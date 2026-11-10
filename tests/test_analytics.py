"""Visitor counting (docs/plans/active/ANALYTICS_PLAN.md): the
GoatCounter snippet and the Content-Security-Policy sources it needs
appear only when GOATCOUNTER_SITE_CODE is set, and the page never
gives GoatCounter a way to learn a room code.

What the browser actually sends is covered by the frontend's own
tests (frontend/src/analytics.test.ts and frontend/e2e-analytics/).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from keystroke_dynamics.api.analytics import csp_with_analytics
from keystroke_dynamics.api.pages import _PARTY_CSP
from keystroke_dynamics.config import Settings, settings

SITE_CODE = "example-site"


@pytest.fixture
def analytics_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "goatcounter_site_code", SITE_CODE)


def _directive(csp: str, name: str) -> str:
    matches = [part.strip() for part in csp.split(";") if part.strip().split(" ")[0] == name]
    assert len(matches) == 1, csp
    return matches[0]


def test_analytics_is_off_by_default() -> None:
    assert Settings(debug=True).goatcounter_site_code == ""


def test_the_script_tag_is_absent_when_the_site_code_is_empty(client: TestClient) -> None:
    assert settings.goatcounter_site_code == ""
    resp = client.get("/party")
    assert resp.status_code == 200
    assert "goatcounter" not in resp.text.lower()
    assert "gc.zgo.at" not in resp.text
    # And the policy would block the request even if a tag appeared.
    assert resp.headers["content-security-policy"] == _PARTY_CSP
    assert "goatcounter" not in _PARTY_CSP
    assert "gc.zgo.at" not in _PARTY_CSP


@pytest.mark.usefixtures("analytics_on")
def test_the_script_tag_is_present_when_the_site_code_is_set(client: TestClient) -> None:
    resp = client.get("/party")
    assert resp.status_code == 200
    assert (
        f'<script data-goatcounter="https://{SITE_CODE}.goatcounter.com/count" '
        """data-goatcounter-settings='{"no_onload": true}' """
        'async src="https://gc.zgo.at/count.js"></script>'
    ) in resp.text
    assert resp.text.count("data-goatcounter=") == 1


@pytest.mark.usefixtures("analytics_on")
def test_the_csp_allows_only_what_the_snippet_needs(client: TestClient) -> None:
    csp = client.get("/party").headers["content-security-policy"]
    assert _directive(csp, "script-src") == "script-src 'self' https://gc.zgo.at"
    assert _directive(csp, "connect-src") == (
        f"connect-src 'self' https://{SITE_CODE}.goatcounter.com"
    )
    # Every other directive is exactly what it is with analytics off.
    untouched = {"script-src", "connect-src"}
    assert [d.strip() for d in csp.split(";") if d.strip().split(" ")[0] not in untouched] == [
        d.strip() for d in _PARTY_CSP.split(";") if d.strip().split(" ")[0] not in untouched
    ]
    assert "unsafe-inline" not in _directive(csp, "script-src")


def test_csp_with_analytics_refuses_a_policy_it_cannot_extend() -> None:
    with pytest.raises(ValueError, match="connect-src"):
        csp_with_analytics("default-src 'self'; script-src 'self'", SITE_CODE)


@pytest.mark.parametrize("site_code", ["", SITE_CODE])
def test_the_page_sets_a_referrer_policy(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, site_code: str
) -> None:
    # Off or on: a room link is never sent to another site as a referrer.
    monkeypatch.setattr(settings, "goatcounter_site_code", site_code)
    resp = client.get("/party")
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"


@pytest.mark.usefixtures("analytics_on")
def test_the_page_has_a_generic_title_and_no_canonical_link(client: TestClient) -> None:
    # count.js prefers a canonical URL over the path, and sends the
    # title along. Neither may ever carry a room code.
    resp = client.get("/party")
    assert "<title>Typing Twin Party</title>" in resp.text
    assert 'rel="canonical"' not in resp.text


@pytest.mark.parametrize(
    "site_code",
    ["Example", "a.b", "a b", "a/b", "x.goatcounter.com", "a;script-src *", 'a"onload="x', "a\nb"],
)
def test_refuses_a_site_code_that_is_not_a_hostname_label(site_code: str) -> None:
    with pytest.raises(ValidationError, match="goatcounter_site_code"):
        Settings(debug=True, goatcounter_site_code=site_code)


@pytest.mark.parametrize("site_code", ["yuliia", "typing-twin", "site2"])
def test_accepts_a_real_looking_site_code(site_code: str) -> None:
    assert Settings(debug=True, goatcounter_site_code=site_code).goatcounter_site_code == site_code
