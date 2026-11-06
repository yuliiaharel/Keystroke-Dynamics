"""Request/response schemas for /api/game/*. Reuses
api.schemas.KeyEventSchema (no db dependency) rather than duplicating
it -- see api/security.py for why nothing game-related imports from
db/ at all.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from keystroke_dynamics.api.schemas import KeyEventSchema
from keystroke_dynamics.game.levels import Level
from keystroke_dynamics.game.store import Attempt, Mode, Note, Player

#: Real attempt modes a client can submit via POST /api/game/attempts.
#: "replay" is deliberately excluded -- only the server can start one,
#: via POST /api/game/replay (Part 1 section 6).
AttemptMode = Literal["attack", "self", "disguise"]

TargetKind = Literal["player", "sample", "target"]


class CreatePartyRequest(BaseModel):
    level: Level


class NoteView(BaseModel):
    ch: str
    start_ms: float
    dur_ms: float

    @classmethod
    def from_core(cls, note: Note) -> NoteView:
        return cls(ch=note.ch, start_ms=note.start_ms, dur_ms=note.dur_ms)


class PlayerView(BaseModel):
    """Never includes `profile` -- the browser gets a player's
    threshold and median notes (enough to draw their signature ring
    and to show the limit), never the underlying per-feature stats."""

    id: str
    name: str
    color: int
    threshold: float
    notes: list[NoteView]
    kind: TargetKind

    @classmethod
    def from_player(cls, player: Player, *, kind: TargetKind) -> PlayerView:
        return cls(
            id=player.id,
            name=player.name,
            color=player.color,
            threshold=player.threshold,
            notes=[NoteView.from_core(n) for n in player.notes],
            kind=kind,
        )


class AttemptView(BaseModel):
    id: str
    typist_name: str
    target_id: str
    target_name: str
    mode: Mode
    distance: float | None
    threshold: float
    ratio: float | None
    #: This attempt's duration over the target's own usual duration,
    #: where 1.0 is the same pace -- shown as its own measure
    #: alongside distance (PARTY_LAUNCH_PLAN.md section 8), kept in
    #: history the same way distance/ratio are. None exactly when
    #: distance is None.
    pace: float | None
    #: Short result label ("Caught!", "That's you", ...) -- the
    #: longer explanation is verdict_text in the response, not
    #: persisted history (matches the approved mockup: attempt
    #: history keeps only the short word, not the full explanation).
    word: str
    counted: bool
    passed: bool | None

    @classmethod
    def from_core(cls, attempt: Attempt) -> AttemptView:
        return cls(
            id=attempt.id,
            typist_name=attempt.typist_name,
            target_id=attempt.target_id,
            target_name=attempt.target_name,
            mode=attempt.mode,
            distance=attempt.distance,
            threshold=attempt.threshold,
            ratio=attempt.ratio,
            pace=attempt.pace,
            word=attempt.word,
            counted=attempt.counted,
            passed=attempt.passed,
        )


class PartyView(BaseModel):
    id: str
    level: Level
    phrase: str
    players: list[PlayerView]
    #: The sample bots, and the permanent target if one is recorded
    #: for this level -- global, not party-scoped (game/targets.py),
    #: merged in here for the frontend's convenience.
    targets: list[PlayerView]
    attempts: list[AttemptView]
    #: PARTY_LAUNCH_PLAN.md section 10: "If it's empty, collection is
    #: off, and the game works normally without showing the opt-in."
    #: The frontend shows the consent checkbox only when this is
    #: True -- never derives it from anything else.
    scores_enabled: bool
    #: scores/consent.py's current wording -- exposed here so the
    #: frontend never carries its own, possibly-stale copy.
    consent_label: str
    consent_explanation: str


class CreatePlayerRequest(BaseModel):
    #: None -> the server generates one (game/names.py).
    name: str | None = None
    #: 3-8 training lines, per PARTY_LAUNCH_PLAN.md Part 1 section 5.
    training_lines: list[list[KeyEventSchema]] = Field(min_length=3, max_length=8)
    #: PARTY_LAUNCH_PLAN.md section 10's opt-in checkbox, unchecked by
    #: default on the client and never a condition of playing --
    #: ignored outright when score collection is off (settings.
    #: scores_database_url unset), same as the checkbox not being
    #: shown at all in that case.
    share_scores: bool = False


class RenamePlayerRequest(BaseModel):
    name: str = Field(min_length=1, max_length=24)


class AttemptRequest(BaseModel):
    #: None -> Guest (not enrolled as a party player, just attacking).
    typist_id: str | None = None
    target_id: str
    mode: AttemptMode
    events: list[KeyEventSchema]
    #: Idempotency key: a retried submission with the same
    #: (typist_id, client_attempt_id) returns the original result
    #: instead of being scored and recorded twice.
    client_attempt_id: str = Field(min_length=1, max_length=64)
    #: The same opt-in as CreatePlayerRequest.share_scores, but for a
    #: Guest attacker, who has no enrolled Player to have opted in at
    #: creation time -- PARTY_LAUNCH_PLAN.md section 10: "for a Guest
    #: before their first attack, show an unchecked option." Ignored
    #: entirely when typist_id is set (a real player's own stored
    #: choice is authoritative then, not anything re-askable per
    #: attempt) or when score collection is off.
    guest_shares_scores: bool = False


class AttemptResponse(BaseModel):
    attempt: AttemptView
    #: The full explanation text for *this* response only -- not
    #: stored in attempt history, matching the mockup's own
    #: last-result-vs-history split.
    verdict_text: str
    #: One-line diagnosis from game/judge.py's _clue() -- same
    #: this-response-only treatment as verdict_text, and None exactly
    #: when attempt.distance is None.
    clue: str | None


class ReplayRequest(BaseModel):
    target_id: str


class ReplayResponse(BaseModel):
    attempt: AttemptView
    verdict_text: str
    clue: str | None
    #: What the browser needs to animate the replay -- the target's
    #: own median notes, already exposed for drawing their signature
    #: ring. Nothing else about the target goes with a replay.
    notes: list[NoteView]


class RecordTargetRequest(BaseModel):
    """Only reachable when settings.debug is true (see api/game.py) --
    a local-only way to record a permanent target (PARTY_LAUNCH_PLAN.md
    Part 1 section 7). `lines` maps level -> 3-8 training runs, the
    same shape POST /api/game/players takes, just across every level
    at once instead of one party's own.
    """

    name: str = Field(min_length=1, max_length=24)
    lines: dict[Level, list[list[KeyEventSchema]]]
