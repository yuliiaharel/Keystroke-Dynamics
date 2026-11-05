"""POST /api/register, /api/login, /api/logout."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from keystroke_dynamics.api.deps import (
    login_rate_limiter,
    rate_limited,
    register_rate_limiter,
    require_matching_origin,
)
from keystroke_dynamics.api.passwords import hash_password, verify_password_or_dummy
from keystroke_dynamics.api.schemas import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    TypingResultSchema,
)
from keystroke_dynamics.config import settings
from keystroke_dynamics.core.events import InvalidSampleError, pair_presses, validate
from keystroke_dynamics.core.features import extract_features
from keystroke_dynamics.core.scoring import scaled_manhattan_score
from keystroke_dynamics.db.repository import create_user, get_profile_features, get_user_by_username
from keystroke_dynamics.db.session import get_db

router = APIRouter(prefix="/api", dependencies=[Depends(require_matching_origin)])


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limited(register_rate_limiter))],
)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    if get_user_by_username(db, body.username) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "username already exists")
    try:
        create_user(db, body.username, hash_password(body.password))
    except IntegrityError:
        # The check above and this insert aren't atomic -- two
        # concurrent registrations for the same new username can both
        # pass the check, and the second loses to the unique
        # constraint here. Same outcome as the check catching it:
        # a 409, not an unhandled 500.
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "username already exists") from None
    return {"status": "created"}


@router.post("/login", dependencies=[Depends(rate_limited(login_rate_limiter))])
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> LoginResponse:
    user = get_user_by_username(db, body.username)
    password_hash = user.password_hash if user is not None else None
    if not verify_password_or_dummy(password_hash, body.password):
        # Identical response whether the username doesn't exist or the
        # password is simply wrong -- never reveal which.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid username or password")
    assert user is not None  # verify_password_or_dummy is only True for a user's own real hash

    request.session["user_id"] = user.id

    if not body.sample:
        return LoginResponse(typing_result=None)

    # A failed or unscoreable typing check never fails the login or
    # reveals anything about the password -- it's purely a signal
    # returned alongside an already-successful login.
    events = [e.to_core() for e in body.sample]
    try:
        validate(events, max_events=settings.max_events)
    except InvalidSampleError:
        return LoginResponse(typing_result=None)

    features = extract_features(pair_presses(events))
    profile = get_profile_features(db, user.id)
    result = scaled_manhattan_score(features, profile)
    return LoginResponse(typing_result=TypingResultSchema.from_core(result))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request) -> None:
    request.session.clear()
