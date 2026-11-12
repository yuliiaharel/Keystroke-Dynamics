"""/api/game rooms (docs/plans/active/ROOMS_PLAN.md Phase 1): creating,
joining, leaving, locking, ending, expiry, who may do what to whose
player, and the join-by-code safety rules. Each "browser" here is its
own TestClient, so its own session cookie and its own room member.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from keystroke_dynamics.api import game as game_api
from keystroke_dynamics.game.codes import CODE_ALPHABET, CODE_LENGTH
from keystroke_dynamics.game.rate_limit import game_join_rate_limiter
from keystroke_dynamics.game.store import InMemoryGameStore
from keystroke_dynamics.main import app
from tests.api.test_game import SENTENCE_LINE

ORIGIN = {"origin": "http://testserver"}


@pytest.fixture
def host() -> Iterator[TestClient]:
    with TestClient(app, headers=ORIGIN) as c:
        yield c


@pytest.fixture
def friend() -> Iterator[TestClient]:
    with TestClient(app, headers=ORIGIN) as c:
        yield c


@pytest.fixture
def stranger() -> Iterator[TestClient]:
    with TestClient(app, headers=ORIGIN) as c:
        yield c


def _use_store(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> None:
    settings: dict[str, object] = {
        "party_limit": 500,
        "players_per_party_limit": 12,
        "attempts_per_party_limit": 200,
        "idle_expiry_seconds": 7200.0,
        "members_per_party_limit": 12,
    }
    settings.update(overrides)
    monkeypatch.setattr(game_api, "_store", InMemoryGameStore(**settings))  # type: ignore[arg-type]


def _create_room(client: TestClient) -> dict:
    resp = client.post("/api/game/rooms", json={"level": "sentence"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _join(client: TestClient, code: str, **body: object) -> dict:
    resp = client.post(f"/api/game/rooms/{code}/join", json=body or None)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _enroll(client: TestClient, name: str) -> dict:
    resp = client.post(
        "/api/game/players", json={"name": name, "training_lines": [SENTENCE_LINE] * 5}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _attempt(
    client: TestClient, *, typist_id: str | None, target_id: str, attempt_id: str = "a1"
) -> object:
    return client.post(
        "/api/game/attempts",
        json={
            "typist_id": typist_id,
            "target_id": target_id,
            "mode": "attack",
            "events": SENTENCE_LINE,
            "client_attempt_id": attempt_id,
        },
    )


def _room(client: TestClient) -> dict:
    resp = client.get("/api/game/room")
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------- creating ----------


def test_creating_a_room_makes_you_its_host_and_only_member(host: TestClient) -> None:
    room = _create_room(host)
    assert room["is_host"] is True
    assert room["member_count"] == 1
    assert room["locked"] is False
    assert room["players"] == []
    assert room["member_id"]
    assert _room(host)["id"] == room["id"]


def test_room_code_is_eight_characters_from_the_unambiguous_alphabet(host: TestClient) -> None:
    code = _create_room(host)["code"]
    assert len(code) == CODE_LENGTH
    assert set(code) <= set(CODE_ALPHABET)


def test_the_old_party_paths_still_answer_for_the_current_frontend(host: TestClient) -> None:
    created = host.post("/api/game/party", json={"level": "sentence"}).json()
    assert host.get("/api/game/party").json()["id"] == created["id"]
    assert _room(host)["id"] == created["id"]
    assert host.post("/api/game/party/reset").status_code == 204
    assert host.get("/api/game/room").status_code == 404


def test_creating_a_second_room_leaves_the_first(host: TestClient, friend: TestClient) -> None:
    first = _create_room(host)
    _join(friend, first["code"])
    second = _create_room(host)
    assert second["id"] != first["id"]
    assert _room(host)["id"] == second["id"]
    # The first room goes on without its old host.
    left_behind = _room(friend)
    assert left_behind["member_count"] == 1
    assert left_behind["is_host"] is True


# ---------- joining ----------


def test_joining_by_code_puts_a_second_browser_in_the_same_room(
    host: TestClient, friend: TestClient
) -> None:
    room = _create_room(host)
    joined = _join(friend, room["code"])
    assert joined["id"] == room["id"]
    assert joined["is_host"] is False
    assert joined["member_id"] != room["member_id"]
    assert _room(host)["member_count"] == 2


@pytest.mark.parametrize(
    "spell",
    [
        lambda code: code.lower(),
        lambda code: f"{code[:4]}-{code[4:]}",
        lambda code: f"{code[:4].lower()}-{code[4:].lower()}",
        lambda code: f" {code[:4]} {code[4:]} ",
    ],
    ids=["lowercase", "dashed", "lowercase-dashed", "spaced"],
)
def test_join_accepts_any_spelling_of_the_code(host: TestClient, friend: TestClient, spell) -> None:
    room = _create_room(host)
    assert _join(friend, spell(room["code"]))["id"] == room["id"]


def test_rejoining_your_own_room_does_not_add_a_member(host: TestClient) -> None:
    room = _create_room(host)
    again = _join(host, room["code"])
    assert again["member_id"] == room["member_id"]
    assert again["member_count"] == 1
    assert again["is_host"] is True


def test_joining_a_second_room_needs_an_explicit_leave(
    host: TestClient, friend: TestClient
) -> None:
    first = _create_room(host)
    second = _create_room(friend)

    refused = host.post(f"/api/game/rooms/{second['code']}/join")
    assert refused.status_code == 409
    assert _room(host)["id"] == first["id"]  # still where they were

    moved = _join(host, second["code"], leave_current=True)
    assert moved["id"] == second["id"]
    assert _room(host)["id"] == second["id"]


def test_a_bad_code_never_costs_you_the_room_you_are_in(host: TestClient) -> None:
    room = _create_room(host)
    resp = host.post("/api/game/rooms/ZZZZZZZZ/join", json={"leave_current": True})
    assert resp.status_code == 404
    assert _room(host)["id"] == room["id"]


def test_one_browser_cannot_see_a_room_it_has_not_joined(
    host: TestClient, stranger: TestClient
) -> None:
    _create_room(host)
    assert stranger.get("/api/game/room").status_code == 404


# ---------- unknown, ended, and expired codes look the same ----------


def test_unknown_ended_expired_and_malformed_codes_get_identical_responses(
    host: TestClient, friend: TestClient, stranger: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_store(monkeypatch, idle_expiry_seconds=0.05)

    ended_code = _create_room(host)["code"]
    assert host.post("/api/game/room/end").status_code == 204

    expired_code = _create_room(friend)["code"]
    time.sleep(0.1)

    unknown_code = "ZZZZZZZZ"
    assert unknown_code not in (ended_code, expired_code)

    responses = [
        stranger.post(f"/api/game/rooms/{code}/join")
        for code in (unknown_code, ended_code, expired_code, "not-a-code", "ABCD-EFG1")
    ]
    assert {r.status_code for r in responses} == {404}
    assert len({r.content for r in responses}) == 1
    assert responses[0].json() == {"detail": "room not found"}


# ---------- join rate limiting ----------


def test_join_attempts_are_rate_limited_per_client(
    stranger: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Well under the general game limiter (20), so a 429 here can only
    # be the join limiter's own.
    monkeypatch.setattr(game_join_rate_limiter, "max_attempts", 3)
    for _ in range(3):
        assert stranger.post("/api/game/rooms/ZZZZZZZZ/join").status_code == 404
    assert stranger.post("/api/game/rooms/ZZZZZZZZ/join").status_code == 429


def test_a_rate_limited_join_is_refused_even_for_a_real_code(
    host: TestClient, stranger: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Guessing can't be "paid off" by finally hitting a live code.
    monkeypatch.setattr(game_join_rate_limiter, "max_attempts", 2)
    code = _create_room(host)["code"]
    for _ in range(2):
        stranger.post("/api/game/rooms/ZZZZZZZZ/join")
    assert stranger.post(f"/api/game/rooms/{code}/join").status_code == 429
    assert _room(host)["member_count"] == 1


def test_other_game_requests_do_not_spend_the_join_budget(
    host: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(game_join_rate_limiter, "max_attempts", 1)
    for _ in range(3):
        _create_room(host)
    host.post("/api/game/rooms/leave")
    assert host.post("/api/game/rooms/ZZZZZZZZ/join").status_code == 404


# ---------- locking ----------


def test_a_locked_room_refuses_new_joiners_with_a_clear_message(
    host: TestClient, friend: TestClient, stranger: TestClient
) -> None:
    room = _create_room(host)
    _join(friend, room["code"])

    locked = host.post("/api/game/room/lock", json={"locked": True})
    assert locked.status_code == 200
    assert locked.json()["locked"] is True

    refused = stranger.post(f"/api/game/rooms/{room['code']}/join")
    assert refused.status_code == 423
    assert "locked" in refused.json()["detail"]
    # Someone already inside is unaffected.
    assert _room(friend)["locked"] is True

    assert host.post("/api/game/room/lock", json={"locked": False}).json()["locked"] is False
    assert _join(stranger, room["code"])["id"] == room["id"]


def test_only_the_host_can_lock(host: TestClient, friend: TestClient) -> None:
    room = _create_room(host)
    _join(friend, room["code"])
    assert friend.post("/api/game/room/lock", json={"locked": True}).status_code == 403
    assert _room(host)["locked"] is False


# ---------- leaving ----------


def test_leaving_removes_your_players_and_your_access(host: TestClient, friend: TestClient) -> None:
    room = _create_room(host)
    _join(friend, room["code"])
    _enroll(host, "Alice")
    _enroll(friend, "Bob")

    assert friend.post("/api/game/rooms/leave").status_code == 204
    assert friend.get("/api/game/room").status_code == 404

    after = _room(host)
    assert after["member_count"] == 1
    assert [p["name"] for p in after["players"]] == ["Alice"]


def test_when_the_host_leaves_the_longest_standing_member_becomes_host(
    host: TestClient, friend: TestClient, stranger: TestClient
) -> None:
    room = _create_room(host)
    _join(friend, room["code"])
    _join(stranger, room["code"])
    assert host.post("/api/game/rooms/leave").status_code == 204
    assert _room(friend)["is_host"] is True
    assert _room(stranger)["is_host"] is False


def test_the_last_member_leaving_ends_the_room(host: TestClient, stranger: TestClient) -> None:
    code = _create_room(host)["code"]
    assert host.post("/api/game/rooms/leave").status_code == 204
    assert stranger.post(f"/api/game/rooms/{code}/join").status_code == 404


def test_leaving_with_no_room_is_a_404(stranger: TestClient) -> None:
    assert stranger.post("/api/game/rooms/leave").status_code == 404


# ---------- ending ----------


def test_ending_the_room_takes_access_away_from_every_member(
    host: TestClient, friend: TestClient
) -> None:
    room = _create_room(host)
    _join(friend, room["code"])
    alice = _enroll(host, "Alice")
    _enroll(friend, "Bob")

    assert host.post("/api/game/room/end").status_code == 204

    assert host.get("/api/game/room").status_code == 404
    assert friend.get("/api/game/room").status_code == 404
    # Not just reading: every route is closed to a former member.
    assert _attempt(friend, typist_id=None, target_id=alice["id"]).status_code == 404  # type: ignore[attr-defined]
    assert friend.post("/api/game/replay", json={"target_id": alice["id"]}).status_code == 404
    assert (
        friend.post(
            "/api/game/players", json={"name": "Again", "training_lines": [SENTENCE_LINE] * 5}
        ).status_code
        == 404
    )


def test_only_the_host_can_end_the_room(host: TestClient, friend: TestClient) -> None:
    room = _create_room(host)
    _join(friend, room["code"])
    assert friend.post("/api/game/room/end").status_code == 403
    assert _room(host)["id"] == room["id"]


# ---------- expiry ----------


def test_an_expired_room_is_gone_for_its_members(
    host: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_store(monkeypatch, idle_expiry_seconds=0.05)
    _create_room(host)
    time.sleep(0.1)
    assert host.get("/api/game/room").status_code == 404


def test_only_reading_a_room_does_not_keep_it_alive(
    host: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Phase 2 polls GET /room; a room nobody plays in must still expire.
    _use_store(monkeypatch, idle_expiry_seconds=0.3)
    _create_room(host)
    deadline = time.monotonic() + 0.4
    while time.monotonic() < deadline:
        host.get("/api/game/room")
        time.sleep(0.05)
    assert host.get("/api/game/room").status_code == 404


# ---------- removing a member ----------


def test_a_removed_member_loses_access_and_their_players(
    host: TestClient, friend: TestClient
) -> None:
    room = _create_room(host)
    friend_member_id = _join(friend, room["code"])["member_id"]
    alice = _enroll(host, "Alice")
    _enroll(friend, "Bob")

    resp = host.delete(f"/api/game/room/members/{friend_member_id}")
    assert resp.status_code == 204

    assert friend.get("/api/game/room").status_code == 404
    assert _attempt(friend, typist_id=None, target_id=alice["id"]).status_code == 404  # type: ignore[attr-defined]
    after = _room(host)
    assert after["member_count"] == 1
    assert [p["name"] for p in after["players"]] == ["Alice"]


def test_a_removed_member_can_rejoin_unless_the_room_is_locked(
    host: TestClient, friend: TestClient
) -> None:
    room = _create_room(host)
    friend_member_id = _join(friend, room["code"])["member_id"]
    host.delete(f"/api/game/room/members/{friend_member_id}")

    host.post("/api/game/room/lock", json={"locked": True})
    assert friend.post(f"/api/game/rooms/{room['code']}/join").status_code == 423


def test_only_the_host_can_remove_a_member(host: TestClient, friend: TestClient) -> None:
    room = _create_room(host)
    _join(friend, room["code"])
    resp = friend.delete(f"/api/game/room/members/{room['member_id']}")
    assert resp.status_code == 403
    assert _room(host)["member_count"] == 2


def test_the_host_cannot_remove_themselves_or_an_unknown_member(host: TestClient) -> None:
    room = _create_room(host)
    assert host.delete(f"/api/game/room/members/{room['member_id']}").status_code == 400
    assert host.delete("/api/game/room/members/nobody").status_code == 404
    assert _room(host)["member_count"] == 1


# ---------- whose player is it ----------


def test_a_player_records_the_member_who_enrolled_them(
    host: TestClient, friend: TestClient
) -> None:
    room = _create_room(host)
    joined = _join(friend, room["code"])
    alice = _enroll(host, "Alice")
    bob = _enroll(friend, "Bob")
    assert alice["owner_member_id"] == room["member_id"]
    assert bob["owner_member_id"] == joined["member_id"]
    # Sample bots belong to nobody.
    assert all(t["owner_member_id"] is None for t in room["targets"])


def test_a_member_cannot_rename_another_members_player(
    host: TestClient, friend: TestClient
) -> None:
    room = _create_room(host)
    _join(friend, room["code"])
    alice = _enroll(host, "Alice")

    resp = friend.patch(f"/api/game/players/{alice['id']}", json={"name": "Hacked"})
    assert resp.status_code == 403
    assert [p["name"] for p in _room(host)["players"]] == ["Alice"]


def test_not_even_the_host_can_rename_another_members_player(
    host: TestClient, friend: TestClient
) -> None:
    room = _create_room(host)
    _join(friend, room["code"])
    bob = _enroll(friend, "Bob")
    resp = host.patch(f"/api/game/players/{bob['id']}", json={"name": "Renamed"})
    assert resp.status_code == 403


@pytest.mark.parametrize("path", ["/api/game/players/{id}", "/api/game/room/players/{id}"])
def test_a_member_cannot_delete_another_members_player(
    host: TestClient, friend: TestClient, path: str
) -> None:
    room = _create_room(host)
    _join(friend, room["code"])
    alice = _enroll(host, "Alice")

    assert friend.delete(path.format(id=alice["id"])).status_code == 403
    assert [p["name"] for p in _room(host)["players"]] == ["Alice"]


@pytest.mark.parametrize("path", ["/api/game/players/{id}", "/api/game/room/players/{id}"])
def test_a_member_can_delete_their_own_player(
    host: TestClient, friend: TestClient, path: str
) -> None:
    room = _create_room(host)
    _join(friend, room["code"])
    bob = _enroll(friend, "Bob")
    assert friend.delete(path.format(id=bob["id"])).status_code == 204
    assert _room(host)["players"] == []


def test_the_host_can_delete_any_player(host: TestClient, friend: TestClient) -> None:
    room = _create_room(host)
    _join(friend, room["code"])
    bob = _enroll(friend, "Bob")
    assert host.delete(f"/api/game/room/players/{bob['id']}").status_code == 204
    assert _room(friend)["players"] == []
    # Losing a player is not losing the room.
    assert _room(friend)["member_count"] == 2


def test_a_member_cannot_type_as_another_members_player(
    host: TestClient, friend: TestClient
) -> None:
    room = _create_room(host)
    _join(friend, room["code"])
    alice = _enroll(host, "Alice")
    bob = _enroll(friend, "Bob")

    resp = _attempt(friend, typist_id=alice["id"], target_id=bob["id"])
    assert resp.status_code == 403  # type: ignore[attr-defined]
    assert _room(host)["attempts"] == []


def test_anyone_can_attack_any_player_as_their_own_player_or_as_guest(
    host: TestClient, friend: TestClient
) -> None:
    room = _create_room(host)
    _join(friend, room["code"])
    alice = _enroll(host, "Alice")
    bob = _enroll(friend, "Bob")

    as_bob = _attempt(friend, typist_id=bob["id"], target_id=alice["id"], attempt_id="b1")
    as_guest = _attempt(friend, typist_id=None, target_id=alice["id"], attempt_id="g1")
    assert as_bob.status_code == 200  # type: ignore[attr-defined]
    assert as_guest.status_code == 200  # type: ignore[attr-defined]
    # Everyone in the room sees both.
    assert [a["typist_name"] for a in _room(host)["attempts"]] == ["Bob", "Guest"]


def test_a_player_from_another_room_is_neither_a_typist_nor_a_target(
    host: TestClient, stranger: TestClient
) -> None:
    _create_room(host)
    alice = _enroll(host, "Alice")
    _create_room(stranger)
    eve = _enroll(stranger, "Eve")

    assert _attempt(stranger, typist_id=None, target_id=alice["id"]).status_code == 400  # type: ignore[attr-defined]
    assert _attempt(stranger, typist_id=alice["id"], target_id=eve["id"]).status_code == 400  # type: ignore[attr-defined]
    assert stranger.delete(f"/api/game/room/players/{alice['id']}").status_code == 404
    assert stranger.patch(f"/api/game/players/{alice['id']}", json={"name": "X"}).status_code == 404


# ---------- same_keyboard ----------


def test_attempts_record_whether_typist_and_target_share_a_keyboard(
    host: TestClient, friend: TestClient
) -> None:
    room = _create_room(host)
    _join(friend, room["code"])
    alice = _enroll(host, "Alice")
    amir = _enroll(host, "Amir")  # a second person at the host's keyboard
    bot_id = room["targets"][0]["id"]

    def same_keyboard(resp) -> object:
        assert resp.status_code == 200, resp.text
        return resp.json()["attempt"]["same_keyboard"]

    assert same_keyboard(_attempt(host, typist_id=amir["id"], target_id=alice["id"])) is True
    assert same_keyboard(_attempt(host, typist_id=None, target_id=alice["id"])) is True
    assert same_keyboard(_attempt(friend, typist_id=None, target_id=alice["id"])) is False
    # No keyboard to compare with for a bot, or for a replay.
    assert (
        same_keyboard(_attempt(host, typist_id=amir["id"], target_id=bot_id, attempt_id="a2"))
        is None
    )
    assert same_keyboard(host.post("/api/game/replay", json={"target_id": alice["id"]})) is None


def test_two_browsers_reusing_a_client_attempt_id_are_not_merged(
    host: TestClient, friend: TestClient
) -> None:
    # Guests have no typist id, so only the sending member keeps two
    # browsers' attempts apart.
    room = _create_room(host)
    _join(friend, room["code"])
    alice = _enroll(host, "Alice")
    first = _attempt(host, typist_id=None, target_id=alice["id"], attempt_id="same")
    second = _attempt(friend, typist_id=None, target_id=alice["id"], attempt_id="same")
    assert first.json()["attempt"]["id"] != second.json()["attempt"]["id"]  # type: ignore[attr-defined]
    assert len(_room(host)["attempts"]) == 2


# ---------- limits ----------


def test_a_full_room_refuses_new_joiners_with_a_clear_message(
    host: TestClient, friend: TestClient, stranger: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_store(monkeypatch, members_per_party_limit=2)
    room = _create_room(host)
    _join(friend, room["code"])
    refused = stranger.post(f"/api/game/rooms/{room['code']}/join")
    assert refused.status_code == 409
    assert "full" in refused.json()["detail"]
    assert _room(host)["member_count"] == 2


def test_the_player_limit_is_shared_by_the_whole_room(
    host: TestClient, friend: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_store(monkeypatch, players_per_party_limit=1)
    room = _create_room(host)
    _join(friend, room["code"])
    _enroll(host, "Alice")
    resp = friend.post(
        "/api/game/players", json={"name": "Bob", "training_lines": [SENTENCE_LINE] * 5}
    )
    assert resp.status_code == 409


def test_the_room_limit_refuses_a_new_room_without_evicting_anyone(
    host: TestClient, friend: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_store(monkeypatch, party_limit=1)
    kept = _create_room(host)
    assert friend.post("/api/game/rooms", json={"level": "sentence"}).status_code == 503
    assert _room(host)["id"] == kept["id"]


def test_the_attempt_limit_keeps_only_the_most_recent(
    host: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_store(monkeypatch, attempts_per_party_limit=2)
    _create_room(host)
    alice = _enroll(host, "Alice")
    for i in range(3):
        _attempt(host, typist_id=None, target_id=alice["id"], attempt_id=f"a{i}")
    assert len(_room(host)["attempts"]) == 2


# ---------- version ----------


def test_version_goes_up_on_every_change_and_not_on_a_read(
    host: TestClient, friend: TestClient
) -> None:
    room = _create_room(host)
    seen = [room["version"]]

    def changed() -> None:
        version = _room(host)["version"]
        assert version > seen[-1]
        seen.append(version)

    _join(friend, room["code"])
    changed()
    alice = _enroll(host, "Alice")
    changed()
    host.patch(f"/api/game/players/{alice['id']}", json={"name": "Alicia"})
    changed()
    _attempt(friend, typist_id=None, target_id=alice["id"])
    changed()
    host.post("/api/game/replay", json={"target_id": alice["id"]})
    changed()
    host.post("/api/game/room/lock", json={"locked": True})
    changed()
    host.delete(f"/api/game/room/players/{alice['id']}")
    changed()
    friend.post("/api/game/rooms/leave")
    changed()

    assert _room(host)["version"] == seen[-1]  # reading changed nothing


# ---------- origin ----------

ROOM_STATE_CHANGING_REQUESTS = [
    ("post", "/api/game/rooms", {"level": "sentence"}),
    ("post", "/api/game/rooms/ABCDEFGH/join", None),
    ("post", "/api/game/rooms/leave", None),
    ("post", "/api/game/room/lock", {"locked": True}),
    ("post", "/api/game/room/end", None),
    ("delete", "/api/game/room/players/x", None),
    ("delete", "/api/game/room/members/x", None),
]


@pytest.mark.parametrize("origin", [None, "http://evil.example"], ids=["missing", "mismatched"])
@pytest.mark.parametrize(("method", "path", "body"), ROOM_STATE_CHANGING_REQUESTS)
def test_every_room_route_that_changes_state_checks_the_origin(
    origin: str | None, method: str, path: str, body: dict | None
) -> None:
    headers = {"origin": origin} if origin else {}
    with TestClient(app, headers=headers) as c:
        fn = getattr(c, method)
        resp = fn(path, json=body) if body is not None else fn(path)
        assert resp.status_code == 403
