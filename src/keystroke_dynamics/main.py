"""App creation and wiring."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from keystroke_dynamics.api import auth, pages, profile
from keystroke_dynamics.api.middleware import MaxBodySizeMiddleware
from keystroke_dynamics.config import settings

app = FastAPI(title="Keystroke Dynamics")

# No CORS middleware: the app is same-origin only (see
# api/deps.py:require_matching_origin for the explicit Origin check on
# top of that).

app.add_middleware(MaxBodySizeMiddleware, max_bytes=settings.max_body_bytes)

# Signed, HttpOnly cookie sessions. SameSite=Lax (the default) already
# blocks the cookie on cross-site fetch/XHR; https_only adds Secure
# outside local development, per the debug flag. The secret comes from
# the environment via config.settings.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    https_only=not settings.debug,
)

app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(pages.router)

_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
