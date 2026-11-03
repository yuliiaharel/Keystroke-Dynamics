import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from keystroke_dynamics.api import deps
from keystroke_dynamics.db.models import ProfileFeature, User
from keystroke_dynamics.main import app

STATE_CHANGING_REQUESTS = [
    ("post", "/api/register", {"username": "someone", "password": "correct-password-123"}),
    ("post", "/api/login", {"username": "alice", "password": "correct-password-123"}),
    ("post", "/api/logout", None),
    ("post", "/api/profile/samples", {"events": []}),
    ("post", "/api/profile/verify", {"events": []}),
    ("delete", "/api/profile", None),
]


def _call(c: TestClient, method: str, path: str, body: dict | None):
    fn = getattr(c, method)
    return fn(path, json=body) if body is not None else fn(path)


@pytest.mark.parametrize(("method", "path", "body"), STATE_CHANGING_REQUESTS)
def test_missing_origin_is_rejected(
    method: str, path: str, body: dict | None, registered_user: dict[str, str]
) -> None:
    # A fresh client with no default Origin header -- unlike the
    # `client` fixture, which always sends one.
    with TestClient(app) as bare_client:
        resp = _call(bare_client, method, path, body)
        assert resp.status_code == 403


@pytest.mark.parametrize(("method", "path", "body"), STATE_CHANGING_REQUESTS)
def test_mismatched_origin_is_rejected(
    method: str, path: str, body: dict | None, registered_user: dict[str, str]
) -> None:
    with TestClient(app, headers={"origin": "http://evil.example"}) as evil_client:
        resp = _call(evil_client, method, path, body)
        assert resp.status_code == 403


def test_matching_origin_is_not_a_cors_response(client: TestClient) -> None:
    """No CORS middleware: even a same-origin response carries no
    Access-Control-* headers, because none are ever set."""
    resp = client.post(
        "/api/register", json={"username": "someone", "password": "correct-password-123"}
    )
    assert not any(h.lower().startswith("access-control-") for h in resp.headers)


def test_cross_origin_request_gets_no_cors_headers_either() -> None:
    with TestClient(app, headers={"origin": "http://evil.example"}) as evil_client:
        resp = evil_client.post("/api/register", json={"username": "x", "password": "y"})
        assert not any(h.lower().startswith("access-control-") for h in resp.headers)


def test_no_cors_middleware_is_configured() -> None:
    middleware_classes = [m.cls.__name__ for m in app.user_middleware]
    assert "CORSMiddleware" not in middleware_classes


def test_oversized_request_body_is_rejected(logged_in_client: TestClient) -> None:
    huge_code = "x" * 200_000  # well past settings.max_body_bytes (100_000)
    resp = logged_in_client.post(
        "/api/profile/verify",
        json={"events": [{"code": huge_code, "action": "down", "t_ms": 0}]},
    )
    assert resp.status_code == 413


@pytest.mark.parametrize(
    "username",
    [
        'x"); DROP TABLE users; --',
        "' OR '1'='1",
        "../../etc/passwd",
        "..\\..\\windows\\system32\\config",
        "/etc/shadow",
    ],
)
def test_sql_injection_and_path_traversal_usernames_rejected_db_intact(
    client: TestClient, username: str, db_session: Session
) -> None:
    resp = client.post(
        "/api/register", json={"username": username, "password": "correct-password-123"}
    )
    assert resp.status_code == 422  # rejected before ever reaching a query

    # The users table must still exist, with no row created for it.
    assert inspect(db_session.bind).has_table("users")
    assert db_session.scalar(select(User).where(User.username == username)) is None


def test_no_raw_events_reach_the_database(
    logged_in_client: TestClient, db_session: Session
) -> None:
    """profile_features legitimately stores *which* key a statistic is
    for (key_a/key_b) -- that's the feature's identity, not raw event
    data. What must never appear is the sample's actual timestamps:
    only a derived statistic (count/mean/m2) survives, never the raw
    12345/12399 this hold's duration (54ms) was computed from.
    """
    raw_t_ms_down, raw_t_ms_up = 12345.0, 12399.0
    sample = {
        "events": [
            {"code": "VeryDistinctiveKeyCodeForThisTest", "action": "down", "t_ms": raw_t_ms_down},
            {"code": "VeryDistinctiveKeyCodeForThisTest", "action": "up", "t_ms": raw_t_ms_up},
        ]
    }
    logged_in_client.post("/api/profile/samples", json=sample)

    rows = db_session.scalars(select(ProfileFeature)).all()
    assert len(rows) > 0

    hold_row = next(r for r in rows if r.kind == "hold")
    assert hold_row.key_a == "VeryDistinctiveKeyCodeForThisTest"  # the feature's identity: fine
    assert hold_row.mean == pytest.approx(raw_t_ms_up - raw_t_ms_down)  # the derived duration: fine

    # Neither raw timestamp survives anywhere, in any numeric column,
    # on any row -- only the derived duration above does.
    for row in rows:
        for column in inspect(row).mapper.column_attrs:
            value = getattr(row, column.key)
            if isinstance(value, int | float):
                assert value not in (raw_t_ms_down, raw_t_ms_up)

    # And structurally: no column anywhere could hold a raw event list
    # or request body in the first place (no JSON/text blob column).
    column_names = {c.key for c in inspect(ProfileFeature).mapper.column_attrs}
    assert column_names == {"id", "profile_id", "kind", "key_a", "key_b", "count", "mean", "m2"}


def test_no_raw_events_are_logged(
    logged_in_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    telltale_code = "VeryDistinctiveKeyCodeForLoggingTest"
    sample = {
        "events": [
            {"code": telltale_code, "action": "down", "t_ms": 54321},
            {"code": telltale_code, "action": "up", "t_ms": 54399},
        ]
    }
    with caplog.at_level(logging.DEBUG):
        logged_in_client.post("/api/profile/samples", json=sample)

    for record in caplog.records:
        assert telltale_code not in record.getMessage()


@pytest.mark.parametrize(
    ("path", "limiter_name", "body"),
    [
        ("/api/login", "login_rate_limiter", {"username": "x", "password": "y"}),
        ("/api/register", "register_rate_limiter", {"username": "x", "password": "y"}),
        ("/api/profile/verify", "verify_rate_limiter", {"events": []}),
    ],
)
def test_rate_limit_applies_to_sensitive_endpoints(
    client: TestClient, path: str, limiter_name: str, body: dict
) -> None:
    limiter = getattr(deps, limiter_name)
    for _ in range(limiter.max_attempts):
        client.post(path, json=body)

    over_limit = client.post(path, json=body)
    assert over_limit.status_code == 429
