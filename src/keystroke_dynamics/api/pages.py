"""Server-rendered pages. GET-only, so none of these need the
Origin check that guards the state-changing /api/* routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()

_templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "home.html", {"active_page": "home"})


@router.get("/create-profile", response_class=HTMLResponse)
def create_profile_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "create_profile.html", {"active_page": "create-profile"}
    )


@router.get("/authenticate", response_class=HTMLResponse)
def authenticate_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "authenticate.html", {"active_page": "authenticate"})


@router.get("/how-it-works", response_class=HTMLResponse)
def how_it_works_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "how_it_works.html", {"active_page": "how-it-works"})


@router.get("/about", response_class=HTMLResponse)
def about_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "about.html", {"active_page": "about"})


@router.get("/finish", response_class=HTMLResponse)
def finish_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "finish.html", {"active_page": "finish"})
