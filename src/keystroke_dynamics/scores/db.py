"""Engine and session factory for the scores database -- separate
from db/session.py's (the account system's), and unlike it, never
created unconditionally at import time: public mode must be able to
import this whole package with no database of any kind configured
(see config.py's scores_database_url), so the engine is built lazily,
on first actual use, and only if a URL is set at all.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from keystroke_dynamics.config import settings

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _ensure_engine() -> tuple[Engine, sessionmaker[Session]]:
    global _engine, _SessionLocal
    if _engine is None:
        if not settings.scores_database_url:
            raise RuntimeError(
                "scores/db.py was used with no SCORES_DATABASE_URL set -- "
                "callers must check settings.scores_database_url first."
            )
        _engine = create_engine(settings.scores_database_url)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    assert _SessionLocal is not None
    return _engine, _SessionLocal


@contextmanager
def scores_session() -> Generator[Session]:
    """A session on the scores database. Raises RuntimeError if
    scores_database_url isn't set -- callers (the writer, the
    retention task) check settings.scores_database_url themselves
    before ever reaching here; this is a defensive backstop, not the
    intended way to detect "collection is off".
    """
    _, session_local = _ensure_engine()
    session = session_local()
    try:
        yield session
    finally:
        session.close()
