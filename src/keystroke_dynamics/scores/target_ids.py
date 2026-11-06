"""A stable, random score_id for the sample bots and the permanent
target -- the two kinds of game target that aren't party-scoped
Player objects, so they have no Player.score_id of their own to ride
(see game/store.py's Player.score_id docstring for the party-scoped
case).

game/targets.py's sample_targets() is itself process-lifetime-cached
(functools.cache), so the Player objects it returns -- and the
score_id their own dataclass default assigns -- are already stable
for the life of the process without anything here. load_permanent_target()
is deliberately NOT cached that way (tests reload it from a fresh file
on each call), so its returned Player would otherwise get a *new*
random score_id every call -- useless for score_attempts, where the
same permanent target must keep one consistent target_id across every
row ever written in this process. This module is that one exception's
fix, not a general mechanism either of them needs.
"""

from __future__ import annotations

import threading
import uuid

_lock = threading.Lock()
_score_ids: dict[str, str] = {}


def score_id_for_target(real_id: str) -> str:
    """A random id that stays the same for this real_id for the rest
    of the process's life, and is never derived from it (per
    PARTY_LAUNCH_PLAN.md section 10's "must not be derived from ... a
    game ID") -- only looked up by it, in memory, never persisted
    anywhere alongside real_id itself. Forgotten on restart, same as
    every other in-memory game state.
    """
    with _lock:
        if real_id not in _score_ids:
            _score_ids[real_id] = str(uuid.uuid4())
        return _score_ids[real_id]
