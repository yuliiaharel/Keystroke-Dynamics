"""The score_attempts table: docs/plans/done/PARTY_LAUNCH_PLAN.md section 10's one
append-only table, on its own database (settings.scores_database_url),
written only by the background writer (scores/writer.py). This
module's Base is deliberately separate from db/models.py's -- a
completely different database, with its own migrations
(migrations_scores/) and its own restricted database role that may
only INSERT and DELETE rows here, nothing else.

The column set is exhaustive and intentionally not open to
extension -- see tests/scores/test_models.py's test that fails if a
column outside docs/plans/done/PARTY_LAUNCH_PLAN.md's own list (plus
same_keyboard, from docs/plans/active/ROOMS_PLAN.md, and screen_size,
from docs/plans/active/MOBILE_PLAN.md) is added. In
particular, there is no name, IP address, user agent, key timing, key
identity, or profile-statistics column, and party_id/typist_id/
target_id are random ids created only for this table (game/store.py's
Player.score_id/Party.score_id, or scores/target_ids.py for the
sample bots and the permanent target) -- never derived from, or
stored with, a session, cookie, name, or game id.
"""

from __future__ import annotations

import datetime

from sqlalchemy import Boolean, CheckConstraint, Date, Float, Integer, String, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ScoreAttempt(Base):
    __tablename__ = "score_attempts"
    __table_args__ = (
        CheckConstraint("device_type IN ('keyboard', 'touch')", name="ck_device_type"),
        CheckConstraint("line_id IN ('word', 'sentence', 'long', 'touch')", name="ck_line_id"),
        CheckConstraint("mode IN ('attack', 'self', 'disguise', 'replay', 'grip')", name="ck_mode"),
        CheckConstraint(
            "target_kind IN ('player', 'simulated', 'permanent')", name="ck_target_kind"
        ),
        CheckConstraint("outcome IN ('pass', 'fail', 'unusable')", name="ck_outcome"),
        CheckConstraint(
            "screen_size IN ('small', 'medium', 'large', 'xlarge')", name="ck_screen_size"
        ),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    #: Date only, no time -- see docs/plans/done/PARTY_LAUNCH_PLAN.md section 10's
    #: table definition. Never a timestamp: a time-of-day would be one
    #: more thing that, combined with other signals, narrows down who
    #: this row could be. Indexed: the daily retention task
    #: (scores/retention.py) deletes by this column.
    created_on: Mapped[datetime.date] = mapped_column(Date, index=True)
    #: Set in code (SCORING_VERSION below) and changed whenever
    #: scoring or game settings change.
    scoring_version: Mapped[str] = mapped_column(String)
    #: Which wording of the score-saving notice was current when this
    #: row was written (scores/recording.py's NOTICE_VERSION). The
    #: name dates from the opt-in checkbox: "1" rows are from players
    #: who ticked it, later versions are saved automatically.
    consent_version: Mapped[str] = mapped_column(String)
    device_type: Mapped[str] = mapped_column(String)
    line_id: Mapped[str] = mapped_column(String)
    mode: Mapped[str] = mapped_column(String)
    target_kind: Mapped[str] = mapped_column(String)
    party_id: Mapped[str] = mapped_column(Uuid(as_uuid=False))
    typist_id: Mapped[str] = mapped_column(Uuid(as_uuid=False))
    target_id: Mapped[str] = mapped_column(Uuid(as_uuid=False))
    training_lines: Mapped[int] = mapped_column(Integer)
    compared_features: Mapped[int] = mapped_column(Integer)
    #: Nullable exactly when the attempt was unusable (INSUFFICIENT_DATA
    #: -- too messy to score at all). A keyboard row's rhythm and
    #: total hold the same value and its place is null. A touch row's
    #: rhythm is its timing-only score, place its tap-position-only
    #: score, and total the distance over both.
    rhythm: Mapped[float | None] = mapped_column(Float)
    place: Mapped[float | None] = mapped_column(Float)
    total: Mapped[float | None] = mapped_column(Float)
    limit_value: Mapped[float] = mapped_column(Float)
    #: Nullable only in the (shouldn't-normally-happen) case where the
    #: target has no notes to compare against -- see
    #: game/judge.py:pace_ratio().
    pace: Mapped[float | None] = mapped_column(Float)
    outcome: Mapped[str] = mapped_column(String)
    #: Whether the typist and the target were on the same keyboard
    #: (the same room member) -- docs/plans/active/ROOMS_PLAN.md Phase 1
    #: section 5, since a different keyboard can change timing. Null
    #: for rows from before rooms, for bot and permanent targets, and
    #: for replays.
    same_keyboard: Mapped[bool | None] = mapped_column(Boolean)
    #: Roughly how wide the typist's screen was, as one of four
    #: buckets by viewport width (game/screen.py) -- never the width
    #: itself. Touch rows only (docs/plans/active/MOBILE_PLAN.md
    #: Phase 1 section 6), because key size can change where taps
    #: land. Null for every keyboard row, for replays, and when the
    #: browser didn't report a width.
    screen_size: Mapped[str | None] = mapped_column(String)
