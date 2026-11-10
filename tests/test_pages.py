"""Smoke tests for the server-rendered pages -- catches template
errors (a bad {% %} tag, a missing block) that a 200-vs-500 check is
enough to surface; the frontend's own test suite covers behavior."""

import pytest
from fastapi.testclient import TestClient

PAGES = [
    "/",
    "/create-profile",
    "/authenticate",
    "/how-it-works",
    "/about",
    "/finish",
    "/party",
]


@pytest.mark.parametrize("path", PAGES)
def test_page_renders(client: TestClient, path: str) -> None:
    resp = client.get(path)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")


def test_pages_link_to_the_built_static_assets(client: TestClient) -> None:
    resp = client.get("/create-profile")
    assert "/static/js/create-profile.js" in resp.text
    assert "/static/css/styles.css" in resp.text

    resp = client.get("/authenticate")
    assert "/static/js/authenticate.js" in resp.text

    resp = client.get("/party")
    assert "/static/js/party.js" in resp.text
    assert "/static/css/party.css" in resp.text
    assert "/static/css/fonts.css" in resp.text
    assert "fonts.googleapis.com" not in resp.text
    assert "fonts.gstatic.com" not in resp.text


@pytest.mark.parametrize("code", ["ABCDEFGH", "abcd-efgh", "ZZZZZZZZ", "nonsense"])
def test_a_room_link_serves_the_game_page_whatever_the_code(client: TestClient, code: str) -> None:
    # No room exists for any of these. The page never looks a code up
    # (the join request does, behind its rate limit), so a GET can't
    # tell a real code from a made-up one.
    room_page = client.get(f"/r/{code}")
    assert room_page.status_code == 200
    assert room_page.text == client.get("/party").text
    assert "script-src 'self'" in room_page.headers["content-security-policy"]


def test_a_room_link_preview_is_the_home_pages_and_never_names_the_room(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # With a public base URL the page carries og: tags. A room link's
    # must be the home page's own, so a preview shows nothing about
    # the room, not even its code (ROOMS_PLAN.md Phase 3 section 3).
    monkeypatch.setattr(
        "keystroke_dynamics.api.pages.settings.public_base_url", "https://example.com"
    )
    room_page = client.get("/r/ABCD-EFGH")
    assert room_page.text == client.get("/party").text
    assert 'property="og:url" content="https://example.com/party"' in room_page.text
    assert "ABCD" not in room_page.text


def test_the_page_is_told_its_home_path(client: TestClient) -> None:
    # party.ts returns here when it leaves a room.
    assert '<body data-home="/party">' in client.get("/r/ABCDEFGH").text


def test_typing_twin_page_no_longer_exists(client: TestClient) -> None:
    # Removed entirely -- Party replaces it (docs/plans/done/PARTY_LAUNCH_PLAN.md).
    # Checked here, under the accounts-enabled suite, since that's
    # the only mode the old page was ever reachable in.
    assert client.get("/typing-twin").status_code == 404


def test_account_pages_nav_links_to_party_not_typing_twin(client: TestClient) -> None:
    resp = client.get("/")
    assert 'href="/party"' in resp.text
    assert "typing-twin" not in resp.text
    assert "Typing Twin" not in resp.text


def test_party_page_has_a_strict_csp_with_no_inline_scripts(client: TestClient) -> None:
    # style-src keeps 'unsafe-inline' (the page's dynamic ring colors
    # and layout tweaks use the style attribute, same as the approved
    # mockup) -- script-src is where "no inline scripts" actually
    # matters, and that one must stay clean.
    resp = client.get("/party")
    csp = resp.headers["content-security-policy"]
    assert "script-src 'self'" in csp
    for directive in csp.split(";"):
        if directive.strip().startswith("script-src"):
            assert "unsafe-inline" not in directive
            assert "unsafe-eval" not in directive


def test_party_page_has_no_og_tags_without_a_configured_public_base_url(
    client: TestClient,
) -> None:
    # No public_base_url (the default -- it's only set once actually
    # deployed) means no absolute URLs can be built, so these tags
    # are omitted rather than pointing at something broken.
    resp = client.get("/party")
    assert "og:url" not in resp.text
    assert "og:image" not in resp.text


def test_party_page_og_tags_use_absolute_urls_from_public_base_url(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "keystroke_dynamics.api.pages.settings.public_base_url", "https://example.com"
    )
    resp = client.get("/party")
    assert 'property="og:url" content="https://example.com/party"' in resp.text
    assert (
        'property="og:image" content="https://example.com/static/img/party-preview.png"'
        in resp.text
    )


def test_og_preview_image_exists_and_is_1200x630(client: TestClient) -> None:
    resp = client.get("/static/img/party-preview.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    # PNG IHDR: width/height are the 4-byte big-endian ints right
    # after the 8-byte signature + 4-byte length + "IHDR".
    width = int.from_bytes(resp.content[16:20], "big")
    height = int.from_bytes(resp.content[20:24], "big")
    assert (width, height) == (1200, 630)
