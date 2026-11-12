"""In-memory, per-process rate limiting.

Documented limitation (per docs/plans/done/MODERNIZATION_PLAN.md Phase 4): state lives
in this one process's memory. It resets on restart, and running more
than one process (multiple workers, multiple containers) gives each
its own independent counters rather than a shared one -- so the real
limit under N processes is N times what's configured here. Fine for a
single instance; not a substitute for a shared store (Redis, the
database) if this ever needs to scale out.
"""

from __future__ import annotations

import threading
import time


class RateLimiter:
    def __init__(self, max_attempts: int, window_seconds: float) -> None:
        self.max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._lock = threading.Lock()
        self._attempts: dict[str, list[float]] = {}

    def reset(self) -> None:
        """Clears all recorded attempts. Not used by the app itself --
        only by tests, so one test's calls to a rate-limited endpoint
        don't eat into another's budget."""
        with self._lock:
            self._attempts.clear()

    def allow(self, key: str) -> bool:
        """Records one attempt for key and reports whether it's
        within the limit. Always records, even when denied, so a
        caller that keeps retrying doesn't get a free pass once the
        window rolls over mid-flood.
        """
        now = time.monotonic()
        cutoff = now - self._window_seconds

        with self._lock:
            attempts = [t for t in self._attempts.get(key, []) if t > cutoff]
            attempts.append(now)
            self._attempts[key] = attempts
            return len(attempts) <= self.max_attempts
