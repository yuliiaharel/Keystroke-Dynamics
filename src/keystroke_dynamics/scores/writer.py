"""Bounded in-memory queue + a background thread that batches writes
to the scores database, so no request ever waits on it
(PARTY_LAUNCH_PLAN.md section 10: "Never let a request wait on the
database"). If the queue is full -- the database is slow, down,
asleep, or full -- a new command is dropped, with only a count
logged, never the row itself (logging it would partially defeat
"never store... key timing" if a crash dump or log aggregator ever
captured it).

One ScoreWriter instance per process (score_writer below, constructed
unconditionally -- it touches no database at import time, so public
mode and every other no-scores-configured case can still import this
module safely). main.py's lifespan calls .start()/.stop() only when
settings.scores_database_url is actually set; api/game.py only ever
calls .enqueue() behind that same check.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import delete, insert

from keystroke_dynamics.config import settings
from keystroke_dynamics.scores.db import scores_session
from keystroke_dynamics.scores.models import ScoreAttempt

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InsertRow:
    row: dict[str, object]


@dataclass(frozen=True)
class DeleteByPartyId:
    """'New party'/party expiry cascade -- every row this party's own
    score_id ever appeared on, as typist, target, or party, since
    party_id is stamped on every row regardless of which side a given
    player was on."""

    party_id: str


@dataclass(frozen=True)
class DeleteByPlayerScoreId:
    """'Delete me' -- every row where this player was the typist or
    the target (within or across parties; the plan doesn't scope
    "Delete me" to the current party only)."""

    score_id: str


DeleteCommand = DeleteByPartyId | DeleteByPlayerScoreId
Command = InsertRow | DeleteCommand


def _write_batch(inserts: list[dict[str, object]], deletes: list[DeleteCommand]) -> None:
    """The real sink: one bulk insert, then every delete, in one
    transaction. Inserts always applied before deletes in the same
    batch -- regardless of which was enqueued first -- so a
    'Delete me'/'New party' queued moments after a still-unwritten
    insert for the same id reliably wins rather than racing it; see
    the module docstring on why that direction is the safe one.
    """
    with scores_session() as session:
        if inserts:
            session.execute(insert(ScoreAttempt), inserts)
        for d in deletes:
            if isinstance(d, DeleteByPartyId):
                session.execute(delete(ScoreAttempt).where(ScoreAttempt.party_id == d.party_id))
            else:
                session.execute(
                    delete(ScoreAttempt).where(
                        (ScoreAttempt.typist_id == d.score_id)
                        | (ScoreAttempt.target_id == d.score_id)
                    )
                )
        session.commit()


class ScoreWriter:
    def __init__(
        self,
        *,
        max_size: int,
        batch_interval_seconds: float,
        write_batch: Callable[[list[dict[str, object]], list[DeleteCommand]], None] = _write_batch,
    ) -> None:
        self._queue: queue.Queue[Command] = queue.Queue(maxsize=max_size)
        self._batch_interval_seconds = batch_interval_seconds
        self._write_batch = write_batch
        self._dropped_count = 0
        self._dropped_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def enqueue(self, command: Command) -> None:
        """Never blocks, even when the queue is full -- see the
        module docstring."""
        try:
            self._queue.put_nowait(command)
        except queue.Full:
            with self._dropped_lock:
                self._dropped_count += 1
                count = self._dropped_count
            logger.warning("scores queue is full -- dropped a row (dropped so far: %d)", count)

    @property
    def dropped_count(self) -> int:
        with self._dropped_lock:
            return self._dropped_count

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="scores-writer", daemon=True)
        self._thread.start()

    def stop(self, *, flush_timeout_seconds: float = 5.0) -> None:
        """Signals the writer thread to stop, then makes one best-
        effort attempt to flush whatever's still queued. A crash (or
        SIGKILL, which gives no shutdown hook at all) can still lose
        queued rows -- the plan accepts that explicitly."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=flush_timeout_seconds)
            self._thread = None
        self._drain_once()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._drain_once(wait_seconds=self._batch_interval_seconds)

    def _drain_once(self, wait_seconds: float = 0.0) -> None:
        commands = self._collect(wait_seconds)
        if not commands:
            return
        inserts = [c.row for c in commands if isinstance(c, InsertRow)]
        deletes = [c for c in commands if not isinstance(c, InsertRow)]
        try:
            self._write_batch(inserts, deletes)
        except Exception:
            # Never let one bad/unreachable batch take the writer
            # thread down -- the next batch (and the next flush on
            # shutdown) still gets a chance. Rows in *this* batch are
            # lost, same as the plan's own crash-can-lose-rows
            # allowance; logged as a count only, same as a dropped row.
            logger.exception(
                "scores writer failed to write a batch of %d command(s)", len(commands)
            )

    def _collect(self, wait_seconds: float) -> list[Command]:
        commands: list[Command] = []
        try:
            first = (
                self._queue.get(timeout=wait_seconds) if wait_seconds else self._queue.get_nowait()
            )
            commands.append(first)
        except queue.Empty:
            return commands
        while True:
            try:
                commands.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return commands


#: The one process-wide writer -- see the module docstring.
score_writer = ScoreWriter(
    max_size=settings.scores_queue_max_size,
    batch_interval_seconds=settings.scores_writer_batch_interval_seconds,
)
