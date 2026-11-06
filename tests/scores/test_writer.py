"""scores/writer.py's queue + background thread, against a fake sink
(not a real database -- see test_writer_integration.py for that):
never blocks, drops and counts when full, batches a drain, and
applies inserts before deletes within one batch."""

from __future__ import annotations

import threading
import time

from keystroke_dynamics.scores.writer import (
    DeleteByPartyId,
    DeleteByPlayerScoreId,
    DeleteCommand,
    InsertRow,
    ScoreWriter,
)


class FakeSink:
    """Records every batch handed to it, and can be told to raise on
    the next call -- never touches a database."""

    def __init__(self) -> None:
        self.batches: list[tuple[list[dict[str, object]], list[DeleteCommand]]] = []
        self._raise_next = False
        self.lock = threading.Lock()

    def raise_on_next_call(self) -> None:
        self._raise_next = True

    def __call__(self, inserts: list[dict[str, object]], deletes: list[DeleteCommand]) -> None:
        with self.lock:
            if self._raise_next:
                self._raise_next = False
                raise RuntimeError("simulated database failure")
            self.batches.append((inserts, deletes))


def _row(id_: str = "r1") -> dict[str, object]:
    return {"id": id_}


def test_enqueue_never_blocks_and_drops_when_full() -> None:
    sink = FakeSink()
    writer = ScoreWriter(max_size=1, batch_interval_seconds=10.0, write_batch=sink)
    writer.enqueue(InsertRow(_row("a")))
    # The queue (size 1) is now full -- this must drop, not block.
    writer.enqueue(InsertRow(_row("b")))
    assert writer.dropped_count == 1


def test_stop_flushes_whatever_is_still_queued() -> None:
    sink = FakeSink()
    writer = ScoreWriter(max_size=10, batch_interval_seconds=10.0, write_batch=sink)
    writer.enqueue(InsertRow(_row("a")))
    writer.enqueue(InsertRow(_row("b")))
    # Never started -- stop() must still flush via its own best-effort
    # drain, not rely on a running thread having already done it.
    writer.stop()
    assert len(sink.batches) == 1
    inserts, deletes = sink.batches[0]
    assert [r["id"] for r in inserts] == ["a", "b"]
    assert deletes == []


def test_a_batch_applies_inserts_before_deletes() -> None:
    sink = FakeSink()
    writer = ScoreWriter(max_size=10, batch_interval_seconds=10.0, write_batch=sink)
    writer.enqueue(InsertRow(_row("a")))
    writer.enqueue(DeleteByPartyId("party-1"))
    writer.stop()
    assert len(sink.batches) == 1
    inserts, deletes = sink.batches[0]
    assert [r["id"] for r in inserts] == ["a"]
    assert deletes == [DeleteByPartyId("party-1")]


def test_delete_by_player_score_id_is_passed_through() -> None:
    sink = FakeSink()
    writer = ScoreWriter(max_size=10, batch_interval_seconds=10.0, write_batch=sink)
    writer.enqueue(DeleteByPlayerScoreId("player-1"))
    writer.stop()
    _, deletes = sink.batches[0]
    assert deletes == [DeleteByPlayerScoreId("player-1")]


def test_a_failed_batch_does_not_crash_the_writer_or_block_the_next_one() -> None:
    sink = FakeSink()
    sink.raise_on_next_call()
    writer = ScoreWriter(max_size=10, batch_interval_seconds=10.0, write_batch=sink)
    writer.enqueue(InsertRow(_row("a")))
    writer.stop()  # the flush raises internally -- must not propagate
    assert sink.batches == []  # the failed batch produced nothing

    # A later batch still works normally.
    writer.enqueue(InsertRow(_row("b")))
    writer.stop()
    assert len(sink.batches) == 1
    assert sink.batches[0][0][0]["id"] == "b"


def test_the_background_thread_actually_drains_without_an_explicit_stop() -> None:
    sink = FakeSink()
    writer = ScoreWriter(max_size=10, batch_interval_seconds=0.05, write_batch=sink)
    writer.start()
    try:
        writer.enqueue(InsertRow(_row("a")))
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not sink.batches:
            time.sleep(0.02)
        assert sink.batches, "writer thread never drained the queue"
        assert sink.batches[0][0][0]["id"] == "a"
    finally:
        writer.stop()
