"""In-memory game state: rooms, their members, players, attempts.

A room is still called `Party` in code (docs/plans/active/ROOMS_PLAN.md
Phase 1 section 1: rename only if it's small and safe -- it isn't,
the name runs through the API, the scores table, and every test).
Users only ever see the word "room".

One process, one worker, no database -- see main.py's docstring for
why single-worker is deliberate. A `threading.Lock` guards every
mutation anyway, since FastAPI still dispatches sync routes to a
threadpool (multiple requests really do run concurrently within this
one process).

Deliberately behind a narrow Protocol (GameStore) so a later, real
multi-worker "online rooms" backend (out of scope for this launch --
see docs/plans/done/PARTY_LAUNCH_PLAN.md) can be swapped in without changing
api/game.py.

Player never retains raw training lines or events after enrollment --
only the derived profile (Welford stats, not raw timestamps), the
calibrated threshold, and the precomputed display notes the ring/roll
need. Building that fully is api/game.py's job (it already has
core.events/core.features/game.scoring to do it with); this module
just stores the result.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal, Protocol

from keystroke_dynamics.core.features import FeatureKey
from keystroke_dynamics.core.stats import RunningStats
from keystroke_dynamics.game.codes import generate_code
from keystroke_dynamics.game.levels import Level

Mode = Literal["attack", "self", "disguise", "replay"]

#: What a member's browser types on. Everyone is "keyboard" until the
#: mobile version adds "touch" (docs/plans/active/MOBILE_PLAN.md); it
#: lives on the member so that later an attack can be refused when the
#: typist's and the target owner's device types differ.
DeviceType = Literal["keyboard", "touch"]


@dataclass(frozen=True)
class Note:
    """One key's position in the precomputed median timing used to
    draw a player's ring and roll -- never raw per-line data."""

    ch: str
    start_ms: float
    dur_ms: float


@dataclass(frozen=True)
class Player:
    id: str
    name: str
    color: int
    profile: dict[FeatureKey, RunningStats]
    threshold: float
    notes: list[Note]
    created_at: float = field(default_factory=time.monotonic)
    #: A random id, never derived from `id` -- docs/plans/done/PARTY_LAUNCH_PLAN.md
    #: section 10's own requirement for score_attempts.typist_id/
    #: target_id. Its lifetime is simply this Player object's: once a
    #: player is deleted or their party expires, this value is nowhere
    #: in memory anymore, which is exactly what makes "Delete me"/
    #: "New party" able to find and remove their stored rows while
    #: they're still around, and exactly why nothing can be done once
    #: they aren't (see api/game.py's scores-deletion calls and
    #: howView()'s privacy text). For the sample bots and the
    #: permanent target -- not party-scoped, so there's no Player
    #: object lifetime to ride -- see scores/target_ids.py instead.
    score_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    #: How many training lines went into this player's profile --
    #: score_attempts.training_lines. Captured once at enrollment,
    #: since the raw lines themselves are never kept past it.
    training_line_count: int = 0
    #: The room member (browser) that enrolled this player, and the
    #: only one allowed to type as, rename, or delete them (the host
    #: may also delete). None only for the sample bots and the
    #: permanent target, which belong to no room.
    owner_member_id: str | None = None


@dataclass(frozen=True)
class Attempt:
    id: str
    typist_name: str
    typist_id: str | None  # None for Guest, REPLAY_TYPIST_ID for a server-run replay
    target_id: str
    target_name: str
    mode: Mode
    distance: float | None
    threshold: float
    ratio: float | None
    word: str
    counted: bool
    passed: bool | None
    #: This attempt's duration over the target's own usual duration
    #: for the line (game/judge.py's pace) -- None exactly when
    #: distance is None. Defaulted so existing callers/tests that
    #: don't care about pace don't need updating.
    pace: float | None = None
    created_at: float = field(default_factory=time.monotonic)
    #: The client-supplied idempotency key for POST /api/game/attempts
    #: (see api/game.py) -- None for attempts that don't need one
    #: (server-initiated replays). A retried submission with the same
    #: (typist_id, client_attempt_id) returns the original Attempt
    #: instead of scoring and recording a duplicate.
    client_attempt_id: str | None = None
    #: The member whose browser sent this attempt -- what ties a
    #: Guest's attempt (typist_id None) to someone, and what keeps
    #: two browsers' client_attempt_ids from ever colliding.
    #: api/game.py always sets it.
    member_id: str | None = None
    #: Whether the typist and the target belong to the same member,
    #: i.e. were typed on the same keyboard. None when that question
    #: has no answer: the target is a sample bot or the permanent
    #: target, or the "typist" is the replay bot.
    same_keyboard: bool | None = None


#: Attempt.typist_id for a server-run replay (game/replay.py) -- never
#: a real player, but distinct from Guest (None) in attempt history.
REPLAY_TYPIST_ID = "replay"


@dataclass
class Member:
    """One browser in a room. Anonymous: nothing here but random ids
    and clock readings."""

    id: str
    device_type: DeviceType = "keyboard"
    created_at: float = field(default_factory=time.monotonic)
    last_seen: float = field(default_factory=time.monotonic)


@dataclass
class Party:
    id: str
    level: Level
    #: The shareable room code (game/codes.py) -- unique among live
    #: rooms, and the only thing a joiner needs.
    code: str
    #: Starts as the member who created the room; passes to the
    #: longest-standing remaining member if the host leaves.
    host_member_id: str
    members: dict[str, Member] = field(default_factory=dict)
    #: A locked room refuses new joiners; current members are
    #: unaffected.
    locked: bool = False
    #: Goes up by one on every change anyone in the room could see,
    #: so a browser can tell "the room changed" from this number alone
    #: (Phase 2's live updates).
    version: int = 0
    players: dict[str, Player] = field(default_factory=dict)
    attempts: list[Attempt] = field(default_factory=list)
    created_at: float = field(default_factory=time.monotonic)
    last_activity: float = field(default_factory=time.monotonic)
    #: A random id, never derived from `id` -- score_attempts.party_id
    #: (docs/plans/done/PARTY_LAUNCH_PLAN.md section 10). Same "rides this object's own
    #: lifetime, no separate mapping to discard" reasoning as
    #: Player.score_id above.
    score_id: str = field(default_factory=lambda: str(uuid.uuid4()))


class PartyLimitReached(Exception):
    """Raised by create_party when the store is at capacity and no
    party is expired -- see the module docstring on why that's a hard
    stop, not an eviction of someone's still-active game."""


class PartyFullError(Exception):
    """Raised by add_player when a party already has
    players_per_party_limit players."""


class RoomNotFoundError(Exception):
    """Raised by join_party for a code that names no live room --
    never distinguishes "never existed" from "ended" or "expired"."""


class RoomLockedError(Exception):
    """Raised by join_party when the host has locked the room."""


class RoomMembersFullError(Exception):
    """Raised by join_party when a room already has
    members_per_party_limit member browsers."""


@dataclass(frozen=True)
class MemberRemoval:
    """What remove_member took out with the member -- the caller
    needs the players' score_ids, and whether that was the last
    member (the room is gone too), to delete their stored scores."""

    players: list[Player]
    room_ended: bool


class RoomListener(Protocol):
    """Told about every room change as it happens, so live updates
    (game/events.py) can't miss one. Called with the store's lock
    held, from whichever thread made the change: implementations must
    return quickly and must never call back into the store."""

    def room_changed(self, party_id: str, version: int) -> None: ...
    def room_ended(self, party_id: str) -> None: ...
    def member_removed(self, party_id: str, member_id: str) -> None: ...


class GameStore(Protocol):
    def create_party(self, level: Level) -> Party: ...
    def get_party(self, party_id: str) -> Party | None: ...
    def touch(self, party_id: str) -> None: ...
    def delete_party(self, party_id: str) -> None: ...
    def join_party(self, code: str) -> tuple[Party, Member]: ...
    def remove_member(self, party_id: str, member_id: str) -> MemberRemoval | None: ...
    def mark_member_seen(self, party_id: str, member_id: str) -> None: ...
    def set_locked(self, party_id: str, locked: bool) -> bool: ...
    def add_player(self, party_id: str, player: Player) -> None: ...
    def rename_player(self, party_id: str, player_id: str, new_name: str) -> bool: ...
    def delete_player(self, party_id: str, player_id: str) -> bool: ...
    def add_attempt(self, party_id: str, attempt: Attempt) -> bool: ...
    def sweep_expired(self) -> int: ...


class InMemoryGameStore:
    def __init__(
        self,
        *,
        party_limit: int,
        players_per_party_limit: int,
        attempts_per_party_limit: int,
        idle_expiry_seconds: float,
        members_per_party_limit: int = 12,
        listener: RoomListener | None = None,
    ) -> None:
        self._listener = listener
        self._members_per_party_limit = members_per_party_limit
        self._party_limit = party_limit
        self._players_per_party_limit = players_per_party_limit
        self._attempts_per_party_limit = attempts_per_party_limit
        self._idle_expiry_seconds = idle_expiry_seconds
        self._lock = threading.Lock()
        self._parties: dict[str, Party] = {}

    def _is_expired(self, party: Party, now: float) -> bool:
        return now - party.last_activity > self._idle_expiry_seconds

    def _changed(self, party: Party) -> None:
        """The one place a room's version moves, so the listener hears
        about every change. Caller holds the lock."""
        party.version += 1
        if self._listener is not None:
            self._listener.room_changed(party.id, party.version)

    def _drop(self, party_id: str) -> None:
        """The one place a room leaves the store -- ended, emptied, or
        expired. Caller holds the lock."""
        if self._parties.pop(party_id, None) is not None and self._listener is not None:
            self._listener.room_ended(party_id)

    def sweep_expired(self) -> int:
        """Removes every expired party. Returns how many were removed
        -- callers (create_party, and the periodic sweep a load test
        can trigger) use this to decide whether capacity opened up."""
        now = time.monotonic()
        with self._lock:
            expired = [pid for pid, party in self._parties.items() if self._is_expired(party, now)]
            for pid in expired:
                self._drop(pid)
            return len(expired)

    def create_party(self, level: Level) -> Party:
        self.sweep_expired()
        with self._lock:
            if len(self._parties) >= self._party_limit:
                # Deliberately does not evict a party that hasn't
                # expired, even to make room -- sweep_expired() just
                # ran and already removed anything that qualified.
                # Evicting someone's still-active game to fit a new
                # one would silently erase real play; a clear "try
                # again soon" is the honest answer instead.
                raise PartyLimitReached(
                    f"{self._party_limit} parties are already active. Try again soon."
                )
            # 500 rooms at most, so a scan for a clash is cheap and
            # keeps one source of truth -- no second code->room index
            # to fall out of step with _parties.
            live_codes = {p.code for p in self._parties.values()}
            code = generate_code()
            while code in live_codes:
                code = generate_code()
            host = Member(id=str(uuid.uuid4()))
            party = Party(
                id=str(uuid.uuid4()),
                level=level,
                code=code,
                members={host.id: host},
                host_member_id=host.id,
            )
            self._parties[party.id] = party
            return party

    def join_party(self, code: str) -> tuple[Party, Member]:
        """Adds a new member to the live room with this (already
        normalized) code. Lookup and add happen under one lock, so a
        room can't fill, lock, or end between the two."""
        now = time.monotonic()
        with self._lock:
            party = next((p for p in self._parties.values() if p.code == code), None)
            if party is not None and self._is_expired(party, now):
                self._drop(party.id)
                party = None
            if party is None:
                raise RoomNotFoundError
            if party.locked:
                raise RoomLockedError("This room is locked. Ask the host to unlock it.")
            if len(party.members) >= self._members_per_party_limit:
                raise RoomMembersFullError(
                    f"This room is full: {self._members_per_party_limit} browsers have joined."
                )
            member = Member(id=str(uuid.uuid4()))
            party.members[member.id] = member
            self._changed(party)
            party.last_activity = now
            return party, member

    def remove_member(self, party_id: str, member_id: str) -> MemberRemoval | None:
        """Takes a member out, along with the players they enrolled
        and every attempt involving those players -- nobody else could
        type as or manage them once their owner is gone. The last
        member leaving ends the room. None when there was no such
        room or member."""
        with self._lock:
            party = self._parties.get(party_id)
            if party is None or member_id not in party.members:
                return None
            del party.members[member_id]
            removed = [p for p in party.players.values() if p.owner_member_id == member_id]
            removed_ids = {p.id for p in removed}
            for player_id in removed_ids:
                del party.players[player_id]
            party.attempts = [
                a
                for a in party.attempts
                if a.typist_id not in removed_ids and a.target_id not in removed_ids
            ]
            if self._listener is not None:
                self._listener.member_removed(party_id, member_id)
            if not party.members:
                self._drop(party_id)
                return MemberRemoval(players=removed, room_ended=True)
            if party.host_member_id == member_id:
                party.host_member_id = min(party.members.values(), key=lambda m: m.created_at).id
            self._changed(party)
            party.last_activity = time.monotonic()
            return MemberRemoval(players=removed, room_ended=False)

    def mark_member_seen(self, party_id: str, member_id: str) -> None:
        """Records that this member's browser just made a request.
        Deliberately not a room change: it moves neither `version` nor
        the idle clock, so merely watching a room (Phase 2's polling)
        can't keep it alive forever."""
        with self._lock:
            party = self._parties.get(party_id)
            if party is not None and member_id in party.members:
                party.members[member_id].last_seen = time.monotonic()

    def set_locked(self, party_id: str, locked: bool) -> bool:
        with self._lock:
            party = self._parties.get(party_id)
            if party is None:
                return False
            if party.locked != locked:
                party.locked = locked
                self._changed(party)
            party.last_activity = time.monotonic()
            return True

    def get_party(self, party_id: str) -> Party | None:
        with self._lock:
            party = self._parties.get(party_id)
            if party is None:
                return None
            if self._is_expired(party, time.monotonic()):
                self._drop(party_id)
                return None
            return party

    def touch(self, party_id: str) -> None:
        with self._lock:
            party = self._parties.get(party_id)
            if party is not None:
                party.last_activity = time.monotonic()

    def delete_party(self, party_id: str) -> None:
        with self._lock:
            self._drop(party_id)

    def add_player(self, party_id: str, player: Player) -> None:
        with self._lock:
            party = self._parties.get(party_id)
            if party is None:
                return
            if len(party.players) >= self._players_per_party_limit:
                raise PartyFullError(
                    f"This party already has {self._players_per_party_limit} players."
                )
            party.players[player.id] = player
            self._changed(party)
            party.last_activity = time.monotonic()

    def rename_player(self, party_id: str, player_id: str, new_name: str) -> bool:
        with self._lock:
            party = self._parties.get(party_id)
            if party is None or player_id not in party.players:
                return False
            existing = party.players[player_id]
            party.players[player_id] = Player(
                id=existing.id,
                name=new_name,
                color=existing.color,
                profile=existing.profile,
                threshold=existing.threshold,
                notes=existing.notes,
                created_at=existing.created_at,
                # A rename must never mint a new score_id -- it's
                # set once, at enrollment.
                score_id=existing.score_id,
                training_line_count=existing.training_line_count,
                owner_member_id=existing.owner_member_id,
            )
            self._changed(party)
            party.last_activity = time.monotonic()
            return True

    def delete_player(self, party_id: str, player_id: str) -> bool:
        with self._lock:
            party = self._parties.get(party_id)
            if party is None or player_id not in party.players:
                return False
            del party.players[player_id]
            # That player's own attempts no longer point at anyone
            # meaningful to keep around either.
            party.attempts = [
                a for a in party.attempts if a.typist_id != player_id and a.target_id != player_id
            ]
            self._changed(party)
            party.last_activity = time.monotonic()
            return True

    def add_attempt(self, party_id: str, attempt: Attempt) -> bool:
        with self._lock:
            party = self._parties.get(party_id)
            if party is None:
                return False
            party.attempts.append(attempt)
            if len(party.attempts) > self._attempts_per_party_limit:
                party.attempts = party.attempts[-self._attempts_per_party_limit :]
            self._changed(party)
            party.last_activity = time.monotonic()
            return True

    def party_count(self) -> int:
        with self._lock:
            return len(self._parties)
