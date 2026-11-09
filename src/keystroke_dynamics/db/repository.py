"""Pure database operations. No HTTP/session concerns here -- those
belong in api/.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from keystroke_dynamics.core.features import Feature, FeatureKey
from keystroke_dynamics.core.stats import RunningStats, update
from keystroke_dynamics.db.models import ProfileFeature, TypingProfile, User


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username))


def create_user(db: Session, username: str, password_hash: str) -> User:
    user = User(username=username, password_hash=password_hash)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_profile_features(db: Session, user_id: int) -> dict[FeatureKey, RunningStats]:
    profile = db.scalar(select(TypingProfile).where(TypingProfile.user_id == user_id))
    if profile is None:
        return {}
    return {
        _to_feature_key(row): RunningStats(count=row.count, mean=row.mean, m2=row.m2)
        for row in profile.features
    }


def save_sample_features(db: Session, user_id: int, features: list[Feature]) -> int:
    """Merges one sample's features into the user's profile (creating
    the profile if this is their first sample) and returns its new
    sample_count.

    Locks the profile row for the rest of the transaction
    (SELECT ... FOR UPDATE), so two concurrent uploads for the same
    user serialize instead of one silently losing the other's update
    -- see the "concurrent sample uploads keep the correct count"
    test.

    A brand-new profile has its own race: two concurrent *first*
    uploads for the same user could both see no profile row to lock
    and both try to create one, and the second to flush loses to the
    unique constraint on user_id. Caught below: roll back and re-fetch
    with the lock, which now succeeds against the row the other
    request just committed.
    """
    profile = db.scalar(
        select(TypingProfile).where(TypingProfile.user_id == user_id).with_for_update()
    )
    if profile is None:
        profile = TypingProfile(user_id=user_id, sample_count=0)
        db.add(profile)
        try:
            db.flush()  # assigns profile.id, needed below
        except IntegrityError:
            db.rollback()
            profile = db.scalar(
                select(TypingProfile).where(TypingProfile.user_id == user_id).with_for_update()
            )
            assert profile is not None  # the losing race always means it exists now

    existing_by_key = {_to_feature_key(row): row for row in profile.features}

    for feature in features:
        row = existing_by_key.get(feature.key)
        if row is None:
            stats = update(RunningStats(), feature.value_ms)
            kind, key_a, key_b = _from_feature_key(feature.key)
            row = ProfileFeature(
                profile_id=profile.id,
                kind=kind,
                key_a=key_a,
                key_b=key_b,
                count=stats.count,
                mean=stats.mean,
                m2=stats.m2,
            )
            db.add(row)
            existing_by_key[feature.key] = row
        else:
            prior = RunningStats(count=row.count, mean=row.mean, m2=row.m2)
            stats = update(prior, feature.value_ms)
            row.count, row.mean, row.m2 = stats.count, stats.mean, stats.m2

    profile.sample_count += 1
    # Read the count while the row lock is still held. Reading it back
    # after the commit can return a later upload's count instead, since
    # the commit releases the lock.
    sample_count = profile.sample_count
    db.commit()
    return sample_count


def delete_profile(db: Session, user_id: int) -> bool:
    """Returns True if a profile existed and was deleted, False if the
    user had none."""
    profile = db.scalar(select(TypingProfile).where(TypingProfile.user_id == user_id))
    if profile is None:
        return False
    db.delete(profile)
    db.commit()
    return True


def _to_feature_key(row: ProfileFeature) -> FeatureKey:
    if row.kind == "hold":
        return ("hold", row.key_a)
    return ("flight", row.key_a, row.key_b)


def _from_feature_key(key: FeatureKey) -> tuple[str, str, str]:
    if key[0] == "hold":
        return "hold", key[1], ""
    return "flight", key[1], key[2]
