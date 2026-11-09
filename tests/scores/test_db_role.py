"""The restricted app database role (tests/scores/conftest.py's
scores_app_role_url, mirroring exactly what DEPLOY.md instructs for
the real role on Neon): it can insert and delete score_attempts rows
-- everything the app actually does -- and nothing else at all.
docs/plans/done/PARTY_LAUNCH_PLAN.md section 10: "The app's database user may only
insert and delete rows in this table."

One real-world wrinkle this grant has to account for: a DELETE with a
WHERE clause needs SELECT on the columns the WHERE references (not
just DELETE on the table) -- Postgres has to be able to evaluate the
filter. scores/writer.py's own deletes filter by party_id/typist_id/
target_id, and scores/retention.py's by created_on, so the role gets
column-level SELECT on exactly those four -- still never a general
read path to any actual score, outcome, or other column.
"""

from __future__ import annotations

import datetime
import uuid

import psycopg
import psycopg.errors
import pytest

_COLUMNS = (
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
)


def _values(**overrides: object) -> dict[str, object]:
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


def _insert(conn: psycopg.Connection, **overrides: object) -> dict[str, object]:
    row = _values(**overrides)
    placeholders = ", ".join(f"%({c})s" for c in _COLUMNS)
    conn.execute(
        f"INSERT INTO score_attempts ({', '.join(_COLUMNS)}) VALUES ({placeholders})",  # noqa: S608
        row,
    )
    return row


def test_app_role_can_insert_and_delete_by_party_id(scores_app_role_url: str) -> None:
    # party_id, not id -- scores/writer.py's own deletes
    # (DeleteByPartyId/DeleteByPlayerScoreId) never filter by id, only
    # by party_id/typist_id/target_id (and scores/retention.py's by
    # created_on) -- see tests/scores/conftest.py's grant comment on
    # why a DELETE's WHERE clause needs column-level SELECT on exactly
    # the columns it filters by.
    with psycopg.connect(scores_app_role_url, autocommit=True) as conn:
        row = _insert(conn)
        conn.execute("DELETE FROM score_attempts WHERE party_id = %s", (row["party_id"],))


def test_app_role_cannot_delete_by_a_column_outside_the_grant(scores_app_role_url: str) -> None:
    # id itself was deliberately left out of the column-level SELECT
    # grant -- the app never needs to filter a delete by it, and this
    # confirms the grant is actually that narrow, not just "SELECT on
    # everything in practice".
    with psycopg.connect(scores_app_role_url, autocommit=True) as conn:
        row = _insert(conn)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM score_attempts WHERE id = %s", (row["id"],))


def test_app_role_cannot_select_star(scores_app_role_url: str) -> None:
    with psycopg.connect(scores_app_role_url, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM score_attempts")


def test_app_role_cannot_select_a_scoring_column(scores_app_role_url: str) -> None:
    # Confirms the column-level grant is actually narrow, not a stand-
    # in for full SELECT: outcome (or any other actual score data) is
    # never readable, only the four identifier columns a delete's own
    # WHERE clause needs.
    with psycopg.connect(scores_app_role_url, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT outcome FROM score_attempts")


def test_app_role_can_select_the_four_columns_its_own_deletes_filter_by(
    scores_app_role_url: str,
) -> None:
    with psycopg.connect(scores_app_role_url, autocommit=True) as conn:
        _insert(conn)
        conn.execute("SELECT party_id, typist_id, target_id, created_on FROM score_attempts")


def test_app_role_cannot_update(scores_app_role_url: str) -> None:
    # Insert as the real app role (what it's actually used for), then
    # try to UPDATE as that same role -- must fail even though the
    # row exists and INSERT on this exact table is allowed. The row
    # itself is cleaned up by the autouse TRUNCATE between tests
    # (tests/scores/conftest.py's _clean_score_attempts), same as
    # every other test here.
    with psycopg.connect(scores_app_role_url, autocommit=True) as conn:
        row = _insert(conn)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE score_attempts SET outcome = 'fail' WHERE id = %s", (row["id"],))


def test_app_role_cannot_read_the_alembic_version_table(scores_app_role_url: str) -> None:
    # The only other object in this schema -- confirms the restriction
    # isn't specific to score_attempts by name, but genuinely "nothing
    # except what was explicitly granted".
    with psycopg.connect(scores_app_role_url, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM alembic_version")


def test_app_role_cannot_create_a_table(scores_app_role_url: str) -> None:
    with psycopg.connect(scores_app_role_url, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("CREATE TABLE should_not_work (id int)")
