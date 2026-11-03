"""Shared FastAPI dependencies: the current authenticated user,
same-origin enforcement, and rate limiting."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from keystroke_dynamics.api.rate_limit import RateLimiter
from keystroke_dynamics.config import settings
from keystroke_dynamics.db.models import User
from keystroke_dynamics.db.session import get_db

# One limiter per sensitive endpoint, each with its own counters, so
# a flood of login attempts doesn't eat into the registration or
# verification budget for the same client. Keyed by client IP.
_MAX_ATTEMPTS = settings.rate_limit_max_attempts
_WINDOW_SECONDS = settings.rate_limit_window_seconds
login_rate_limiter = RateLimiter(_MAX_ATTEMPTS, _WINDOW_SECONDS)
register_rate_limiter = RateLimiter(_MAX_ATTEMPTS, _WINDOW_SECONDS)
verify_rate_limiter = RateLimiter(_MAX_ATTEMPTS, _WINDOW_SECONDS)


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


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """The user is derived only from the session, never from a header
    or request body -- a client can't claim to be someone else just
    by setting a field.
    """
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    user = db.get(User, user_id)
    if user is None:
        # The session names a user that no longer exists (e.g. the
        # account was deleted). Treat it the same as never logging in.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    return user


def rate_limited(limiter: RateLimiter) -> Callable[[Request], None]:
    def dependency(request: Request) -> None:
        key = request.client.host if request.client else "unknown"
        if not limiter.allow(key):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate limit exceeded")

    return dependency
