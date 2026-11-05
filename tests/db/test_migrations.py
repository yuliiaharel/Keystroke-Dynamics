"""Exercises the migrations directly, independent of the once-per-session
autouse fixture in conftest.py. That fixture happens to run against an
empty database too (docker-compose's tmpfs-backed test-db starts with
nothing in it), but this test makes the plan's "migrations apply to an
empty database and match the models" requirement explicit and
re-runnable on its own, rather than relying on fixture setup order.
"""

from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config as AlembicConfig
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from keystroke_dynamics.db.models import Base

REPO_ROOT = Path(__file__).parent.parent.parent
TEST_DATABASE_URL = os.environ["DATABASE_URL"]  # set by tests/conftest.py


def _alembic_config() -> AlembicConfig:
    cfg = AlembicConfig(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return cfg


def test_migrations_apply_to_an_empty_database_and_match_the_models() -> None:
    cfg = _alembic_config()

    # Tear everything down to a genuinely empty database -- not just the
    # row-level truncation conftest.py does between tests -- then apply
    # every migration from scratch, the same as a brand new deployment.
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")

    # What results must match the ORM models exactly: no table, column,
    # or constraint the models define is missing, and nothing extra
    # that a migration created but the models don't know about.
    engine = create_engine(TEST_DATABASE_URL)
    try:
        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            diff = compare_metadata(context, Base.metadata)
        assert diff == []
    finally:
        engine.dispose()
