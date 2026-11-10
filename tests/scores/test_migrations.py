"""migrations_scores/, against real Postgres: the same_keyboard
migration (docs/plans/active/ROOMS_PLAN.md Phase 1 section 5) applies
to a database that is at the schema production runs today, with rows
already in it, and loses none of them.
"""

from __future__ import annotations

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config as AlembicConfig
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text

from keystroke_dynamics.scores.models import Base
from tests.scores.conftest import REPO_ROOT, SCORES_TEST_DATABASE_URL, _scores_engine
from tests.scores.test_db_role import _COLUMNS, _values

#: The schema live before rooms: score_attempts as first created.
BEFORE_ROOMS = "4148bfbe4bd6"
ADD_SAME_KEYBOARD = "7c2e9a4f1b3d"


def _alembic_config() -> AlembicConfig:
    cfg = AlembicConfig(str(REPO_ROOT / "alembic_scores.ini"))
    cfg.set_main_option("sqlalchemy.url", SCORES_TEST_DATABASE_URL)
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations_scores"))
    return cfg


def _column_names() -> set[str]:
    with _scores_engine.connect() as conn:
        return {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'score_attempts'"
                )
            )
        }


def test_same_keyboard_migration_directly_follows_the_first_one() -> None:
    script = ScriptDirectory.from_config(_alembic_config())
    assert script.get_heads() == [ADD_SAME_KEYBOARD]
    assert script.get_revision(ADD_SAME_KEYBOARD).down_revision == BEFORE_ROOMS


def test_same_keyboard_migration_keeps_existing_rows() -> None:
    cfg = _alembic_config()
    try:
        # Back to exactly what's deployed today, then put rows in it
        # the way the pre-rooms app wrote them: no same_keyboard at all.
        command.downgrade(cfg, BEFORE_ROOMS)
        assert "same_keyboard" not in _column_names()

        before = [_values(rhythm=0.4 + i / 10, outcome="pass") for i in range(3)]
        before.append(_values(rhythm=None, total=None, outcome="unusable"))
        placeholders = ", ".join(f":{c}" for c in _COLUMNS)
        with _scores_engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO score_attempts ({', '.join(_COLUMNS)}) "  # noqa: S608
                    f"VALUES ({placeholders})"
                ),
                before,
            )

        command.upgrade(cfg, "head")

        with _scores_engine.connect() as conn:
            after = {
                str(row["id"]): row
                for row in conn.execute(text("SELECT * FROM score_attempts")).mappings()
            }
        assert set(after) == {row["id"] for row in before}
        for row in before:
            stored = after[str(row["id"])]
            # Every value the row had is untouched...
            for column in _COLUMNS:
                if column == "id":
                    continue
                expected = row[column]
                actual = stored[column]
                assert str(actual) == str(expected) if expected is not None else actual is None
            # ...and the new column reads as "not recorded".
            assert stored["same_keyboard"] is None
    finally:
        # Whatever happened above, leave the shared test database at
        # head for the rest of the session.
        command.upgrade(cfg, "head")


def test_migrated_schema_matches_the_model() -> None:
    command.upgrade(_alembic_config(), "head")
    with _scores_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_the_app_role_can_still_insert_after_the_migration(scores_app_role_url: str) -> None:
    # The real app role has INSERT on the table, not on a column list,
    # so the new column must be writable with no new grant.
    import psycopg

    row = {**_values(), "same_keyboard": False}
    columns = (*_COLUMNS, "same_keyboard")
    with psycopg.connect(scores_app_role_url) as conn:
        conn.execute(
            f"INSERT INTO score_attempts ({', '.join(columns)}) "  # noqa: S608
            f"VALUES ({', '.join(f'%({c})s' for c in columns)})",
            row,
        )
        conn.commit()
    with _scores_engine.connect() as conn:
        stored = conn.execute(
            text("SELECT same_keyboard FROM score_attempts WHERE id = :id"), {"id": row["id"]}
        ).scalar_one()
    assert stored is False
