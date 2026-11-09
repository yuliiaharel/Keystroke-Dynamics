"""Tests for the startup guard against missing/default deployment
settings -- Settings() must fail loudly rather than silently running
with a value anyone can read in this repo's own .env.example, or with
no real origin/public URL, outside local development."""

import pytest

from keystroke_dynamics.config import Settings

#: A full set of real-looking deployment values -- the baseline every
#: test below starts from and overrides one field at a time, so each
#: test isolates exactly the field it's named for.
_REAL_VALUES = {
    "debug": False,
    "session_secret": "a-real-production-secret",
    "allowed_origin": "https://typingtwin.example.com",
    "public_base_url": "https://typingtwin.example.com",
}


def test_allows_real_values_outside_debug() -> None:
    settings = Settings(**_REAL_VALUES)
    assert settings.session_secret == _REAL_VALUES["session_secret"]
    assert settings.allowed_origin == _REAL_VALUES["allowed_origin"]
    assert settings.public_base_url == _REAL_VALUES["public_base_url"]


def test_allows_every_placeholder_in_debug_mode() -> None:
    settings = Settings(
        debug=True, session_secret="change-me", allowed_origin="http://127.0.0.1:8000"
    )
    assert settings.session_secret == "change-me"
    assert settings.public_base_url is None


@pytest.mark.parametrize("secret", ["", "change-me"])
def test_refuses_to_start_without_a_real_session_secret_outside_debug(secret: str) -> None:
    with pytest.raises(ValueError, match="SESSION_SECRET"):
        Settings(**{**_REAL_VALUES, "session_secret": secret})


@pytest.mark.parametrize("origin", ["", "http://127.0.0.1:8000"])
def test_refuses_to_start_without_a_real_allowed_origin_outside_debug(origin: str) -> None:
    with pytest.raises(ValueError, match="ALLOWED_ORIGIN"):
        Settings(**{**_REAL_VALUES, "allowed_origin": origin})


@pytest.mark.parametrize("url", [None, ""])
def test_refuses_to_start_without_a_public_base_url_outside_debug(url: str | None) -> None:
    with pytest.raises(ValueError, match="PUBLIC_BASE_URL"):
        Settings(**{**_REAL_VALUES, "public_base_url": url})


def test_refuses_an_allowed_origin_still_containing_the_deploy_placeholder() -> None:
    # DEPLOY.md's own bootstrap step deliberately sets this during the
    # app's first deploy, before the real *.ondigitalocean.app
    # hostname is known -- startup must refuse to run with it left in
    # place rather than silently serving under a URL nobody owns.
    with pytest.raises(ValueError, match="ALLOWED_ORIGIN"):
        Settings(**{**_REAL_VALUES, "allowed_origin": "https://REPLACE_ME.ondigitalocean.app"})


def test_refuses_a_public_base_url_still_containing_the_deploy_placeholder() -> None:
    with pytest.raises(ValueError, match="PUBLIC_BASE_URL"):
        Settings(**{**_REAL_VALUES, "public_base_url": "https://REPLACE_ME.ondigitalocean.app"})


@pytest.mark.parametrize("origin", ["http://typingtwin.example.com", "typingtwin.example.com"])
def test_refuses_a_non_https_allowed_origin_outside_debug(origin: str) -> None:
    with pytest.raises(ValueError, match="ALLOWED_ORIGIN"):
        Settings(**{**_REAL_VALUES, "allowed_origin": origin})


@pytest.mark.parametrize("url", ["http://typingtwin.example.com", "typingtwin.example.com"])
def test_refuses_a_non_https_public_base_url_outside_debug(url: str) -> None:
    with pytest.raises(ValueError, match="PUBLIC_BASE_URL"):
        Settings(**{**_REAL_VALUES, "public_base_url": url})


def test_reports_every_missing_field_at_once() -> None:
    # A deployment that forgot everything should see everything it's
    # missing in one error, not one at a time across repeated restarts.
    with pytest.raises(ValueError) as exc_info:
        Settings(debug=False, session_secret="change-me", allowed_origin="http://127.0.0.1:8000")
    message = str(exc_info.value)
    assert "SESSION_SECRET" in message
    assert "ALLOWED_ORIGIN" in message
    assert "PUBLIC_BASE_URL" in message


# ---------- scores_database_url (docs/plans/done/PARTY_LAUNCH_PLAN.md section 10) ----------


def test_scores_database_url_defaults_to_off() -> None:
    assert Settings(**_REAL_VALUES).scores_database_url is None


def test_empty_scores_database_url_normalizes_to_none() -> None:
    # SCORES_DATABASE_URL="" in an env file must mean "off", exactly
    # like leaving it unset -- never a value Settings treats as "set
    # to the empty string".
    settings = Settings(**{**_REAL_VALUES, "scores_database_url": ""})
    assert settings.scores_database_url is None


def test_a_real_scores_database_url_is_kept() -> None:
    url = "postgresql+psycopg://user:pass@neon.example.com/scores"
    settings = Settings(**{**_REAL_VALUES, "scores_database_url": url})
    assert settings.scores_database_url == url
