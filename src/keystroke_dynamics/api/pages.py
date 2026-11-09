"""The anonymous game's page -- always mounted (main.py), unlike
account_pages.py's router. Also holds the shared Jinja2Templates
instance account_pages.py imports, so there's exactly one templates
directory configured for the whole app.

The page itself lives at "/" in public mode (the default -- Party is
the only thing a visitor sees) and at "/party" when the account
system is also enabled, so it never collides with account_pages.py's
own home page at "/" in that mode -- see PARTY_LAUNCH_PLAN.md Part 1
sections 1 and 8. In public mode, "/party" (its old path) redirects
to "/" instead of 404ing.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from keystroke_dynamics.config import settings

router = APIRouter()

_templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

#: No inline *scripts* anywhere -- script-src has no 'unsafe-inline'
#: or 'unsafe-eval', and every script is self-hosted static/js (see
#: PARTY_LAUNCH_PLAN.md Part 1 section 8's literal requirement). The
#: page's dynamically-colored SVGs/layout tweaks (a player's ring
#: color, a swatch, an inline gap) use the `style` attribute the way
#: the approved mockup does, so style-src keeps 'unsafe-inline' --
#: inline presentation carries a fundamentally different risk from
#: inline script, which is what this CSP actually exists to stop.
_PARTY_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "form-action 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'"
)

#: "/" in public mode (where it's the only page); "/party" once the
#: account system's own home page is also mounted at "/".
PARTY_PATH = "/party" if settings.enable_accounts else "/"


@router.get(PARTY_PATH, response_class=HTMLResponse)
def party_page(request: Request) -> HTMLResponse:
    response = templates.TemplateResponse(
        request,
        "party.html",
        {"active_page": "party", "public_base_url": settings.public_base_url},
    )
    response.headers["Content-Security-Policy"] = _PARTY_CSP
    return response


if settings.debug:
    # Local-only (docs/plans/active/MOBILE_PLAN.md Phase 0): a page for checking what a
    # real phone's browser delivers for taps on the on-page keyboard.
    # Never registered -- not just rejected -- outside debug mode, same
    # as api/game.py's debug route. It has no backend: the page makes
    # no requests, so no tap data reaches the server.
    @router.get("/debug/touch-capture", response_class=HTMLResponse)
    def touch_capture_page(request: Request) -> HTMLResponse:
        response = templates.TemplateResponse(request, "touch_capture.html", {})
        response.headers["Content-Security-Policy"] = _PARTY_CSP
        return response


if PARTY_PATH == "/":
    # The game used to live at /party before public mode moved it to
    # "/" (its only page); redirect old links/bookmarks rather than
    # 404 them. Only registered in public mode -- when the account
    # system is also enabled, "/party" IS the real route above, not a
    # redirect target.
    @router.get("/party")
    def party_redirect() -> RedirectResponse:
        return RedirectResponse("/", status_code=308)
