import concurrent.futures

import pytest
from fastapi.testclient import TestClient

SAMPLE = {
    "events": [
        {"code": "Period", "action": "down", "t_ms": 0},
        {"code": "Period", "action": "up", "t_ms": 90},
        {"code": "KeyT", "action": "down", "t_ms": 180},
        {"code": "KeyT", "action": "up", "t_ms": 260},
        {"code": "KeyI", "action": "down", "t_ms": 350},
        {"code": "KeyI", "action": "up", "t_ms": 420},
    ]
}


@pytest.mark.parametrize(
    ("method", "path"),
    [("post", "/api/profile/samples"), ("post", "/api/profile/verify"), ("delete", "/api/profile")],
)
def test_profile_endpoints_require_authentication(
    client: TestClient, method: str, path: str
) -> None:
    resp = (
        getattr(client, method)(path, json={"events": []})
        if method == "post"
        else client.delete(path)
    )
    assert resp.status_code == 401


def test_add_sample_increments_count(logged_in_client: TestClient) -> None:
    resp = logged_in_client.post("/api/profile/samples", json=SAMPLE)
    assert resp.status_code == 200
    assert resp.json() == {"sample_count": 1}

    resp = logged_in_client.post("/api/profile/samples", json=SAMPLE)
    assert resp.json() == {"sample_count": 2}


def test_verify_with_no_profile_is_insufficient_data(logged_in_client: TestClient) -> None:
    resp = logged_in_client.post("/api/profile/verify", json=SAMPLE)
    assert resp.status_code == 200
    assert resp.json()["decision"] == "insufficient_data"


def test_delete_profile_removes_it(logged_in_client: TestClient) -> None:
    logged_in_client.post("/api/profile/samples", json=SAMPLE)

    resp = logged_in_client.delete("/api/profile")
    assert resp.status_code == 204

    # Deleting again (nothing to delete) is still fine, not an error.
    resp = logged_in_client.delete("/api/profile")
    assert resp.status_code == 204

    # And a fresh sample starts a brand new profile from zero.
    resp = logged_in_client.post("/api/profile/samples", json=SAMPLE)
    assert resp.json() == {"sample_count": 1}


def test_malformed_sample_rejected(logged_in_client: TestClient) -> None:
    bad = {
        "events": [
            {"code": "KeyA", "action": "down", "t_ms": 100},
            {"code": "KeyA", "action": "up", "t_ms": 50},  # time goes backward
        ]
    }
    resp = logged_in_client.post("/api/profile/verify", json=bad)
    assert resp.status_code == 400


def test_too_many_events_rejected(logged_in_client: TestClient) -> None:
    events = [
        {"code": "KeyA", "action": "down" if i % 2 == 0 else "up", "t_ms": float(i)}
        for i in range(2001)
    ]
    resp = logged_in_client.post("/api/profile/verify", json={"events": events})
    assert resp.status_code == 400


def test_user_cannot_access_another_users_profile(client: TestClient) -> None:
    client.post("/api/register", json={"username": "alice", "password": "correct-password-123"})
    client.post("/api/register", json={"username": "bob", "password": "correct-password-456"})

    client.post("/api/login", json={"username": "bob", "password": "correct-password-456"})
    client.post("/api/profile/samples", json=SAMPLE)
    client.post("/api/logout")

    client.post("/api/login", json={"username": "alice", "password": "correct-password-123"})
    # Alice's own actions must never reach bob's profile: there's no
    # field anywhere in these requests that could even name bob, so
    # this is really confirming the user is derived only from the
    # session, never from anything in the request.
    alice_delete = client.delete("/api/profile")
    assert alice_delete.status_code == 204  # alice's own (empty) profile
    client.post("/api/logout")

    # bob's profile must be untouched by any of alice's calls: one
    # more upload should land at exactly 2 (the 1 from before alice,
    # plus this one) -- not reset, not deleted, not shared.
    client.post("/api/login", json={"username": "bob", "password": "correct-password-456"})
    bob_samples = client.post("/api/profile/samples", json=SAMPLE)
    assert bob_samples.json()["sample_count"] == 2


def test_concurrent_sample_uploads_keep_correct_count(logged_in_client: TestClient) -> None:
    """core/db/repository.py locks the profile row for the duration of
    each upload's transaction specifically so this can't lose an
    update."""
    logged_in_client.post("/api/profile/samples", json=SAMPLE)  # profile already exists

    n = 20

    def upload() -> int:
        resp = logged_in_client.post("/api/profile/samples", json=SAMPLE)
        assert resp.status_code == 200
        return int(resp.json()["sample_count"])

    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(lambda _: upload(), range(n)))

    assert sorted(results) == list(range(2, n + 2))  # 1 was already there; no duplicates, no gaps


def test_concurrent_first_uploads_for_a_new_user_keep_correct_count(
    client: TestClient,
) -> None:
    """The profile row doesn't exist yet when this starts -- exercises
    the create-or-lock race in save_sample_features, not just the
    already-exists path the test above covers."""
    client.post("/api/register", json={"username": "carol", "password": "correct-password-789"})
    client.post("/api/login", json={"username": "carol", "password": "correct-password-789"})

    n = 20

    def upload() -> int:
        resp = client.post("/api/profile/samples", json=SAMPLE)
        assert resp.status_code == 200
        return int(resp.json()["sample_count"])

    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(lambda _: upload(), range(n)))

    assert sorted(results) == list(range(1, n + 1))
