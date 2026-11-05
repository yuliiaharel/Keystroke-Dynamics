"""The anonymous game's page(s) -- always mounted (main.py), unlike
account_pages.py's router. Also holds the shared Jinja2Templates
instance account_pages.py imports, so there's exactly one templates
directory configured for the whole app.

No route is registered here yet: the actual page (porting
design/typing-twin-party.html to this app's Jinja/TS setup, per
PARTY_LAUNCH_PLAN.md Part 1 section 8) hasn't been built. That's
separate, substantial frontend work, not yet started -- see this
session's own status notes rather than assuming it's done because
the backend (api/game.py) is.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.templating import Jinja2Templates

router = APIRouter()

_templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))
