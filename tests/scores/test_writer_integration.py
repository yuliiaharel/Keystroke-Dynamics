"""scores/writer.py against the real scores test database -- the one
thing test_writer.py's fake sink can't cover: that _write_batch()
itself actually inserts and deletes real rows."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import select

from keystroke_dynamics.scores.models import ScoreAttempt
from keystroke_dynamics.scores.writer import (
    DeleteByPartyId,
    DeleteByPlayerScoreId,
    InsertRow,
    ScoreWriter,
    _write_batch,
)


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


def test_write_batch_inserts_rows(scores_db_session) -> None:
    row = _row()
    _write_batch([row], [])
    stored = scores_db_session.execute(
        select(ScoreAttempt).where(ScoreAttempt.id == row["id"])
    ).scalar_one()
    assert stored.outcome == "pass"


def test_write_batch_deletes_by_party_id(scores_db_session) -> None:
    party_id = str(uuid.uuid4())
    row = _row(party_id=party_id)
    _write_batch([row], [])
    _write_batch([], [DeleteByPartyId(party_id)])
    remaining = scores_db_session.execute(
        select(ScoreAttempt).where(ScoreAttempt.party_id == party_id)
    ).all()
    assert remaining == []


def test_write_batch_deletes_by_player_score_id_as_either_typist_or_target(
    scores_db_session,
) -> None:
    score_id = str(uuid.uuid4())
    as_typist = _row(typist_id=score_id)
    as_target = _row(target_id=score_id)
    unrelated = _row()
    _write_batch([as_typist, as_target, unrelated], [])

    _write_batch([], [DeleteByPlayerScoreId(score_id)])

    remaining_ids = {row.id for row in scores_db_session.execute(select(ScoreAttempt)).scalars()}
    assert remaining_ids == {unrelated["id"]}


def test_insert_then_delete_in_one_batch_leaves_nothing(scores_db_session) -> None:
    # Exercises the real ScoreWriter (not _write_batch directly) end
    # to end against Postgres: an insert and a same-score_id delete
    # enqueued together must never leave the row behind.
    score_id = str(uuid.uuid4())
    row = _row(typist_id=score_id)
    writer = ScoreWriter(max_size=10, batch_interval_seconds=10.0)
    writer.enqueue(InsertRow(row))
    writer.enqueue(DeleteByPlayerScoreId(score_id))
    writer.stop()

    remaining = scores_db_session.execute(
        select(ScoreAttempt).where(ScoreAttempt.id == row["id"])
    ).all()
    assert remaining == []
