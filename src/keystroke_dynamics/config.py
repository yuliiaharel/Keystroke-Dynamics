"""Application settings, loaded from the environment (and a .env file
in local development)."""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: The placeholders shipped in .env.example -- never real deployment
#: values. Same local-development-only status as _EXAMPLE_SESSION_SECRET
#: below: fine while debug=true, rejected outside it.
_EXAMPLE_SESSION_SECRET = "change-me"
_LOCAL_ALLOWED_ORIGIN = "http://127.0.0.1:8000"

#: DEPLOY.md's own bootstrap placeholder for the not-yet-known
#: *.ondigitalocean.app hostname (see its "First deploy" section) --
#: checked as a substring, not an exact match, since it appears
#: embedded in a full URL (https://REPLACE_ME.ondigitalocean.app), not
#: on its own.
_UNSET_URL_PLACEHOLDER = "REPLACE_ME"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+psycopg://localhost/keystroke_dynamics"
    session_secret: str = "change-me"
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 8000

    #: Whether the account system (register/login/profile routes, the
    #: old account-based pages, and Postgres) is mounted at all. False
    #: is the public-launch mode docs/plans/done/PARTY_LAUNCH_PLAN.md Part 1 adds: the
    #: app must start and a full game must be playable with no
    #: DATABASE_URL and no database connection whatsoever. The anonymous
    #: game (api/game.py) never depends on this flag either way -- it
    #: has its own in-memory store and never touches accounts or
    #: Postgres, in either mode.
    enable_accounts: bool = False

    #: Same-origin check for state-changing requests (CSRF defense;
    #: see api/security.py:require_matching_origin). The app serves no
    #: separate frontend origin, so this is simply where it itself is
    #: reachable.
    allowed_origin: str = "http://127.0.0.1:8000"

    #: The absolute, public HTTPS URL this app is reachable at once
    #: deployed -- used only for absolute URLs in link-preview metadata
    #: (Open Graph/Twitter tags, the preview image). Required outside
    #: local development, same as session_secret -- see the validator
    #: below.
    public_base_url: str | None = None

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

    #: In-memory game store limits (game/store.py) -- see
    #: docs/plans/done/PARTY_LAUNCH_PLAN.md Part 1 section 2. Same in-memory/per-process
    #: caveat as the rate limiters above: this is deliberately a
    #: single-worker app (see main.py's docstring on why).
    game_party_limit: int = 500
    game_players_per_party_limit: int = 12
    game_attempts_per_party_limit: int = 200
    game_idle_expiry_seconds: float = 2 * 60 * 60
    #: Separate from the account system's rate limiters (different
    #: endpoints, different abuse shape) but the same mechanism.
    game_rate_limit_max_attempts: int = 20
    game_rate_limit_window_seconds: float = 60.0

    #: docs/plans/done/PARTY_LAUNCH_PLAN.md section 10: a separate, optional database
    #: for opted-in score collection -- empty/None means collection is
    #: off and the game works normally with no opt-in shown at all.
    #: Deliberately independent of database_url/enable_accounts: the
    #: account system and score collection are two unrelated optional
    #: databases, either, both, or neither of which may be configured.
    scores_database_url: str | None = None
    #: Bounded in-memory queue between a request and the background
    #: batch writer (scores/writer.py) -- see that module for why a
    #: full queue drops rows rather than blocking.
    scores_queue_max_size: int = 1000
    #: How often the background writer drains the queue, and how long
    #: it waits for a mostly-empty queue to fill a bit before writing
    #: a small batch anyway.
    scores_writer_batch_interval_seconds: float = 2.0
    #: Delete score rows older than this many days (default ~12
    #: months) -- scores/retention.py's daily background task.
    scores_retention_days: int = 365

    @model_validator(mode="after")
    def _normalize_empty_scores_database_url(self) -> "Settings":
        # An empty string (e.g. SCORES_DATABASE_URL="" in an env file)
        # must mean "off", exactly like None -- every other check in
        # this module treats "falsy" and "unset" as the same thing.
        if self.scores_database_url == "":
            self.scores_database_url = None
        return self

    @model_validator(mode="after")
    def _require_real_deployment_settings_outside_local_development(self) -> "Settings":
        # debug doubles as "this is local development" elsewhere already
        # (see main.py's https_only=not settings.debug); reused here so
        # a deployment that forgets one of these fails loudly at startup
        # instead of silently running with a value anyone can read in
        # this repo's own .env.example, or with no absolute URL to build
        # link-preview metadata from at all (api/pages.py already
        # tolerates public_base_url=None, but only as a local-dev
        # fallback -- a real deployment should never actually hit it).
        if self.debug:
            return self
        problems = []
        if self.session_secret in ("", _EXAMPLE_SESSION_SECRET):
            problems.append(
                f"SESSION_SECRET is missing or still the .env.example placeholder "
                f"({_EXAMPLE_SESSION_SECRET!r})"
            )
        if self.allowed_origin in ("", _LOCAL_ALLOWED_ORIGIN):
            problems.append(
                f"ALLOWED_ORIGIN is missing or still the local-development default "
                f"({_LOCAL_ALLOWED_ORIGIN!r}) -- set it to this app's own public URL"
            )
        elif _UNSET_URL_PLACEHOLDER in self.allowed_origin:
            problems.append(
                f"ALLOWED_ORIGIN still contains the deploy-time placeholder "
                f"({_UNSET_URL_PLACEHOLDER!r}) -- see DEPLOY.md's first-deploy steps"
            )
        elif not self.allowed_origin.startswith("https://"):
            problems.append(
                f"ALLOWED_ORIGIN must be an https:// URL outside local development "
                f"(got {self.allowed_origin!r})"
            )
        if not self.public_base_url:
            problems.append("PUBLIC_BASE_URL is missing -- set it to this app's own public URL")
        elif _UNSET_URL_PLACEHOLDER in self.public_base_url:
            problems.append(
                f"PUBLIC_BASE_URL still contains the deploy-time placeholder "
                f"({_UNSET_URL_PLACEHOLDER!r}) -- see DEPLOY.md's first-deploy steps"
            )
        elif not self.public_base_url.startswith("https://"):
            problems.append(
                f"PUBLIC_BASE_URL must be an https:// URL outside local development "
                f"(got {self.public_base_url!r})"
            )
        if problems:
            raise ValueError(
                "; ".join(problems) + ". Set real values, or set DEBUG=true for local "
                "development only."
            )
        return self


settings = Settings()
