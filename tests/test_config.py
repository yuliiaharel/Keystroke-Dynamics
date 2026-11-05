"""Tests for the startup guard against a missing/default session
secret -- Settings() must fail loudly rather than silently signing
sessions with the example secret outside local development."""

import pytest

from keystroke_dynamics.config import Settings


@pytest.mark.parametrize("secret", ["", "change-me"])
def test_refuses_to_start_without_a_real_secret_outside_debug(secret: str) -> None:
    with pytest.raises(ValueError, match="SESSION_SECRET"):
        Settings(debug=False, session_secret=secret)


def test_allows_the_example_secret_in_debug_mode() -> None:
    settings = Settings(debug=True, session_secret="change-me")
    assert settings.session_secret == "change-me"


def test_allows_a_real_secret_outside_debug() -> None:
    settings = Settings(debug=False, session_secret="a-real-production-secret")
    assert settings.session_secret == "a-real-production-secret"
