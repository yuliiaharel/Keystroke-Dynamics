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
from psycopg import sql
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


@pytest.fixture(autouse=True)
def _use_test_db_for_scores_db_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """scores/db.py's scores_session() (what the real writer uses by
    default) builds its engine from settings.scores_database_url --
    None in every test process here, since setting that env var would
    also change what tests/test_config.py's own tests see. Point its
    module-level cache at this package's test engine/session factory
    directly instead, for every test under tests/scores/."""
    import keystroke_dynamics.scores.db as scores_db

    monkeypatch.setattr(scores_db, "_engine", _scores_engine)
    monkeypatch.setattr(scores_db, "_SessionLocal", _ScoresSessionLocal)


@pytest.fixture
def scores_db_session():
    db = _ScoresSessionLocal()
    try:
        yield db
    finally:
        db.close()


#: Exactly what DEPLOY.md instructs granting to the real app role on
#: Neon (PARTY_LAUNCH_PLAN.md section 10: "The app's database user may
#: only insert and delete rows in this table") -- test_db_role.py
#: proves this grant set is actually sufficient (the app still works)
#: and actually restrictive (nothing else is possible), against a
#: real Postgres role, not a mock.
APP_ROLE_NAME = "scores_app_role_test"
APP_ROLE_PASSWORD = "test-only-password-not-used-anywhere-real"  # noqa: S105


def _create_or_reset_app_role() -> None:
    # CREATE ROLE is DDL -- its PASSWORD clause doesn't accept a bound
    # parameter the way a normal DML statement would (postgres parses
    # the whole statement before execution, with no placeholder
    # support in this position), so the password is composed as a
    # literal via psycopg.sql instead of string-formatted directly.
    admin_scores_url = SCORES_TEST_DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(admin_scores_url, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_ROLE_NAME,)
        ).fetchone()
        if exists is None:
            conn.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(APP_ROLE_NAME), sql.Literal(APP_ROLE_PASSWORD)
                )
            )
        # Idempotent, and re-run every session: harmless if already
        # granted, and necessary the first time after each fresh
        # CREATE TABLE (a brand-new test database on another machine,
        # say, has the role but not yet the grant on this table).
        conn.execute(f"GRANT CONNECT ON DATABASE {SCORES_TEST_DATABASE_NAME} TO {APP_ROLE_NAME}")
        conn.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE_NAME}")
        conn.execute(f"GRANT INSERT, DELETE ON score_attempts TO {APP_ROLE_NAME}")
        # A DELETE with a WHERE clause needs SELECT on the columns the
        # WHERE references, even with no general read access (Postgres
        # has to be able to evaluate the filter) -- scores/writer.py's
        # deletes filter by party_id/typist_id/target_id, and
        # scores/retention.py's by created_on. This column-level grant
        # covers exactly those four and nothing else: the app role
        # still can't read a single score, outcome, or any other
        # column.
        conn.execute(
            f"GRANT SELECT (party_id, typist_id, target_id, created_on) "  # noqa: S608
            f"ON score_attempts TO {APP_ROLE_NAME}"
        )


@pytest.fixture(scope="session")
def scores_app_role_url(_migrated_scores_database: None) -> str:
    """A real, restricted Postgres role -- login, INSERT and DELETE on
    score_attempts, plus column-level SELECT on exactly the four
    columns its own deletes filter by (see the grant comment above;
    no other column, and no other table, is readable) -- not a mock
    of one. Depends on _migrated_scores_database explicitly (not just
    its autouse order) since the table must exist before GRANT can
    name it."""
    _create_or_reset_app_role()
    return f"postgresql://{APP_ROLE_NAME}:{APP_ROLE_PASSWORD}@localhost:5433/{SCORES_TEST_DATABASE_NAME}"
