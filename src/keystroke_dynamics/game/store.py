"""In-memory game state: parties, players, attempts.

One process, one worker, no database -- see main.py's docstring for
why single-worker is deliberate. A `threading.Lock` guards every
mutation anyway, since FastAPI still dispatches sync routes to a
threadpool (multiple requests really do run concurrently within this
one process).

Deliberately behind a narrow Protocol (GameStore) so a later, real
multi-worker "online rooms" backend (out of scope for this launch --
see PARTY_LAUNCH_PLAN.md) can be swapped in without changing
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
from keystroke_dynamics.game.levels import Level

Mode = Literal["attack", "self", "disguise", "replay"]


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
    #: A random id, never derived from `id` -- PARTY_LAUNCH_PLAN.md
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
    #: Opted in to PARTY_LAUNCH_PLAN.md section 10's score sharing at
    #: enrollment time. Never pre-checked, never a condition of
    #: playing, and never changeable later in this launch's scope.
    shares_scores: bool = False
    #: The consent wording version this player agreed to, captured
    #: once at the moment they opted in -- not whatever the current
    #: code constant is when a later attempt gets recorded, which
    #: could be a different wording if it changed in between. None
    #: when shares_scores is False.
    consent_version: str | None = None
    #: How many training lines went into this player's profile --
    #: score_attempts.training_lines. Captured once at enrollment,
    #: since the raw lines themselves are never kept past it.
    training_line_count: int = 0


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


#: Attempt.typist_id for a server-run replay (game/replay.py) -- never
#: a real player, but distinct from Guest (None) in attempt history.
REPLAY_TYPIST_ID = "replay"


@dataclass
class Party:
    id: str
    level: Level
    players: dict[str, Player] = field(default_factory=dict)
    attempts: list[Attempt] = field(default_factory=list)
    created_at: float = field(default_factory=time.monotonic)
    last_activity: float = field(default_factory=time.monotonic)
    #: A random id, never derived from `id` -- score_attempts.party_id
    #: (PARTY_LAUNCH_PLAN.md section 10). Same "rides this object's own
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


class GameStore(Protocol):
    def create_party(self, level: Level) -> Party: ...
    def get_party(self, party_id: str) -> Party | None: ...
    def touch(self, party_id: str) -> None: ...
    def delete_party(self, party_id: str) -> None: ...
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
    ) -> None:
        self._party_limit = party_limit
        self._players_per_party_limit = players_per_party_limit
        self._attempts_per_party_limit = attempts_per_party_limit
        self._idle_expiry_seconds = idle_expiry_seconds
        self._lock = threading.Lock()
        self._parties: dict[str, Party] = {}

    def _is_expired(self, party: Party, now: float) -> bool:
        return now - party.last_activity > self._idle_expiry_seconds

    def sweep_expired(self) -> int:
        """Removes every expired party. Returns how many were removed
        -- callers (create_party, and the periodic sweep a load test
        can trigger) use this to decide whether capacity opened up."""
        now = time.monotonic()
        with self._lock:
            expired = [pid for pid, party in self._parties.items() if self._is_expired(party, now)]
            for pid in expired:
                del self._parties[pid]
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
            party = Party(id=str(uuid.uuid4()), level=level)
            self._parties[party.id] = party
            return party

    def get_party(self, party_id: str) -> Party | None:
        with self._lock:
            party = self._parties.get(party_id)
            if party is None:
                return None
            if self._is_expired(party, time.monotonic()):
                del self._parties[party_id]
                return None
            return party

    def touch(self, party_id: str) -> None:
        with self._lock:
            party = self._parties.get(party_id)
            if party is not None:
                party.last_activity = time.monotonic()

    def delete_party(self, party_id: str) -> None:
        with self._lock:
            self._parties.pop(party_id, None)

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
                # A rename must never mint a new score_id or touch
                # consent -- both are set once, at enrollment.
                score_id=existing.score_id,
                shares_scores=existing.shares_scores,
                consent_version=existing.consent_version,
                training_line_count=existing.training_line_count,
            )
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
            party.last_activity = time.monotonic()
            return True

    def party_count(self) -> int:
        with self._lock:
            return len(self._parties)
