"""The anonymous game's page -- always mounted (main.py), unlike
account_pages.py's router. Also holds the shared Jinja2Templates
instance account_pages.py imports, so there's exactly one templates
directory configured for the whole app.

The page itself lives at "/" in public mode (the default) and at
"/party" when the account system is also enabled, so it never
collides with account_pages.py's own home page at "/" in that mode --
see PARTY_LAUNCH_PLAN.md Part 1 sections 1 and 8.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from keystroke_dynamics.config import settings

router = APIRouter()

_templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

#: No inline scripts or styles anywhere on this page -- everything is
#: self-hosted static/js and static/css -- so this has no 'unsafe-
#: inline' anywhere, and nothing but this app's own origin is allowed
#: for anything. See PARTY_LAUNCH_PLAN.md Part 1 section 8.
_PARTY_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
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
