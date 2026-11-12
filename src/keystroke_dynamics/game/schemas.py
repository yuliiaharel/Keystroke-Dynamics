"""Request/response schemas for /api/game/*. The game has its own
event schema (GameEventSchema) because a touch room's events also say
where each tap landed; the account API's KeyEventSchema is left
exactly as it is. Nothing game-related imports from db/ at all -- see
api/security.py for why.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from keystroke_dynamics.game.levels import Level
from keystroke_dynamics.game.place import TapPoint, tap_map
from keystroke_dynamics.game.store import Attempt, DeviceType, Mode, Note, Player
from keystroke_dynamics.game.taps import TapEvent

#: Real attempt modes a client can submit via POST /api/game/attempts.
#: "replay" is deliberately excluded -- only the server can start one,
#: via POST /api/game/replay (Part 1 section 6). "disguise" is for
#: keyboard rooms only and "grip" for touch rooms only; api/game.py
#: refuses the wrong one with a 400.
AttemptMode = Literal["attack", "self", "disguise", "grip"]

TargetKind = Literal["player", "sample", "target"]


class GameEventSchema(BaseModel):
    """One key or tap event. dx and dy are sent only from a touch
    room, and only on down events (game/taps.py checks both)."""

    code: str
    action: Literal["down", "up"]
    t_ms: float
    dx: float | None = None
    dy: float | None = None

    def to_tap(self) -> TapEvent:
        return TapEvent(code=self.code, action=self.action, t_ms=self.t_ms, dx=self.dx, dy=self.dy)


class CreatePartyRequest(BaseModel):
    #: Plain str, not Level -- api/game.py checks this against LEVELS
    #: itself and raises a clear 400 for an unknown level (e.g. the
    #: removed "word"), rather than letting pydantic's own Literal
    #: validation reject it with a generic 422.
    level: str
    #: What the creating browser types on, which becomes the room's
    #: own device type. A page from before touch rooms sends nothing
    #: and gets a keyboard room, as before.
    device_type: DeviceType = "keyboard"


class NoteView(BaseModel):
    ch: str
    start_ms: float
    dur_ms: float

    @classmethod
    def from_core(cls, note: Note) -> NoteView:
        return cls(ch=note.ch, start_ms=note.start_ms, dur_ms=note.dur_ms)


class TapPointView(BaseModel):
    """One key of a touch player's tap map: where their taps usually
    land on it, in key widths (x) and heights (y) from its center, and
    how much that varies. x is null for the space bar."""

    code: str
    x: float | None
    x_spread: float | None
    y: float
    y_spread: float

    @classmethod
    def from_core(cls, point: TapPoint) -> TapPointView:
        return cls(
            code=point.code,
            x=point.x,
            x_spread=point.x_spread,
            y=point.y,
            y_spread=point.y_spread,
        )


class PlayerView(BaseModel):
    """Never includes `profile` -- the browser gets a player's
    threshold and median notes (enough to draw their signature ring
    and to show the limit), never the underlying per-feature timing
    stats.

    A touch player's tap map is the one deliberate exception
    (docs/plans/active/MOBILE_PLAN.md Phase 1 section 7): the room
    draws it, so tap-position averages and spreads are sent -- position
    only, and only in responses that go to members of the player's own
    room. The event stream never carries a PlayerView."""

    id: str
    name: str
    color: int
    threshold: float
    notes: list[NoteView]
    kind: TargetKind
    #: The member (browser) that enrolled this player; compare with
    #: PartyView.member_id to tell "on this keyboard" from "on
    #: another one". None for sample bots and the permanent target.
    #: Useless on its own: a member id only counts inside a signed
    #: session cookie.
    owner_member_id: str | None
    #: Empty for every keyboard player.
    tap_map: list[TapPointView]

    @classmethod
    def from_player(cls, player: Player, *, kind: TargetKind) -> PlayerView:
        return cls(
            id=player.id,
            name=player.name,
            color=player.color,
            threshold=player.threshold,
            notes=[NoteView.from_core(n) for n in player.notes],
            kind=kind,
            owner_member_id=player.owner_member_id,
            tap_map=[TapPointView.from_core(p) for p in tap_map(player.place_profile)],
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
    #: alongside distance (docs/plans/done/PARTY_LAUNCH_PLAN.md section 8), kept in
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
    #: False -> typed on a different keyboard from the target's own,
    #: which can change timing (shown as "different keyboard"). None
    #: when it doesn't apply: a bot target, or a replay.
    same_keyboard: bool | None
    #: A touch attempt's timing-only and position-only distances,
    #: shown separately. Null for every keyboard attempt, and for a
    #: touch attempt that couldn't be scored.
    rhythm: float | None
    place: float | None

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
            same_keyboard=attempt.same_keyboard,
            rhythm=attempt.rhythm,
            place=attempt.place,
        )


class PartyView(BaseModel):
    """A room, as one of its members sees it."""

    id: str
    #: The room code, 8 characters with no dash -- the link is
    #: /r/<code>.
    code: str
    #: Goes up on every change to the room.
    version: int
    locked: bool
    #: The member this response was built for.
    member_id: str
    is_host: bool
    member_count: int
    #: What this room's players type on: "keyboard" or "touch".
    device_type: DeviceType
    #: True when this member's own device type differs from the
    #: room's: they can read the room and run a replay, but not enroll,
    #: rename, or type.
    watching: bool
    level: Level
    phrase: str
    players: list[PlayerView]
    #: The sample bots, and the permanent target if one is recorded
    #: for this level -- global, not party-scoped (game/targets.py),
    #: merged in here for the frontend's convenience.
    targets: list[PlayerView]
    attempts: list[AttemptView]
    #: Whether score collection is on (settings.scores_database_url
    #: is set). The frontend shows its score-saving notice only when
    #: this is True -- never derives it from anything else -- so the
    #: privacy text always matches what the server does.
    scores_enabled: bool


class NameSuggestionView(BaseModel):
    name: str


class CreatePlayerRequest(BaseModel):
    #: None -> the server generates one (game/names.py).
    name: str | None = None
    #: 3-8 training lines, per docs/plans/done/PARTY_LAUNCH_PLAN.md Part 1 section 5.
    training_lines: list[list[GameEventSchema]] = Field(min_length=3, max_length=8)


class JoinRoomRequest(BaseModel):
    #: A browser is in one room at a time. Joining a second room is
    #: refused (409) unless this is set, so the page can ask "Leave
    #: your current room and join this one?" first.
    leave_current: bool = False
    #: What the joining browser types on. If it differs from the
    #: room's, this member watches.
    device_type: DeviceType = "keyboard"


class LockRoomRequest(BaseModel):
    locked: bool


class RenamePlayerRequest(BaseModel):
    name: str = Field(min_length=1, max_length=24)


class AttemptRequest(BaseModel):
    #: None -> Guest (not enrolled as a party player, just attacking).
    typist_id: str | None = None
    target_id: str
    mode: AttemptMode
    events: list[GameEventSchema]
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
    a local-only way to record a permanent target (docs/plans/done/PARTY_LAUNCH_PLAN.md
    Part 1 section 7). `lines` maps level -> 3-8 training runs, the
    same shape POST /api/game/players takes, just across every level
    at once instead of one party's own.
    """

    name: str = Field(min_length=1, max_length=24)
    lines: dict[Level, list[list[GameEventSchema]]]
