"""SQLAlchemy models, per MODERNIZATION_PLAN.md Phase 4's schema."""

from __future__ import annotations

import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(unique=True, index=True)
    password_hash: Mapped[str]
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    profile: Mapped[TypingProfile | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )


class TypingProfile(Base):
    __tablename__ = "typing_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    sample_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="profile")
    features: Mapped[list[ProfileFeature]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class ProfileFeature(Base):
    """One row per (kind, key_a, key_b) feature in a profile, storing
    its RunningStats (count, mean, m2) -- see core.stats.

    key_b is an empty string rather than NULL for hold features (which
    have no second key), per the plan's instruction: NULL would make
    the unique constraint ineffective, since SQL NULLs are never equal
    to each other, so two "duplicate" hold rows with key_b=NULL
    wouldn't violate the constraint at all.
    """

    __tablename__ = "profile_features"
    __table_args__ = (UniqueConstraint("profile_id", "kind", "key_a", "key_b"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("typing_profiles.id"))
    kind: Mapped[str]  # "hold" | "flight"
    key_a: Mapped[str]
    key_b: Mapped[str] = mapped_column(default="")
    count: Mapped[int]
    mean: Mapped[float]
    m2: Mapped[float]

    profile: Mapped[TypingProfile] = relationship(back_populates="features")
