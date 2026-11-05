"""Shared FastAPI dependencies for the account system: the current
authenticated user, plus re-exports of the DB-independent security
helpers (api/security.py) that auth.py/profile.py already import from
here."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from keystroke_dynamics.api.rate_limit import RateLimiter
from keystroke_dynamics.api.security import rate_limited, require_matching_origin
from keystroke_dynamics.config import settings
from keystroke_dynamics.db.models import User
from keystroke_dynamics.db.session import get_db

__all__ = [
    "get_current_user",
    "login_rate_limiter",
    "rate_limited",
    "register_rate_limiter",
    "require_matching_origin",
    "verify_rate_limiter",
]

# One limiter per sensitive endpoint, each with its own counters, so
# a flood of login attempts doesn't eat into the registration or
# verification budget for the same client. Keyed by client IP.
_MAX_ATTEMPTS = settings.rate_limit_max_attempts
_WINDOW_SECONDS = settings.rate_limit_window_seconds
login_rate_limiter = RateLimiter(_MAX_ATTEMPTS, _WINDOW_SECONDS)
register_rate_limiter = RateLimiter(_MAX_ATTEMPTS, _WINDOW_SECONDS)
verify_rate_limiter = RateLimiter(_MAX_ATTEMPTS, _WINDOW_SECONDS)


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
