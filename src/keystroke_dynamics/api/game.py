"""POST/GET /api/game/party, POST /api/game/party/reset,
POST /api/game/players, PATCH/DELETE /api/game/players/{id},
POST /api/game/attempts, POST /api/game/replay.

The anonymous party game: no accounts, no database (see config.py's
enable_accounts). A party's identity comes entirely from
request.session["party_id"] -- never trusted from the request body or
a path parameter without first checking the session actually owns it
(_party_for_session). A target_id/typist_id is only ever resolved
*within* that same party, so a value that happens to name something
in a different party is simply "not found", never a cross-party leak.

Origin check + rate limiting are applied per-route (not at the router
level) because this router, unlike auth.py/profile.py, mixes a
read-only GET with state-changing routes -- see api/pages.py's own
note on why GETs skip the Origin check.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status

from keystroke_dynamics.api.schemas import KeyEventSchema
from keystroke_dynamics.api.security import rate_limited, require_matching_origin
from keystroke_dynamics.config import settings
from keystroke_dynamics.core.events import InvalidSampleError, KeyEvent, pair_presses, validate
from keystroke_dynamics.core.features import extract_features
from keystroke_dynamics.game.enroll import build_profile_and_threshold, median_notes
from keystroke_dynamics.game.judge import judge, pace_ratio
from keystroke_dynamics.game.levels import LEVELS
from keystroke_dynamics.game.names import InvalidNameError, generate_name, validate_custom_name
from keystroke_dynamics.game.rate_limit import game_rate_limiter
from keystroke_dynamics.game.replay import notes_to_events
from keystroke_dynamics.game.schemas import (
    AttemptRequest,
    AttemptResponse,
    AttemptView,
    CreatePartyRequest,
    CreatePlayerRequest,
    NoteView,
    PartyView,
    PlayerView,
    RecordTargetRequest,
    RenamePlayerRequest,
    ReplayRequest,
    ReplayResponse,
)
from keystroke_dynamics.game.store import (
    REPLAY_TYPIST_ID,
    Attempt,
    GameStore,
    InMemoryGameStore,
    Party,
    PartyFullError,
    PartyLimitReached,
    Player,
)
from keystroke_dynamics.game.targets import (
    SAMPLE_TARGET_ID_PREFIX,
    TARGETS_DIR,
    load_permanent_target,
    sample_targets,
    save_permanent_target,
)
from keystroke_dynamics.scores.consent import CONSENT_EXPLANATION, CONSENT_LABEL, CONSENT_VERSION
from keystroke_dynamics.scores.recording import (
    ScoreTargetKind,
    build_score_row,
    should_record_score,
)
from keystroke_dynamics.scores.writer import (
    DeleteByPartyId,
    DeleteByPlayerScoreId,
    InsertRow,
    score_writer,
)

router = APIRouter(prefix="/api/game")

#: Every state-changing route gets both: the Origin check and this
#: game's own rate limiter (api/pages.py's GETs, and this router's own
#: GET /party, need neither -- see the module docstring).
_STATE_CHANGING = [Depends(require_matching_origin), Depends(rate_limited(game_rate_limiter))]

# One process, one worker (see main.py) -- this in-memory store is
# this one process's entire state. A second worker or container would
# have its own, independent copy, splitting one party across two
# stores with no way to reconcile them. Multi-worker/multi-instance
# "online rooms" is explicitly out of scope for this launch (see
# PARTY_LAUNCH_PLAN.md) and would need a shared backend instead of
# this Protocol's in-memory implementation.
_store: GameStore = InMemoryGameStore(
    party_limit=settings.game_party_limit,
    players_per_party_limit=settings.game_players_per_party_limit,
    attempts_per_party_limit=settings.game_attempts_per_party_limit,
    idle_expiry_seconds=settings.game_idle_expiry_seconds,
)


def get_game_store() -> GameStore:
    return _store


def _party_for_session(request: Request, store: GameStore = Depends(get_game_store)) -> Party:
    party_id = request.session.get("party_id")
    if party_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no active party")
    party = store.get_party(party_id)
    if party is None:
        # Gone (expired or the process restarted) -- drop the stale
        # reference so the next request doesn't keep hitting this.
        request.session.pop("party_id", None)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "party not found or expired")
    return party


def _validate_events(events_schema: list[KeyEventSchema]) -> list[KeyEvent]:
    events = [e.to_core() for e in events_schema]
    try:
        validate(events, max_events=settings.max_events)
    except InvalidSampleError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return events


def _resolve_target(party: Party, target_id: str) -> Player | None:
    """Looks a target_id up among this party's own real players
    first, then the global sample bots and permanent target for this
    party's level -- never any other party's players."""
    if target_id in party.players:
        return party.players[target_id]
    phrase = LEVELS[party.level].phrase
    for bot in sample_targets(party.level, phrase):
        if bot.id == target_id:
            return bot
    permanent = load_permanent_target(party.level)
    if permanent is not None and permanent.id == target_id:
        return permanent
    return None


def _score_target_kind(party: Party, target: Player) -> ScoreTargetKind:
    """score_attempts.target_kind's own vocabulary (never
    game/schemas.py's PlayerView.kind TargetKind, a different label
    set for the frontend) -- derived from the same ids _resolve_target
    already distinguishes by, not stored anywhere on Player itself."""
    if target.id in party.players:
        return "player"
    if target.id.startswith(SAMPLE_TARGET_ID_PREFIX):
        return "simulated"
    return "permanent"


def _party_view(party: Party) -> PartyView:
    phrase = LEVELS[party.level].phrase
    bots = sample_targets(party.level, phrase)
    targets = [PlayerView.from_player(b, kind="sample") for b in bots]
    permanent = load_permanent_target(party.level)
    if permanent is not None:
        targets.append(PlayerView.from_player(permanent, kind="target"))
    return PartyView(
        id=party.id,
        level=party.level,
        phrase=phrase,
        players=[PlayerView.from_player(p, kind="player") for p in party.players.values()],
        targets=targets,
        attempts=[AttemptView.from_core(a) for a in party.attempts],
        scores_enabled=bool(settings.scores_database_url),
        consent_label=CONSENT_LABEL,
        consent_explanation=CONSENT_EXPLANATION,
    )


@router.post("/party", dependencies=_STATE_CHANGING)
def create_party(
    body: CreatePartyRequest, request: Request, store: GameStore = Depends(get_game_store)
) -> PartyView:
    try:
        party = store.create_party(body.level)
    except PartyLimitReached as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    # Replaces any party this session already had -- the old one is
    # simply orphaned and expires normally, same as an abandoned tab.
    request.session["party_id"] = party.id
    return _party_view(party)


@router.get("/party")
def get_party(party: Party = Depends(_party_for_session)) -> PartyView:
    return _party_view(party)


@router.post(
    "/party/reset",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=_STATE_CHANGING,
)
def reset_party(
    request: Request,
    party: Party = Depends(_party_for_session),
    store: GameStore = Depends(get_game_store),
) -> None:
    store.delete_party(party.id)
    request.session.pop("party_id", None)
    if settings.scores_database_url:
        # party.score_id, not party.id -- the random id score_attempts
        # rows actually carry (PARTY_LAUNCH_PLAN.md section 10). Still
        # readable here: deleting from the store's internal dict
        # doesn't clear this local Party object's own attributes.
        score_writer.enqueue(DeleteByPartyId(party.score_id))


@router.post("/players", dependencies=_STATE_CHANGING)
def create_player(
    body: CreatePlayerRequest,
    party: Party = Depends(_party_for_session),
    store: GameStore = Depends(get_game_store),
) -> PlayerView:
    phrase = LEVELS[party.level].phrase
    runs = [_validate_events(line) for line in body.training_lines]

    existing_names = {p.name.lower() for p in party.players.values()}
    if body.name is not None:
        try:
            name = validate_custom_name(body.name, existing_names=existing_names)
        except InvalidNameError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.reason) from exc
    else:
        name = generate_name()
        while name.lower() in existing_names:
            name = generate_name()

    profile, threshold = build_profile_and_threshold(phrase, runs)
    notes = median_notes(phrase, runs)
    # Consent is captured once, here, at enrollment -- never
    # re-askable later, and ignored outright when score collection is
    # off (PARTY_LAUNCH_PLAN.md section 10), same as the checkbox not
    # being shown at all in that case.
    shares_scores = bool(settings.scores_database_url) and body.share_scores
    player = Player(
        id=str(uuid.uuid4()),
        name=name,
        color=len(party.players) % 6,
        profile=profile,
        threshold=threshold,
        notes=notes,
        training_line_count=len(runs),
        shares_scores=shares_scores,
        consent_version=CONSENT_VERSION if shares_scores else None,
    )
    try:
        store.add_player(party.id, player)
    except PartyFullError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return PlayerView.from_player(player, kind="player")


@router.patch(
    "/players/{player_id}",
    dependencies=_STATE_CHANGING,
)
def rename_player(
    player_id: str,
    body: RenamePlayerRequest,
    party: Party = Depends(_party_for_session),
    store: GameStore = Depends(get_game_store),
) -> PlayerView:
    if player_id not in party.players:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "player not found")
    existing_names = {p.name.lower() for p in party.players.values() if p.id != player_id}
    try:
        name = validate_custom_name(body.name, existing_names=existing_names)
    except InvalidNameError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.reason) from exc
    store.rename_player(party.id, player_id, name)
    updated_party = store.get_party(party.id)
    assert updated_party is not None  # we just renamed a player in it
    return PlayerView.from_player(updated_party.players[player_id], kind="player")


@router.delete(
    "/players/{player_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=_STATE_CHANGING,
)
def delete_player(
    player_id: str,
    party: Party = Depends(_party_for_session),
    store: GameStore = Depends(get_game_store),
) -> None:
    # Read before deleting: once gone from the store, there's no
    # other way to find this player's score_id.
    player = party.players.get(player_id)
    if not store.delete_player(party.id, player_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "player not found")
    if settings.scores_database_url and player is not None:
        score_writer.enqueue(DeleteByPlayerScoreId(player.score_id))


@router.post("/attempts", dependencies=_STATE_CHANGING)
def create_attempt(
    body: AttemptRequest,
    party: Party = Depends(_party_for_session),
    store: GameStore = Depends(get_game_store),
) -> AttemptResponse:
    if body.typist_id is not None and body.typist_id not in party.players:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown typist")
    target = _resolve_target(party, body.target_id)
    if target is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown target")

    events = _validate_events(body.events)
    sample = extract_features(pair_presses(events))
    phrase = LEVELS[party.level].phrase
    run_duration_ms = events[-1].t_ms if events else 0.0
    typist_name = party.players[body.typist_id].name if body.typist_id else "Guest"
    verdict = judge(
        sample,
        typist_name=typist_name,
        target=target,
        mode=body.mode,
        phrase=phrase,
        run_duration_ms=run_duration_ms,
    )

    duplicate = next(
        (
            a
            for a in party.attempts
            if a.typist_id == body.typist_id and a.client_attempt_id == body.client_attempt_id
        ),
        None,
    )
    if duplicate is not None:
        return AttemptResponse(
            attempt=AttemptView.from_core(duplicate), verdict_text=verdict.text, clue=verdict.clue
        )

    attempt = Attempt(
        id=str(uuid.uuid4()),
        typist_name=typist_name,
        typist_id=body.typist_id,
        target_id=target.id,
        target_name=target.name,
        mode=body.mode,
        distance=verdict.distance,
        threshold=target.threshold,
        ratio=verdict.ratio,
        pace=verdict.pace,
        word=verdict.word,
        counted=verdict.counted,
        passed=verdict.passed,
        client_attempt_id=body.client_attempt_id,
    )
    store.add_attempt(party.id, attempt)

    if settings.scores_database_url:
        typist_player = party.players[body.typist_id] if body.typist_id else None
        typist_consents = typist_player.shares_scores if typist_player else body.guest_shares_scores
        target_kind = _score_target_kind(party, target)
        target_consents = target.shares_scores if target_kind == "player" else True
        if should_record_score(
            typist_consents=typist_consents,
            target_kind=target_kind,
            target_consents=target_consents,
        ):
            consent_version = (
                typist_player.consent_version
                if typist_player and typist_player.consent_version
                else CONSENT_VERSION
            )
            row = build_score_row(
                verdict=verdict,
                pace=pace_ratio(run_duration_ms, target),
                mode=body.mode,
                target_kind=target_kind,
                line_id=party.level,
                party_id=party.score_id,
                # A Guest has no Player object to carry a stable
                # score_id -- each Guest attempt gets its own fresh,
                # disposable random id instead, never reused, so
                # Guest attempts can't even be correlated with each
                # other through this column (there's no "Delete me"
                # for a Guest either, consistent with that).
                typist_id=typist_player.score_id if typist_player else str(uuid.uuid4()),
                target_id=target.score_id,
                training_lines=target.training_line_count,
                limit_value=target.threshold,
                consent_version=consent_version,
            )
            score_writer.enqueue(InsertRow(row))

    return AttemptResponse(
        attempt=AttemptView.from_core(attempt), verdict_text=verdict.text, clue=verdict.clue
    )


@router.post("/replay", dependencies=_STATE_CHANGING)
def create_replay(
    body: ReplayRequest,
    party: Party = Depends(_party_for_session),
    store: GameStore = Depends(get_game_store),
) -> ReplayResponse:
    target = _resolve_target(party, body.target_id)
    if target is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown target")

    phrase = LEVELS[party.level].phrase
    events = notes_to_events(target.notes)
    sample = extract_features(pair_presses(events))
    run_duration_ms = events[-1].t_ms if events else 0.0
    verdict = judge(
        sample,
        typist_name="Replay bot",
        target=target,
        mode="replay",
        phrase=phrase,
        run_duration_ms=run_duration_ms,
    )
    attempt = Attempt(
        id=str(uuid.uuid4()),
        typist_name="Replay bot",
        typist_id=REPLAY_TYPIST_ID,
        target_id=target.id,
        target_name=target.name,
        mode="replay",
        distance=verdict.distance,
        threshold=target.threshold,
        ratio=verdict.ratio,
        pace=verdict.pace,
        word=verdict.word,
        counted=verdict.counted,
        passed=verdict.passed,
    )
    store.add_attempt(party.id, attempt)

    if settings.scores_database_url:
        # The replay bot isn't a real person -- there's no typist
        # consent to require (should_record_score's own doc on why).
        target_kind = _score_target_kind(party, target)
        target_consents = target.shares_scores if target_kind == "player" else True
        if should_record_score(
            typist_consents=True, target_kind=target_kind, target_consents=target_consents
        ):
            consent_version = (
                target.consent_version
                if target_kind == "player" and target.consent_version
                else CONSENT_VERSION
            )
            row = build_score_row(
                verdict=verdict,
                pace=pace_ratio(run_duration_ms, target),
                mode="replay",
                target_kind=target_kind,
                line_id=party.level,
                party_id=party.score_id,
                # No real typist -- a fresh, disposable random id,
                # same reasoning as a Guest attacker's typist_id above.
                typist_id=str(uuid.uuid4()),
                target_id=target.score_id,
                training_lines=target.training_line_count,
                limit_value=target.threshold,
                consent_version=consent_version,
            )
            score_writer.enqueue(InsertRow(row))

    return ReplayResponse(
        attempt=AttemptView.from_core(attempt),
        verdict_text=verdict.text,
        clue=verdict.clue,
        notes=[NoteView.from_core(n) for n in target.notes],
    )


if settings.debug:
    # Local-only (PARTY_LAUNCH_PLAN.md Part 1 section 7): this route
    # is never even registered -- not just rejected -- unless
    # settings.debug is true, so it can't exist in a real deployment
    # (debug must be false there; see config.py's own validator).
    # Meant to be run once, by hand, on a developer's own machine to
    # record a permanent target -- not something the game itself
    # ever calls.
    @router.post(
        "/debug/record-target",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(require_matching_origin)],
    )
    def record_target(body: RecordTargetRequest) -> None:
        lines: dict[str, list[list[KeyEvent]]] = {
            level: [_validate_events(line) for line in runs] for level, runs in body.lines.items()
        }
        TARGETS_DIR.mkdir(parents=True, exist_ok=True)
        path = TARGETS_DIR / f"{body.name.lower().replace(' ', '-')}.json"
        save_permanent_target(path, name=body.name, lines=lines)
