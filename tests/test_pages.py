"""Smoke tests for the server-rendered pages -- catches template
errors (a bad {% %} tag, a missing block) that a 200-vs-500 check is
enough to surface; the frontend's own test suite covers behavior."""

import pytest
from fastapi.testclient import TestClient

PAGES = ["/", "/create-profile", "/authenticate", "/how-it-works", "/about", "/finish"]


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
