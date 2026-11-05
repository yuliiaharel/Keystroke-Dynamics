"""Request-level security helpers with no database dependency, so the
anonymous game module (which must work with no DATABASE_URL at all --
see config.py's enable_accounts) can use the same Origin check and
rate-limiting machinery the account system uses, without importing
anything from db/.

api/deps.py re-exports require_matching_origin and rate_limited for
backward compatibility with auth.py/profile.py, which import them
from there.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException, Request, status

from keystroke_dynamics.api.rate_limit import RateLimiter
from keystroke_dynamics.config import settings


def require_matching_origin(request: Request) -> None:
    """CSRF defense for all state-changing requests: the Origin header
    must match this app's own configured origin exactly. The app sets
    no CORS headers and serves no other origin, so a missing or
    mismatched Origin always means either a cross-site request or a
    non-browser client that isn't sending one -- reject both.
    """
    origin = request.headers.get("origin")
    if origin != settings.allowed_origin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "origin mismatch")


def rate_limited(limiter: RateLimiter) -> Callable[[Request], None]:
    def dependency(request: Request) -> None:
        key = client_ip(request)
        if not limiter.allow(key):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate limit exceeded")

    return dependency


def client_ip(request: Request) -> str:
    """The key rate limiting buckets by. Deliberately just the ASGI
    connection's own peer address, never a client-supplied header
    (X-Forwarded-For and friends are trivial to spoof) -- see Part 2 of
    PARTY_LAUNCH_PLAN.md for how this is expected to interact with
    DigitalOcean's proxy, which isn't configured yet."""
    return request.client.host if request.client else "unknown"
