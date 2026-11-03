"""Application settings, loaded from the environment (and a .env file
in local development)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+psycopg://localhost/keystroke_dynamics"
    session_secret: str = "change-me"
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 8000

    #: Same-origin check for state-changing requests (CSRF defense;
    #: see api/deps.py:require_matching_origin). The app serves no
    #: separate frontend origin, so this is simply where it itself is
    #: reachable.
    allowed_origin: str = "http://127.0.0.1:8000"

    #: Request body / event-count limits (core.events.validate takes
    #: max_events directly; max_body_bytes is enforced by middleware
    #: before the body is even parsed).
    max_body_bytes: int = 100_000
    max_events: int = 2000

    #: In-memory, per-process rate limiting for login, registration,
    #: and verification (api/rate_limit.py). Documented limitation:
    #: resets on restart and does not share state across processes --
    #: fine for one instance, not a real multi-process guarantee.
    rate_limit_max_attempts: int = 10
    rate_limit_window_seconds: float = 60.0


settings = Settings()
