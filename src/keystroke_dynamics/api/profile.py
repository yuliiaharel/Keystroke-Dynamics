"""POST /api/profile/samples, POST /api/profile/verify,
DELETE /api/profile. All require an active session."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from keystroke_dynamics.api.deps import (
    get_current_user,
    rate_limited,
    require_matching_origin,
    verify_rate_limiter,
)
from keystroke_dynamics.api.schemas import (
    SampleRequest,
    SamplesResponse,
    TypingResultSchema,
    VerifyRequest,
)
from keystroke_dynamics.config import settings
from keystroke_dynamics.core.events import InvalidSampleError, pair_presses, validate
from keystroke_dynamics.core.features import extract_features
from keystroke_dynamics.core.scoring import scaled_manhattan_score
from keystroke_dynamics.db.models import User
from keystroke_dynamics.db.repository import (
    delete_profile,
    get_profile_features,
    save_sample_features,
)
from keystroke_dynamics.db.session import get_db

router = APIRouter(prefix="/api/profile", dependencies=[Depends(require_matching_origin)])


@router.post("/samples")
def add_sample(
    body: SampleRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SamplesResponse:
    events = [e.to_core() for e in body.events]
    try:
        validate(events, max_events=settings.max_events)
    except InvalidSampleError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    features = extract_features(pair_presses(events))
    sample_count = save_sample_features(db, user.id, features)
    return SamplesResponse(sample_count=sample_count)


@router.post("/verify", dependencies=[Depends(rate_limited(verify_rate_limiter))])
def verify(
    body: VerifyRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TypingResultSchema:
    events = [e.to_core() for e in body.events]
    try:
        validate(events, max_events=settings.max_events)
    except InvalidSampleError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    features = extract_features(pair_presses(events))
    profile = get_profile_features(db, user.id)
    result = scaled_manhattan_score(features, profile)
    return TypingResultSchema.from_core(result)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_profile(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    delete_profile(db, user.id)
