"""Shared test fixtures. Sets the environment variables the app reads
at import time before anything imports it, so tests always run
against the dedicated test database and a known Origin -- never the
settings a developer might have in their own .env.
"""

import os
from pathlib import Path

os.environ["DATABASE_URL"] = (
    "postgresql+psycopg://keystroke:keystroke@localhost:5433/keystroke_dynamics_test"
)
os.environ["SESSION_SECRET"] = "test-secret-not-for-production"
os.environ["ALLOWED_ORIGIN"] = "http://testserver"
os.environ["DEBUG"] = "true"
# This test config uses Postgres, so the account system (and its own
# tests) needs it mounted -- see docs/plans/done/PARTY_LAUNCH_PLAN.md Part 1 section 1.
# The *other* mode (no accounts, no database) gets its own dedicated
# test module (tests/test_public_mode.py) that sets its own env and
# builds its own app instance, since this module-level app is only
# ever built once, with this one setting baked in.
os.environ["ENABLE_ACCOUNTS"] = "true"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config as AlembicConfig  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from keystroke_dynamics.api import game as game_api  # noqa: E402
from keystroke_dynamics.api.deps import (  # noqa: E402
    login_rate_limiter,
    register_rate_limiter,
    verify_rate_limiter,
)
from keystroke_dynamics.db.session import get_db  # noqa: E402
from keystroke_dynamics.game.rate_limit import (  # noqa: E402
    game_join_rate_limiter,
    game_rate_limiter,
)
from keystroke_dynamics.main import app  # noqa: E402

TEST_DATABASE_URL = os.environ["DATABASE_URL"]
REPO_ROOT = Path(__file__).parent.parent

_test_engine = create_engine(TEST_DATABASE_URL)
_TestSessionLocal = sessionmaker(bind=_test_engine, autoflush=False, expire_on_commit=False)


def _override_get_db():  # type: ignore[no-untyped-def]
    db = _TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(scope="session", autouse=True)
def _migrated_database():
    """Applies migrations once per test session -- this is also the
    "migrations apply to an empty database" check, run for real
    against a database that starts with nothing in it (docker-compose
    rebuilds test-db's tmpfs volume from scratch every time it's
    (re)started).
    """
    cfg = AlembicConfig(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    with _test_engine.begin() as conn:
        conn.execute(
            text("TRUNCATE profile_features, typing_profiles, users RESTART IDENTITY CASCADE")
        )


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    # The rate limiters are process-global singletons (see api/deps.py
    # and game/rate_limit.py) so one test's calls to a rate-limited
    # endpoint don't eat into another's budget -- this is test
    # isolation, not something the app itself ever does.
    limiters = (
        login_rate_limiter,
        register_rate_limiter,
        verify_rate_limiter,
        game_rate_limiter,
        game_join_rate_limiter,
    )
    for limiter in limiters:
        limiter.reset()


@pytest.fixture(autouse=True)
def _clear_game_store():
    # The in-memory game store (api/game.py's module-global _store) is
    # also process-global -- same reasoning as the rate limiters above.
    yield
    game_api._store._parties.clear()  # noqa: SLF001


@pytest.fixture
def client():
    with TestClient(app, headers={"origin": os.environ["ALLOWED_ORIGIN"]}) as c:
        yield c


@pytest.fixture
def db_session():
    """A direct DB session for test-side assertions, separate from
    whatever session the app's own request handling uses -- for
    checking what actually landed in the database, not what the app
    says it did."""
    db = _TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def registered_user(client: TestClient) -> dict[str, str]:
    credentials = {"username": "alice", "password": "correct-password-123"}
    resp = client.post("/api/register", json=credentials)
    assert resp.status_code == 201, resp.text
    return credentials


@pytest.fixture
def logged_in_client(client: TestClient, registered_user: dict[str, str]) -> TestClient:
    resp = client.post("/api/login", json=registered_user)
    assert resp.status_code == 200, resp.text
    return client
