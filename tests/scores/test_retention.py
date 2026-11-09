"""scores/retention.py: delete_expired_rows() against the real scores
test database (date-based filtering isn't meaningfully fakeable), and
RetentionTask's start/stop lifecycle against a fast interval."""

from __future__ import annotations

import datetime
import time
import uuid

from sqlalchemy import select

from keystroke_dynamics.scores.models import ScoreAttempt
from keystroke_dynamics.scores.retention import RetentionTask, delete_expired_rows
from keystroke_dynamics.scores.writer import _write_batch

TODAY = datetime.date(2027, 1, 1)


def _row(created_on: datetime.date) -> dict[str, object]:
    return {
        "id": str(uuid.uuid4()),
        "created_on": created_on,
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


def test_delete_expired_rows_removes_only_what_is_older_than_the_cutoff(scores_db_session) -> None:
    old = _row(TODAY - datetime.timedelta(days=400))
    boundary = _row(TODAY - datetime.timedelta(days=365))  # exactly the default retention
    recent = _row(TODAY - datetime.timedelta(days=1))
    _write_batch([old, boundary, recent], [])

    deleted = delete_expired_rows(retention_days=365, today=TODAY)
    assert deleted == 1

    remaining_ids = {row.id for row in scores_db_session.execute(select(ScoreAttempt)).scalars()}
    assert remaining_ids == {boundary["id"], recent["id"]}


def test_delete_expired_rows_is_a_no_op_with_nothing_old_enough(scores_db_session) -> None:
    _write_batch([_row(TODAY)], [])
    assert delete_expired_rows(retention_days=365, today=TODAY) == 0


def test_retention_task_runs_on_start_without_waiting_a_full_interval(scores_db_session) -> None:
    old = _row(datetime.date.today() - datetime.timedelta(days=400))
    _write_batch([old], [])

    task = RetentionTask(retention_days=365, interval_seconds=60.0)
    task.start()
    try:
        deadline = time.monotonic() + 2.0
        remaining = [old["id"]]
        while time.monotonic() < deadline and remaining:
            remaining = [
                row.id
                for row in scores_db_session.execute(
                    select(ScoreAttempt).where(ScoreAttempt.id == old["id"])
                ).scalars()
            ]
            if remaining:
                time.sleep(0.02)
        assert remaining == [], "retention task never ran its first pass"
    finally:
        task.stop()
