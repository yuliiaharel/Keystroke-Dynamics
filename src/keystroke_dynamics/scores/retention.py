"""Daily background task that deletes score_attempts rows older than
settings.scores_retention_days (docs/plans/done/PARTY_LAUNCH_PLAN.md section 10:
"Delete rows older than a configurable retention period, default 12
months, with a daily background task").
"""

from __future__ import annotations

import datetime
import logging
import threading
from typing import cast

from sqlalchemy import delete
from sqlalchemy.engine import CursorResult

from keystroke_dynamics.config import settings
from keystroke_dynamics.scores.db import scores_session
from keystroke_dynamics.scores.models import ScoreAttempt

logger = logging.getLogger(__name__)

SECONDS_PER_DAY = 24 * 60 * 60


def delete_expired_rows(*, retention_days: int, today: datetime.date | None = None) -> int:
    """Deletes every row with created_on older than retention_days
    ago, and returns how many. A pure function of "today" (defaulting
    to the real date) so it's directly testable without waiting for a
    real day to pass, or depending on wall-clock time at all.
    """
    cutoff = (today or datetime.date.today()) - datetime.timedelta(days=retention_days)
    with scores_session() as session:
        # delete() always executes as a CursorResult (never a Row-
        # yielding Result), so .rowcount is always there at runtime --
        # session.execute()'s general-purpose return type just doesn't
        # say so statically.
        result = cast(
            CursorResult[tuple[()]],
            session.execute(delete(ScoreAttempt).where(ScoreAttempt.created_on < cutoff)),
        )
        session.commit()
        return result.rowcount


class RetentionTask:
    """Owns the background thread that runs delete_expired_rows()
    once, then once a day. Same start()/stop() shape as
    scores/writer.py's ScoreWriter, and constructed unconditionally
    (no database touch until actually run) for the same import-safety
    reason -- public mode must be able to import this module with no
    database configured at all.
    """

    def __init__(self, *, retention_days: int, interval_seconds: float = SECONDS_PER_DAY) -> None:
        self._retention_days = retention_days
        self._interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="scores-retention", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _run(self) -> None:
        # Runs once right away (so a long-idle instance that just
        # restarted doesn't wait a full day before its first cleanup),
        # then once per interval, exiting promptly if stop() is called
        # during the wait rather than only after it elapses.
        while not self._stop.is_set():
            try:
                deleted = delete_expired_rows(retention_days=self._retention_days)
                if deleted:
                    logger.info("scores retention deleted %d row(s)", deleted)
            except Exception:
                # Same reasoning as ScoreWriter._drain_once: one
                # failed run (database briefly unreachable) must not
                # take the whole background task down -- it gets
                # another try next interval.
                logger.exception("scores retention task failed")
            if self._stop.wait(timeout=self._interval_seconds):
                return


#: The one process-wide retention task -- see the class docstring.
retention_task = RetentionTask(retention_days=settings.scores_retention_days)
