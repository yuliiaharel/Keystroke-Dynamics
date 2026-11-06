"""Fixtures for the scores database (PARTY_LAUNCH_PLAN.md section
10): a second, separate test database on the same local Postgres
server tests/conftest.py already uses -- never the account system's
own keystroke_dynamics_test, since these are two independent
databases in real deployment (SCORES_DATABASE_URL vs DATABASE_URL)
and must stay that way in tests too.

The official postgres image only creates the one database named by
POSTGRES_DB on first init (docker-compose.test.yml), so this module
creates its own database (via a plain CREATE DATABASE, not an init
script) the first time any test here runs, rather than requiring a
second service container just for this.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).parent.parent.parent
_ADMIN_DATABASE_URL = "postgresql://keystroke:keystroke@localhost:5433/keystroke_dynamics_test"
SCORES_TEST_DATABASE_NAME = "keystroke_dynamics_scores_test"
SCORES_TEST_DATABASE_URL = (
    f"postgresql+psycopg://keystroke:keystroke@localhost:5433/{SCORES_TEST_DATABASE_NAME}"
)

_scores_engine = create_engine(SCORES_TEST_DATABASE_URL)
_ScoresSessionLocal = sessionmaker(bind=_scores_engine, autoflush=False, expire_on_commit=False)


def _create_database_if_missing() -> None:
    # autocommit=True: CREATE DATABASE can't run inside a transaction.
    with psycopg.connect(_ADMIN_DATABASE_URL, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (SCORES_TEST_DATABASE_NAME,)
        ).fetchone()
        if exists is None:
            conn.execute(f"CREATE DATABASE {SCORES_TEST_DATABASE_NAME}")  # noqa: S608


@pytest.fixture(scope="session", autouse=True)
def _migrated_scores_database():
    """Creates the scores test database if it doesn't exist yet, then
    applies migrations_scores/ to it once per test session -- this is
    also the "migrations apply to an empty database" check, same
    reasoning as tests/conftest.py's own _migrated_database."""
    _create_database_if_missing()
    cfg = AlembicConfig(str(REPO_ROOT / "alembic_scores.ini"))
    cfg.set_main_option("sqlalchemy.url", SCORES_TEST_DATABASE_URL)
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations_scores"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _clean_score_attempts():
    yield
    with _scores_engine.begin() as conn:
        conn.execute(text("TRUNCATE score_attempts"))


@pytest.fixture
def scores_db_session():
    db = _ScoresSessionLocal()
    try:
        yield db
    finally:
        db.close()
