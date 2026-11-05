"""The anonymous game's own rate limiter -- separate from the account
system's (api/deps.py) because it guards a different set of routes
with a different abuse shape, sized from its own settings
(game_rate_limit_max_attempts/game_rate_limit_window_seconds). Same
in-memory, per-process mechanism and limitation (api/rate_limit.py).
"""

from __future__ import annotations

from keystroke_dynamics.api.rate_limit import RateLimiter
from keystroke_dynamics.config import settings

game_rate_limiter = RateLimiter(
    settings.game_rate_limit_max_attempts, settings.game_rate_limit_window_seconds
)
