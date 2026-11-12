"""The anonymous party game's API, all under /api/game.

Rooms (docs/plans/active/ROOMS_PLAN.md Phase 1):
POST /rooms, POST /rooms/{code}/join, POST /rooms/leave, GET /room,
POST /room/lock, POST /room/end, DELETE /room/players/{id},
DELETE /room/members/{id}.
Live updates (Phase 2): GET /room/events, a server-sent event stream
that says only "the room is at version N" or "this is over for you".
Play, inside the session's room: GET /room/name-suggestion,
POST /players, PATCH/DELETE /players/{id}, POST /attempts,
POST /replay.
The paths the game used before rooms still answer, for a page that
was loaded before the deploy that moved the frontend to the room
paths (Phase 3):
POST /party = POST /rooms, GET /party = GET /room,
POST /party/reset = POST /rooms/leave.

No accounts, no database (see config.py's enable_accounts). Who a
request comes from is entirely request.session's "room_id" and
"member_id" -- both random, server-generated, and carried in the
signed session cookie, never trusted from a body or a path. Every
route but create and join goes through _room_for_session, which
checks that this member still belongs to this room. A target_id/
typist_id is only ever resolved *within* that room, so a value that
happens to name something in a different room is simply "not found",
never a cross-room leak.

Permissions, in one place:
- any member: read the room, run a replay
- a member whose device type matches the room's (a keyboard in a
  keyboard room, a phone in a touch room): also enroll a player and
  attack any player. Anyone else is watching
  (docs/plans/active/MOBILE_PLAN.md Phase 1 section 1)
- a player's owner (the member who enrolled them): type as, rename,
  or delete that player
- the host: also delete any player, remove a member, lock or unlock
  the room, end the room

Origin check + rate limiting are applied per-route (not at the router
level) because this router, unlike auth.py/profile.py, mixes a
read-only GET with state-changing routes -- see api/pages.py's own
note on why GETs skip the Origin check.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from keystroke_dynamics.api.security import rate_limited, require_matching_origin
from keystroke_dynamics.config import settings
from keystroke_dynamics.core.events import InvalidSampleError, KeyEvent, pair_presses
from keystroke_dynamics.core.features import extract_features
from keystroke_dynamics.game.codes import normalize_code
from keystroke_dynamics.game.enroll import (
    build_profile_and_threshold,
    build_touch_profiles_and_threshold,
    median_notes,
)
from keystroke_dynamics.game.events import (
    MemberStreamLimitError,
    RoomEvents,
    Subscription,
    TotalStreamLimitError,
)
from keystroke_dynamics.game.judge import judge, judge_touch, pace_ratio
from keystroke_dynamics.game.levels import LEVELS, TOUCH_LEVEL
from keystroke_dynamics.game.names import InvalidNameError, generate_name, validate_custom_name
from keystroke_dynamics.game.rate_limit import game_join_rate_limiter, game_rate_limiter
from keystroke_dynamics.game.replay import notes_to_events, notes_to_taps
from keystroke_dynamics.game.schemas import (
    AttemptMode,
    AttemptRequest,
    AttemptResponse,
    AttemptView,
    CreatePartyRequest,
    CreatePlayerRequest,
    GameEventSchema,
    JoinRoomRequest,
    LockRoomRequest,
    NameSuggestionView,
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
    DeviceType,
    GameStore,
    InMemoryGameStore,
    Member,
    MemberRemoval,
    Party,
    PartyFullError,
    PartyLimitReached,
    Player,
    RoomLockedError,
    RoomMembersFullError,
    RoomNotFoundError,
)
from keystroke_dynamics.game.taps import (
    TapEvent,
    to_key_events,
    validate_keyboard_events,
    validate_taps,
)
from keystroke_dynamics.game.targets import (
    SAMPLE_TARGET_ID_PREFIX,
    TARGETS_DIR,
    load_permanent_target,
    sample_targets,
    save_permanent_target,
    save_permanent_touch_target,
    touch_targets_dir,
)
from keystroke_dynamics.game.touch_scoring import extract_touch_line
from keystroke_dynamics.scores.recording import (
    ScoreTargetKind,
    build_score_row,
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
#: read-only GETs, need neither -- see the module docstring).
_STATE_CHANGING = [Depends(require_matching_origin), Depends(rate_limited(game_rate_limiter))]

# One process, one worker (see main.py) -- this in-memory store is
# this one process's entire state. A second worker or container would
# have its own, independent copy, splitting one party across two
# stores with no way to reconcile them. Multi-worker/multi-instance
# "online rooms" is explicitly out of scope for this launch (see
# docs/plans/done/PARTY_LAUNCH_PLAN.md) and would need a shared backend instead of
# this Protocol's in-memory implementation.
_events = RoomEvents(
    streams_per_member_limit=settings.game_streams_per_member_limit,
    streams_total_limit=settings.game_streams_total_limit,
)

_store: GameStore = InMemoryGameStore(
    party_limit=settings.game_party_limit,
    players_per_party_limit=settings.game_players_per_party_limit,
    attempts_per_party_limit=settings.game_attempts_per_party_limit,
    idle_expiry_seconds=settings.game_idle_expiry_seconds,
    members_per_party_limit=settings.game_members_per_party_limit,
    listener=_events,
)


def get_game_store() -> GameStore:
    return _store


def get_room_events() -> RoomEvents:
    return _events


@dataclass(frozen=True)
class RoomSession:
    """The room this request's session belongs to, and which of its
    members is asking."""

    party: Party
    member: Member

    @property
    def is_host(self) -> bool:
        return self.party.host_member_id == self.member.id


#: One answer for a code that never existed, an ended room, and an
#: expired one -- a response that told them apart would tell a
#: guesser which codes were once real.
_ROOM_NOT_FOUND = "room not found"


def _forget_room(request: Request) -> None:
    request.session.pop("room_id", None)
    request.session.pop("member_id", None)


def _current_room(request: Request, store: GameStore) -> RoomSession | None:
    """The session's room, if it still has one. A session pointing at
    a room that's gone (ended, expired, or the process restarted), or
    at a room this member was removed from, loses that link here."""
    room_id = request.session.get("room_id")
    member_id = request.session.get("member_id")
    if room_id is None or member_id is None:
        return None
    party = store.get_party(room_id)
    member = party.members.get(member_id) if party is not None else None
    if party is None or member is None:
        _forget_room(request)
        return None
    store.mark_member_seen(party.id, member.id)
    return RoomSession(party=party, member=member)


def _room_for_session(request: Request, store: GameStore = Depends(get_game_store)) -> RoomSession:
    room = _current_room(request, store)
    if room is None:
        # Deliberately the same whether there was never a room, it
        # ended, or this member was removed from it.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no active room")
    return room


#: What a watcher is told when they try to play, by the room's type.
_WATCHING: dict[DeviceType, str] = {
    "keyboard": "This room is for computers. You can watch it here, but not play.",
    "touch": "This room is for phones. You can watch it here, but not play.",
}

#: The attempt modes each kind of room has. "disguise" needs the
#: keyboard game's pace rule; "grip" is the touch game's own.
_ATTEMPT_MODES: dict[DeviceType, frozenset[AttemptMode]] = {
    "keyboard": frozenset({"attack", "self", "disguise"}),
    "touch": frozenset({"attack", "self", "grip"}),
}


def _is_watching(room: RoomSession) -> bool:
    return room.member.device_type != room.party.device_type


def _playing_room_for_session(room: RoomSession = Depends(_room_for_session)) -> RoomSession:
    """For the routes a watcher can't use: enrolling, renaming, and
    typing. A phone's signature and a keyboard's are never compared,
    so the other kind of device has nothing it could honestly submit."""
    if _is_watching(room):
        raise HTTPException(status.HTTP_403_FORBIDDEN, _WATCHING[room.party.device_type])
    return room


def _host_room_for_session(room: RoomSession = Depends(_room_for_session)) -> RoomSession:
    if not room.is_host:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only the host can do that")
    return room


def _leave(request: Request, store: GameStore, room: RoomSession) -> None:
    """Takes this member out of their room -- their players go with
    them, and so do those players' stored scores (the same promise
    "Delete me" makes). The last member out ends the room."""
    removal = store.remove_member(room.party.id, room.member.id)
    _forget_room(request)
    _delete_scores_after_removal(room.party, removal)


def _delete_scores_after_removal(party: Party, removal: MemberRemoval | None) -> None:
    if removal is None or not settings.scores_database_url:
        return
    if removal.room_ended:
        # party.score_id, not party.id -- the random id score_attempts
        # rows actually carry. Still readable: removing the room from
        # the store doesn't clear this object's own attributes.
        score_writer.enqueue(DeleteByPartyId(party.score_id))
        return
    for player in removal.players:
        score_writer.enqueue(DeleteByPlayerScoreId(player.score_id))


def _validate_events(
    events_schema: list[GameEventSchema], device_type: DeviceType
) -> list[TapEvent]:
    """One submitted line, checked by the rules of the room it was
    sent to: a touch room's events must say where each tap landed, and
    a keyboard room's must not. The events live only as long as the
    request -- never stored, never logged."""
    events = [e.to_tap() for e in events_schema]
    try:
        if device_type == "touch":
            validate_taps(events, max_events=settings.max_events)
        else:
            validate_keyboard_events(events, max_events=settings.max_events)
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


_NOT_YOUR_PLAYER = "that player belongs to another member of this room"


def _same_keyboard(room: RoomSession, target: Player) -> bool | None:
    """Whether the typist and the target belong to the same member.
    The typist's member is always the sender: a member can only type
    as their own players or as Guest. None for a target that isn't a
    player in this room (a sample bot or the permanent target)."""
    if target.id not in room.party.players:
        return None
    return target.owner_member_id == room.member.id


def _party_view(room: RoomSession) -> PartyView:
    party = room.party
    phrase = LEVELS[party.level].phrase
    bots = sample_targets(party.level, phrase)
    targets = [PlayerView.from_player(b, kind="sample") for b in bots]
    permanent = load_permanent_target(party.level)
    if permanent is not None:
        targets.append(PlayerView.from_player(permanent, kind="target"))
    return PartyView(
        id=party.id,
        code=party.code,
        version=party.version,
        locked=party.locked,
        member_id=room.member.id,
        is_host=room.is_host,
        member_count=len(party.members),
        device_type=party.device_type,
        watching=_is_watching(room),
        level=party.level,
        phrase=phrase,
        players=[PlayerView.from_player(p, kind="player") for p in party.players.values()],
        targets=targets,
        attempts=[AttemptView.from_core(a) for a in party.attempts],
        scores_enabled=bool(settings.scores_database_url),
    )


@router.post("/rooms", dependencies=_STATE_CHANGING)
@router.post("/party", dependencies=_STATE_CHANGING)
def create_room(
    body: CreatePartyRequest, request: Request, store: GameStore = Depends(get_game_store)
) -> PartyView:
    if body.level not in LEVELS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown level {body.level!r}")
    if (body.level == TOUCH_LEVEL) != (body.device_type == "touch"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"a touch room always uses the {TOUCH_LEVEL!r} level, and a keyboard room never does",
        )
    previous = _current_room(request, store)
    try:
        party = store.create_party(body.level, body.device_type)
    except PartyLimitReached as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    # A browser is in one room at a time. Leaving the old one only
    # after the new one exists means a "try again soon" above costs
    # nobody the room they already had.
    if previous is not None:
        _leave(request, store, previous)
    request.session["room_id"] = party.id
    request.session["member_id"] = party.host_member_id
    return _party_view(RoomSession(party=party, member=party.members[party.host_member_id]))


@router.post(
    "/rooms/{code}/join",
    dependencies=[*_STATE_CHANGING, Depends(rate_limited(game_join_rate_limiter))],
)
def join_room(
    code: str,
    request: Request,
    body: JoinRoomRequest | None = None,
    store: GameStore = Depends(get_game_store),
) -> PartyView:
    normalized = normalize_code(code)
    if normalized is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _ROOM_NOT_FOUND)
    previous = _current_room(request, store)
    if previous is not None and previous.party.code == normalized:
        # Reopening your own room's link: you're already in it.
        return _party_view(previous)
    if previous is not None and not (body is not None and body.leave_current):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "You're already in another room. Leave it to join this one.",
        )
    try:
        party, member = store.join_party(
            normalized, body.device_type if body is not None else "keyboard"
        )
    except RoomNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _ROOM_NOT_FOUND) from exc
    except RoomLockedError as exc:
        raise HTTPException(status.HTTP_423_LOCKED, str(exc)) from exc
    except RoomMembersFullError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    # Only once the join worked -- a bad code must never cost someone
    # the room they were in.
    if previous is not None:
        _leave(request, store, previous)
    request.session["room_id"] = party.id
    request.session["member_id"] = member.id
    return _party_view(RoomSession(party=party, member=member))


@router.get("/room")
@router.get("/party")
def get_room(room: RoomSession = Depends(_room_for_session)) -> PartyView:
    return _party_view(room)


_STREAM_ENDED = 'data: {"ended":true}\n\n'
_STREAM_HEARTBEAT = ": keep-alive\n\n"


def _stream_version(version: int) -> str:
    return f"data: {json.dumps({'version': version}, separators=(',', ':'))}\n\n"


async def _event_stream(
    subscription: Subscription, store: GameStore, heartbeat_seconds: float
) -> AsyncIterator[str]:
    """Everything a stream ever sends: version numbers, heartbeat
    comments, and one final "ended". Never anything from the room
    itself -- the browser reads that through GET /room, behind the
    usual checks."""

    def live_version() -> int | None:
        # get_party is also what notices an expired room, which is why
        # a stream nobody else is touching still ends on time.
        party = store.get_party(subscription.party_id)
        if party is None or subscription.member_id not in party.members:
            return None
        return party.version

    # Read after subscribing, so a change between the two is sent
    # twice rather than missed. Sending it at all is what lets a
    # browser that reconnects find out what it missed.
    version = live_version()
    while version is not None:
        yield _stream_version(version)
        while True:
            try:
                version = await asyncio.wait_for(subscription.next(), heartbeat_seconds)
                break
            except TimeoutError:
                if live_version() is None:
                    version = None
                    break
                yield _STREAM_HEARTBEAT
    # The same line whether the room ended or expired, or this member
    # left or was removed: for this browser they all mean "stop".
    yield _STREAM_ENDED


class _EventStreamResponse(StreamingResponse):
    """Runs on_close however the response ends -- a finished stream,
    a disconnect, or a client that went away before the first byte --
    so a stream's slot under the caps is always given back. A
    `finally` in the generator wouldn't do: it never runs if the
    generator was never started."""

    def __init__(self, content: AsyncIterator[str], on_close: Callable[[], None]) -> None:
        super().__init__(
            content,
            media_type="text/event-stream",
            headers={
                # DigitalOcean's own SSE guidance (configure-edge-settings):
                # this content type plus no-cache.
                "Cache-Control": "no-cache",
                # Asks nginx-style proxies not to buffer the stream.
                "X-Accel-Buffering": "no",
            },
        )
        self._on_close = on_close

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._on_close()


@router.get("/room/events")
async def room_events(
    room: RoomSession = Depends(_room_for_session),
    store: GameStore = Depends(get_game_store),
    events: RoomEvents = Depends(get_room_events),
) -> StreamingResponse:
    """Async, unlike the rest of this router: a stream lives for
    minutes, and a sync route would hold a threadpool thread for all
    of it. No Origin check or rate limit (a GET that changes nothing;
    an EventSource can't send an Origin anyway) -- the two caps are
    what bound it."""
    try:
        subscription = events.subscribe(room.party.id, room.member.id)
    except MemberStreamLimitError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    except TotalStreamLimitError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return _EventStreamResponse(
        _event_stream(subscription, store, settings.game_stream_heartbeat_seconds),
        on_close=lambda: events.unsubscribe(subscription),
    )


@router.post(
    "/rooms/leave",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=_STATE_CHANGING,
)
@router.post(
    "/party/reset",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=_STATE_CHANGING,
)
def leave_room(
    request: Request,
    room: RoomSession = Depends(_room_for_session),
    store: GameStore = Depends(get_game_store),
) -> None:
    _leave(request, store, room)


@router.post("/room/lock", dependencies=_STATE_CHANGING)
def lock_room(
    body: LockRoomRequest,
    room: RoomSession = Depends(_host_room_for_session),
    store: GameStore = Depends(get_game_store),
) -> PartyView:
    store.set_locked(room.party.id, body.locked)
    return _party_view(room)


@router.post(
    "/room/end",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=_STATE_CHANGING,
)
def end_room(
    request: Request,
    room: RoomSession = Depends(_host_room_for_session),
    store: GameStore = Depends(get_game_store),
) -> None:
    """Ends the room for everyone. Other members' streams are told
    at once; their sessions drop the link on their next request, in
    _current_room."""
    store.delete_party(room.party.id)
    _forget_room(request)
    if settings.scores_database_url:
        score_writer.enqueue(DeleteByPartyId(room.party.score_id))


@router.delete(
    "/room/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=_STATE_CHANGING,
)
def remove_member(
    member_id: str,
    room: RoomSession = Depends(_host_room_for_session),
    store: GameStore = Depends(get_game_store),
) -> None:
    """Host only: removes another browser from the room, with its
    players. That browser's session loses the room on its next
    request."""
    if member_id == room.member.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "leave the room instead of removing yourself"
        )
    removal = store.remove_member(room.party.id, member_id)
    if removal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "member not found")
    _delete_scores_after_removal(room.party, removal)


def _unused_generated_name(existing_names: set[str]) -> str:
    """A generated name that isn't in `existing_names` (lowercased).
    Terminates because a room holds far fewer players than
    generate_name has combinations."""
    name = generate_name()
    while name.lower() in existing_names:
        name = generate_name()
    return name


@router.get("/room/name-suggestion")
def suggest_name(room: RoomSession = Depends(_room_for_session)) -> NameSuggestionView:
    """A generated name no player in the room has, for the name step
    to offer. Only a suggestion: nothing is reserved, so POST /players
    still checks whatever name comes back."""
    existing_names = {p.name.lower() for p in room.party.players.values()}
    return NameSuggestionView(name=_unused_generated_name(existing_names))


@router.post("/players", dependencies=_STATE_CHANGING)
def create_player(
    body: CreatePlayerRequest,
    room: RoomSession = Depends(_playing_room_for_session),
    store: GameStore = Depends(get_game_store),
) -> PlayerView:
    party = room.party
    phrase = LEVELS[party.level].phrase
    taps = [_validate_events(line, party.device_type) for line in body.training_lines]
    runs = [to_key_events(line) for line in taps]

    existing_names = {p.name.lower() for p in party.players.values()}
    if body.name is not None:
        try:
            name = validate_custom_name(body.name, existing_names=existing_names)
        except InvalidNameError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.reason) from exc
    else:
        name = _unused_generated_name(existing_names)

    if party.device_type == "touch":
        profile, place_profile, threshold = build_touch_profiles_and_threshold(phrase, taps)
    else:
        profile, threshold = build_profile_and_threshold(phrase, runs)
        place_profile = {}
    notes = median_notes(phrase, runs)
    player = Player(
        id=str(uuid.uuid4()),
        name=name,
        color=len(party.players) % 6,
        profile=profile,
        place_profile=place_profile,
        threshold=threshold,
        notes=notes,
        training_line_count=len(runs),
        owner_member_id=room.member.id,
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
    room: RoomSession = Depends(_playing_room_for_session),
    store: GameStore = Depends(get_game_store),
) -> PlayerView:
    party = room.party
    player = party.players.get(player_id)
    if player is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "player not found")
    # Owner only -- not even the host renames someone else's player.
    if player.owner_member_id != room.member.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _NOT_YOUR_PLAYER)
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
    "/room/players/{player_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=_STATE_CHANGING,
)
@router.delete(
    "/players/{player_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=_STATE_CHANGING,
)
def delete_player(
    player_id: str,
    room: RoomSession = Depends(_room_for_session),
    store: GameStore = Depends(get_game_store),
) -> None:
    party = room.party
    # Read before deleting: once gone from the store, there's no
    # other way to find this player's score_id.
    player = party.players.get(player_id)
    if player is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "player not found")
    if player.owner_member_id != room.member.id and not room.is_host:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _NOT_YOUR_PLAYER)
    if not store.delete_player(party.id, player_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "player not found")
    if settings.scores_database_url:
        score_writer.enqueue(DeleteByPlayerScoreId(player.score_id))


@router.post("/attempts", dependencies=_STATE_CHANGING)
def create_attempt(
    body: AttemptRequest,
    room: RoomSession = Depends(_playing_room_for_session),
    store: GameStore = Depends(get_game_store),
) -> AttemptResponse:
    party = room.party
    if body.mode not in _ATTEMPT_MODES[party.device_type]:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{body.mode!r} attempts aren't part of a {party.device_type} room",
        )
    if body.typist_id is not None:
        typist = party.players.get(body.typist_id)
        if typist is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown typist")
        # You may only type as a player you enrolled. Anyone may
        # attack as Guest (typist_id None), tied to the sending member
        # through Attempt.member_id below.
        if typist.owner_member_id != room.member.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, _NOT_YOUR_PLAYER)
    target = _resolve_target(party, body.target_id)
    if target is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown target")

    events = _validate_events(body.events, party.device_type)
    phrase = LEVELS[party.level].phrase
    run_duration_ms = events[-1].t_ms if events else 0.0
    typist_name = party.players[body.typist_id].name if body.typist_id else "Guest"
    if party.device_type == "touch":
        verdict = judge_touch(
            extract_touch_line(events),
            typist_name=typist_name,
            target=target,
            mode=body.mode,
            phrase=phrase,
            run_duration_ms=run_duration_ms,
        )
    else:
        verdict = judge(
            extract_features(pair_presses(to_key_events(events))),
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
            if a.member_id == room.member.id
            and a.typist_id == body.typist_id
            and a.client_attempt_id == body.client_attempt_id
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
        member_id=room.member.id,
        same_keyboard=_same_keyboard(room, target),
        rhythm=verdict.rhythm,
        place=verdict.place,
    )
    store.add_attempt(party.id, attempt)

    if settings.scores_database_url:
        typist_player = party.players[body.typist_id] if body.typist_id else None
        row = build_score_row(
            verdict=verdict,
            pace=pace_ratio(run_duration_ms, target),
            mode=body.mode,
            target_kind=_score_target_kind(party, target),
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
            same_keyboard=attempt.same_keyboard,
            device_type=party.device_type,
        )
        score_writer.enqueue(InsertRow(row))

    return AttemptResponse(
        attempt=AttemptView.from_core(attempt), verdict_text=verdict.text, clue=verdict.clue
    )


@router.post("/replay", dependencies=_STATE_CHANGING)
def create_replay(
    body: ReplayRequest,
    room: RoomSession = Depends(_room_for_session),
    store: GameStore = Depends(get_game_store),
) -> ReplayResponse:
    party = room.party
    target = _resolve_target(party, body.target_id)
    if target is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown target")

    phrase = LEVELS[party.level].phrase
    if party.device_type == "touch":
        taps = notes_to_taps(target.notes, target.place_profile)
        run_duration_ms = taps[-1].t_ms if taps else 0.0
        verdict = judge_touch(
            extract_touch_line(taps),
            typist_name="Replay bot",
            target=target,
            mode="replay",
            phrase=phrase,
            run_duration_ms=run_duration_ms,
        )
    else:
        events = notes_to_events(target.notes)
        run_duration_ms = events[-1].t_ms if events else 0.0
        verdict = judge(
            extract_features(pair_presses(events)),
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
        member_id=room.member.id,
        rhythm=verdict.rhythm,
        place=verdict.place,
    )
    store.add_attempt(party.id, attempt)

    if settings.scores_database_url:
        row = build_score_row(
            verdict=verdict,
            pace=pace_ratio(run_duration_ms, target),
            mode="replay",
            target_kind=_score_target_kind(party, target),
            line_id=party.level,
            party_id=party.score_id,
            # No real typist -- a fresh, disposable random id,
            # same reasoning as a Guest attacker's typist_id above.
            typist_id=str(uuid.uuid4()),
            target_id=target.score_id,
            training_lines=target.training_line_count,
            limit_value=target.threshold,
            # Nobody typed a replay, so there's no keyboard to compare.
            same_keyboard=None,
            device_type=party.device_type,
        )
        score_writer.enqueue(InsertRow(row))

    return ReplayResponse(
        attempt=AttemptView.from_core(attempt),
        verdict_text=verdict.text,
        clue=verdict.clue,
        notes=[NoteView.from_core(n) for n in target.notes],
    )


if settings.debug:
    # Local-only (docs/plans/done/PARTY_LAUNCH_PLAN.md Part 1 section 7): this route
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
        filename = f"{body.name.lower().replace(' ', '-')}.json"
        if TOUCH_LEVEL in body.lines:
            # A touch target is recorded on its own, into its own
            # file, so it can't replace a keyboard target's.
            if len(body.lines) > 1:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "record the touch line separately from the keyboard lines",
                )
            runs = [_validate_events(line, "touch") for line in body.lines[TOUCH_LEVEL]]
            touch_targets_dir().mkdir(parents=True, exist_ok=True)
            save_permanent_touch_target(touch_targets_dir() / filename, name=body.name, runs=runs)
            return
        lines: dict[str, list[list[KeyEvent]]] = {
            level: [to_key_events(_validate_events(line, "keyboard")) for line in runs]
            for level, runs in body.lines.items()
        }
        TARGETS_DIR.mkdir(parents=True, exist_ok=True)
        save_permanent_target(TARGETS_DIR / filename, name=body.name, lines=lines)
