import concurrent.futures

import pytest
from fastapi.testclient import TestClient


def test_register_creates_a_user(client: TestClient) -> None:
    resp = client.post(
        "/api/register", json={"username": "alice", "password": "correct-password-123"}
    )
    assert resp.status_code == 201


def test_register_duplicate_username_rejected(
    client: TestClient, registered_user: dict[str, str]
) -> None:
    resp = client.post("/api/register", json=registered_user)
    assert resp.status_code == 409


@pytest.mark.parametrize(
    "username",
    [
        "ab",  # too short
        "a" * 33,  # too long
        "has spaces",
        "has/slash",
        'x"); DROP TABLE users; --',
        "../../etc/passwd",
        "..\\..\\windows\\system32",
        "",
    ],
)
def test_register_rejects_invalid_usernames(client: TestClient, username: str) -> None:
    resp = client.post(
        "/api/register", json={"username": username, "password": "correct-password-123"}
    )
    assert resp.status_code == 422


@pytest.mark.parametrize("username", ["abc", "A_valid-Name99", "x" * 32])
def test_register_accepts_valid_usernames(client: TestClient, username: str) -> None:
    resp = client.post(
        "/api/register", json={"username": username, "password": "correct-password-123"}
    )
    assert resp.status_code == 201


def test_register_rejects_short_password(client: TestClient) -> None:
    resp = client.post("/api/register", json={"username": "alice", "password": "short"})
    assert resp.status_code == 422


def test_concurrent_registration_of_the_same_new_username_gets_one_201_and_409s(
    client: TestClient,
) -> None:
    # Phase 7 review finding: the exists-check and the insert aren't
    # atomic, so two concurrent registrations for the same brand-new
    # username can both pass the check and race on the unique
    # constraint. Before the fix, the loser's IntegrityError was
    # uncaught -- a 500, not a clean 409.
    n = 10
    body = {"username": "raceuser", "password": "correct-password-123"}

    def attempt() -> int:
        return client.post("/api/register", json=body).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(lambda _: attempt(), range(n)))

    assert results.count(201) == 1
    assert results.count(409) == n - 1
