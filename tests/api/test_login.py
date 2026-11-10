from fastapi.testclient import TestClient


def test_login_with_correct_password_succeeds(
    client: TestClient, registered_user: dict[str, str]
) -> None:
    resp = client.post("/api/login", json=registered_user)
    assert resp.status_code == 200
    assert resp.json() == {"typing_result": None}


def test_login_unknown_user_and_wrong_password_are_identical(
    client: TestClient, registered_user: dict[str, str]
) -> None:
    wrong_password = client.post(
        "/api/login", json={"username": registered_user["username"], "password": "wrong"}
    )
    unknown_user = client.post("/api/login", json={"username": "no-such-user", "password": "wrong"})

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()


def test_login_session_cookie_is_httponly_and_samesite_lax(
    client: TestClient, registered_user: dict[str, str]
) -> None:
    resp = client.post("/api/login", json=registered_user)
    set_cookie = resp.headers.get("set-cookie", "")
    assert "httponly" in set_cookie.lower()
    assert "samesite=lax" in set_cookie.lower()


def test_login_session_cookie_has_no_secure_flag_in_debug_mode(
    client: TestClient, registered_user: dict[str, str]
) -> None:
    # The test environment runs with DEBUG=true (see conftest.py), so
    # https_only should be False -- matching main.py's
    # https_only=not settings.debug wiring, verified behaviorally here
    # rather than by reaching into the middleware's internals.
    resp = client.post("/api/login", json=registered_user)
    set_cookie = resp.headers.get("set-cookie", "")
    assert "secure" not in set_cookie.lower()


def test_login_establishes_a_working_session(
    client: TestClient, registered_user: dict[str, str]
) -> None:
    client.post("/api/login", json=registered_user)
    resp = client.post("/api/profile/samples", json={"events": []})
    assert resp.status_code == 200


def test_login_with_sample_returns_typing_result_without_failing_login(
    client: TestClient, registered_user: dict[str, str]
) -> None:
    # No profile exists yet, so the sample can't be scored -- but that
    # must never fail the login itself (a failed/absent typing check
    # is only a signal, not a login gate).
    sample = [
        {"code": "KeyA", "action": "down", "t_ms": 0},
        {"code": "KeyA", "action": "up", "t_ms": 90},
    ]
    resp = client.post("/api/login", json={**registered_user, "sample": sample})
    assert resp.status_code == 200
    assert resp.json()["typing_result"]["decision"] == "insufficient_data"


def test_repeated_bad_typing_samples_never_lock_the_account(
    client: TestClient, registered_user: dict[str, str]
) -> None:
    sample = [
        {"code": "KeyA", "action": "down", "t_ms": 0},
        {"code": "KeyA", "action": "up", "t_ms": 90},
    ]
    for _ in range(5):
        resp = client.post("/api/login", json={**registered_user, "sample": sample})
        assert resp.status_code == 200


def test_logout_clears_the_session(client: TestClient, registered_user: dict[str, str]) -> None:
    client.post("/api/login", json=registered_user)
    assert client.post("/api/profile/samples", json={"events": []}).status_code == 200

    resp = client.post("/api/logout")
    assert resp.status_code == 204

    resp = client.post("/api/profile/samples", json={"events": []})
    assert resp.status_code == 401


def test_no_username_availability_endpoint_exists(client: TestClient) -> None:
    """The old app's is_in_DB check (probe whether a username exists,
    with no credential at all) has no equivalent here."""
    paths = set(client.app.openapi()["paths"].keys())
    assert paths == {
        "/health",
        "/api/register",
        "/api/login",
        "/api/logout",
        "/api/profile/samples",
        "/api/profile/verify",
        "/api/profile",
        "/",
        "/create-profile",
        "/authenticate",
        "/how-it-works",
        "/about",
        "/finish",
        "/party",
        "/api/game/party",
        "/api/game/party/reset",
        "/api/game/rooms",
        "/api/game/rooms/{code}/join",
        "/api/game/rooms/leave",
        "/api/game/room",
        "/api/game/room/lock",
        "/api/game/room/name-suggestion",
        "/api/game/room/events",
        "/api/game/room/end",
        "/api/game/room/players/{player_id}",
        "/api/game/room/members/{member_id}",
        "/r/{code}",
        "/api/game/players",
        "/api/game/players/{player_id}",
        "/api/game/attempts",
        "/api/game/replay",
        "/api/game/debug/record-target",
    }
