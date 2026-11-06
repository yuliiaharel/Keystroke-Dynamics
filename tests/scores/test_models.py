"""score_attempts' column set is exhaustive, per PARTY_LAUNCH_PLAN.md
section 10: this fails loudly if a column outside the plan's own list
is ever added, rather than silently letting one more field in
(name, IP address, user agent, key timing, key identity, profile
statistics -- all explicitly forbidden)."""

from __future__ import annotations

import datetime
import uuid

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from keystroke_dynamics.scores.models import ScoreAttempt

#: Exactly PARTY_LAUNCH_PLAN.md section 10's table definition -- add a
#: column here (with a one-line note of which plan line it's from)
#: only alongside an actual plan update, never just to make this pass.
_ALLOWED_COLUMNS = {
    "id",
    "created_on",
    "scoring_version",
    "consent_version",
    "device_type",
    "line_id",
    "mode",
    "target_kind",
    "party_id",
    "typist_id",
    "target_id",
    "training_lines",
    "compared_features",
    "rhythm",
    "place",
    "total",
    "limit_value",
    "pace",
    "outcome",
}


def test_score_attempts_has_exactly_the_allowed_columns() -> None:
    actual = {c.name for c in ScoreAttempt.__table__.columns}
    assert actual == _ALLOWED_COLUMNS


def _row(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "created_on": datetime.date(2026, 1, 1),
        "scoring_version": "1",
        "consent_version": "1",
        "device_type": "keyboard",
        "line_id": "word",
        "mode": "attack",
        "target_kind": "player",
        "party_id": str(uuid.uuid4()),
        "typist_id": str(uuid.uuid4()),
        "target_id": str(uuid.uuid4()),
        "training_lines": 5,
        "compared_features": 11,
        "rhythm": 0.8,
        "place": None,
        "total": 0.8,
        "limit_value": 1.5,
        "pace": 1.02,
        "outcome": "pass",
    }
    defaults.update(overrides)
    return defaults


def test_a_full_row_round_trips(scores_db_session) -> None:
    row = _row()
    scores_db_session.execute(insert(ScoreAttempt), [row])
    scores_db_session.commit()

    stored = scores_db_session.execute(
        select(ScoreAttempt).where(ScoreAttempt.id == row["id"])
    ).scalar_one()
    assert stored.device_type == "keyboard"
    assert stored.place is None
    assert stored.total == 0.8


def test_an_unusable_row_with_null_scores_round_trips(scores_db_session) -> None:
    row = _row(rhythm=None, place=None, total=None, outcome="unusable", compared_features=3)
    scores_db_session.execute(insert(ScoreAttempt), [row])
    scores_db_session.commit()

    stored = scores_db_session.execute(
        select(ScoreAttempt).where(ScoreAttempt.id == row["id"])
    ).scalar_one()
    assert stored.rhythm is None
    assert stored.outcome == "unusable"


def test_device_type_check_constraint_rejects_an_unknown_value(scores_db_session) -> None:
    row = _row(device_type="mouse")
    # A Core insert (not an ORM session.add()) executes against the
    # database immediately, not deferred to commit -- the constraint
    # violation happens right here.
    with pytest.raises(IntegrityError):
        scores_db_session.execute(insert(ScoreAttempt), [row])
    scores_db_session.rollback()


def test_outcome_check_constraint_rejects_an_unknown_value(scores_db_session) -> None:
    row = _row(outcome="maybe")
    with pytest.raises(IntegrityError):
        scores_db_session.execute(insert(ScoreAttempt), [row])
    scores_db_session.rollback()
