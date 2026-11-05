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


class CreatePlayerRequest(BaseModel):
    #: None -> the server generates one (game/names.py).
    name: str | None = None
    #: 3-8 training lines, per PARTY_LAUNCH_PLAN.md Part 1 section 5.
    training_lines: list[list[KeyEventSchema]] = Field(min_length=3, max_length=8)


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


class AttemptResponse(BaseModel):
    attempt: AttemptView
    #: The full explanation text for *this* response only -- not
    #: stored in attempt history, matching the mockup's own
    #: last-result-vs-history split.
    verdict_text: str


class ReplayRequest(BaseModel):
    target_id: str


class ReplayResponse(BaseModel):
    attempt: AttemptView
    verdict_text: str
    #: What the browser needs to animate the replay -- the target's
    #: own median notes, already exposed for drawing their signature
    #: ring. Nothing else about the target goes with a replay.
    notes: list[NoteView]
