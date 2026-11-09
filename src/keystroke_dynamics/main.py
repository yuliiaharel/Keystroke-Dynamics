"""App creation and wiring.

Single worker, by design: the anonymous party game's state
(game/store.py) lives entirely in this one process's memory, shared by
nothing else. A second worker or container would get its own,
independent copy of the store, silently splitting one party across
two places with no way to reconcile them. Part 2 (deployment) is
responsible for actually configuring the server to run exactly one
worker process -- this is just why that constraint exists.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from keystroke_dynamics.api import game, pages
from keystroke_dynamics.api.middleware import MaxBodySizeMiddleware
from keystroke_dynamics.config import settings
from keystroke_dynamics.scores.retention import retention_task
from keystroke_dynamics.scores.writer import score_writer


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncGenerator[None]:
    # Both are constructed unconditionally (scores/writer.py,
    # scores/retention.py) and touch no database until started --
    # only actually run when score collection is configured at all
    # (PARTY_LAUNCH_PLAN.md section 10: off by default, the game
    # works normally either way). .stop() makes a best-effort flush;
    # a crash (or SIGKILL, which skips this entirely) can still lose
    # queued rows, per the plan's own allowance.
    if settings.scores_database_url:
        score_writer.start()
        retention_task.start()
    try:
        yield
    finally:
        if settings.scores_database_url:
            score_writer.stop()
            retention_task.stop()


app = FastAPI(title="Keystroke Dynamics", lifespan=_lifespan)

# No CORS middleware: the app is same-origin only (see
# api/security.py:require_matching_origin for the explicit Origin
# check on top of that).

app.add_middleware(MaxBodySizeMiddleware, max_bytes=settings.max_body_bytes)

# Signed, HttpOnly cookie sessions. SameSite=Lax (the default) already
# blocks the cookie on cross-site fetch/XHR; https_only adds Secure
# outside local development, per the debug flag. The secret comes from
# the environment via config.settings. The anonymous game's own
# identity (api/game.py) rides this same cookie -- there's no second
# signing mechanism.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    https_only=not settings.debug,
)

# The anonymous game has no database dependency either way, so its
# router is always mounted -- see api/game.py and game/store.py.
app.include_router(game.router)
app.include_router(pages.router)

if settings.enable_accounts:
    # Imported here, not at module level: public mode (the default)
    # must never construct a database engine at all, not just avoid
    # using one. auth.py/profile.py (and the account pages inside
    # pages.py) are the only things in this app that import db/ --
    # see api/security.py for the matching split on the dependency
    # side, which is what lets api/game.py avoid this import entirely.
    from keystroke_dynamics.api import account_pages, auth, profile

    app.include_router(auth.router)
    app.include_router(profile.router)
    app.include_router(account_pages.router)

_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
