"""migrations_scores/, against real Postgres. Each migration is
applied to a database at the schema production ran before it, with
rows already in it, and loses none of them: same_keyboard
(docs/plans/active/ROOMS_PLAN.md Phase 1 section 5), then the touch
line and grip mode (docs/plans/active/MOBILE_PLAN.md Phase 1 section 6).
"""

from __future__ import annotations

import psycopg
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config as AlembicConfig
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from keystroke_dynamics.scores.models import Base
from tests.scores.conftest import REPO_ROOT, SCORES_TEST_DATABASE_URL, _scores_engine
from tests.scores.test_db_role import _COLUMNS, _values

#: The schema live before rooms: score_attempts as first created.
BEFORE_ROOMS = "4148bfbe4bd6"
ADD_SAME_KEYBOARD = "7c2e9a4f1b3d"
#: The schema live before touch rooms: with same_keyboard, and with
#: line_id and mode still limited to the keyboard game's values.
ALLOW_TOUCH = "9d5b3e6a2c81"

_COLUMNS_WITH_SAME_KEYBOARD = (*_COLUMNS, "same_keyboard")
_INSERT_WITH_SAME_KEYBOARD = (
    f"INSERT INTO score_attempts ({', '.join(_COLUMNS_WITH_SAME_KEYBOARD)}) "  # noqa: S608
    f"VALUES ({', '.join(f':{c}' for c in _COLUMNS_WITH_SAME_KEYBOARD)})"
)


def _touch_row(**overrides: object) -> dict[str, object]:
    """A row the touch game writes: both scores, and the phone
    question answered."""
    row = _values(
        scoring_version="3",
        device_type="touch",
        line_id="touch",
        rhythm=0.9,
        place=1.4,
        total=1.1,
    )
    return {**row, "same_keyboard": True, **overrides}


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


def test_the_migrations_form_one_chain_in_the_order_they_shipped() -> None:
    # Was "same_keyboard is the only head" until the touch migration
    # was added after it. Still one head, still no branch.
    script = ScriptDirectory.from_config(_alembic_config())
    assert script.get_heads() == [ALLOW_TOUCH]
    assert script.get_revision(ALLOW_TOUCH).down_revision == ADD_SAME_KEYBOARD
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


def _check_constraints() -> dict[str, str]:
    with _scores_engine.connect() as conn:
        return {
            row[0]: row[1]
            for row in conn.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = 'score_attempts'::regclass AND contype = 'c'"
                )
            )
        }


def test_touch_migration_keeps_existing_rows_and_allows_touch_and_grip() -> None:
    cfg = _alembic_config()
    try:
        # Exactly what's deployed today: same_keyboard exists, and the
        # two constraints still allow only the keyboard game's values.
        command.downgrade(cfg, ADD_SAME_KEYBOARD)
        assert "same_keyboard" in _column_names()

        before = [
            {
                **_values(line_id="sentence", mode="attack", rhythm=0.9, total=0.9),
                "same_keyboard": False,
            },
            {**_values(line_id="long", mode="self"), "same_keyboard": True},
            {**_values(line_id="word", mode="disguise"), "same_keyboard": None},
            {
                **_values(
                    line_id="sentence", mode="replay", rhythm=None, total=None, outcome="unusable"
                ),
                "same_keyboard": None,
            },
        ]
        with _scores_engine.begin() as conn:
            conn.execute(text(_INSERT_WITH_SAME_KEYBOARD), before)

        # Before the migration, the old constraints refuse both new values.
        for refused in (_touch_row(), _touch_row(line_id="sentence", mode="grip")):
            with pytest.raises(IntegrityError), _scores_engine.begin() as conn:
                conn.execute(text(_INSERT_WITH_SAME_KEYBOARD), refused)

        command.upgrade(cfg, "head")

        with _scores_engine.connect() as conn:
            after = {
                str(row["id"]): row
                for row in conn.execute(text("SELECT * FROM score_attempts")).mappings()
            }
        assert set(after) == {row["id"] for row in before}
        for row in before:
            stored = after[str(row["id"])]
            for column in _COLUMNS_WITH_SAME_KEYBOARD:
                if column == "id":
                    continue
                expected = row[column]
                actual = stored[column]
                assert str(actual) == str(expected) if expected is not None else actual is None

        # After it, a touch-line row and a grip row both go in...
        touch = _touch_row(mode="attack")
        grip = _touch_row(mode="grip")
        with _scores_engine.begin() as conn:
            conn.execute(text(_INSERT_WITH_SAME_KEYBOARD), [touch, grip])
        with _scores_engine.connect() as conn:
            stored_rows = {
                str(row["id"]): row
                for row in conn.execute(
                    text("SELECT * FROM score_attempts WHERE line_id = 'touch'")
                ).mappings()
            }
        assert set(stored_rows) == {touch["id"], grip["id"]}
        assert stored_rows[str(grip["id"])]["mode"] == "grip"
        assert stored_rows[str(touch["id"])]["place"] == 1.4

        # ...and the constraints still refuse anything else.
        for refused in (_touch_row(line_id="paragraph"), _touch_row(mode="practice")):
            with pytest.raises(IntegrityError), _scores_engine.begin() as conn:
                conn.execute(text(_INSERT_WITH_SAME_KEYBOARD), refused)
    finally:
        command.upgrade(cfg, "head")


def test_touch_migration_leaves_every_other_constraint_as_it_was() -> None:
    cfg = _alembic_config()
    try:
        command.downgrade(cfg, ADD_SAME_KEYBOARD)
        before = _check_constraints()
        command.upgrade(cfg, "head")
        after = _check_constraints()
    finally:
        command.upgrade(cfg, "head")
    assert set(after) == set(before)
    changed = {name for name in after if after[name] != before[name]}
    assert changed == {"ck_line_id", "ck_mode"}
    assert "'touch'" in after["ck_line_id"] and "'touch'" not in before["ck_line_id"]
    assert "'grip'" in after["ck_mode"] and "'grip'" not in before["ck_mode"]


def test_touch_migration_downgrade_refuses_to_drop_touch_rows() -> None:
    cfg = _alembic_config()
    touch = _touch_row()
    try:
        command.upgrade(cfg, "head")
        with _scores_engine.begin() as conn:
            conn.execute(text(_INSERT_WITH_SAME_KEYBOARD), touch)
        with pytest.raises(IntegrityError):
            command.downgrade(cfg, ADD_SAME_KEYBOARD)
        # The failed downgrade changed nothing: the row is still there,
        # and the database still accepts another like it.
        with _scores_engine.begin() as conn:
            conn.execute(text(_INSERT_WITH_SAME_KEYBOARD), _touch_row(mode="grip"))
        with _scores_engine.connect() as conn:
            count = conn.execute(
                text("SELECT count(*) FROM score_attempts WHERE line_id = 'touch'")
            ).scalar_one()
        assert count == 2
    finally:
        command.upgrade(cfg, "head")


def test_the_app_role_can_insert_touch_and_grip_rows_with_no_new_grant(
    scores_app_role_url: str,
) -> None:
    # The app role's INSERT is on the table, so widening a constraint
    # needs no grant change -- nothing to do by hand after the deploy.
    rows = [_touch_row(mode="attack"), _touch_row(mode="grip")]
    with psycopg.connect(scores_app_role_url) as conn:
        for row in rows:
            conn.execute(
                f"INSERT INTO score_attempts ({', '.join(_COLUMNS_WITH_SAME_KEYBOARD)}) "  # noqa: S608
                f"VALUES ({', '.join(f'%({c})s' for c in _COLUMNS_WITH_SAME_KEYBOARD)})",
                row,
            )
        conn.commit()
    with _scores_engine.connect() as conn:
        modes = {
            row[0]
            for row in conn.execute(
                text("SELECT mode FROM score_attempts WHERE device_type = 'touch'")
            )
        }
    assert modes == {"attack", "grip"}


def test_migrated_schema_matches_the_model() -> None:
    command.upgrade(_alembic_config(), "head")
    with _scores_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_the_app_role_can_still_insert_after_the_migration(scores_app_role_url: str) -> None:
    # The real app role has INSERT on the table, not on a column list,
    # so the new column must be writable with no new grant.
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
