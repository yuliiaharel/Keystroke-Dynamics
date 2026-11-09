"""/api/game/*: the anonymous party game's HTTP surface. Unit
coverage for scoring/judging/store logic lives under tests/game/ --
this file is about the API-level contract: session isolation, origin
and rate-limit enforcement, idempotency, and the shape of what comes
back over the wire.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from keystroke_dynamics.game.rate_limit import game_rate_limiter
from keystroke_dynamics.main import app

SENTENCE_PHRASE = "quiet rhythm hides in every small habit of your hands"


def _char_to_code(ch: str) -> str:
    return "Space" if ch == " " else f"Key{ch.upper()}"


def _line_for(phrase: str, *, hold_ms: float = 80.0, gap_ms: float = 150.0) -> list[dict]:
    """A clean, consistent typing of `phrase`, down/up pairs in order."""
    events: list[dict] = []
    t = 0.0
    for i, ch in enumerate(phrase):
        if i > 0:
            t += gap_ms
        code = _char_to_code(ch)
        events.append({"code": code, "action": "down", "t_ms": t})
        events.append({"code": code, "action": "up", "t_ms": t + hold_ms})
    return events


#: A clean, consistent typing of the sentence level's own phrase --
#: used as both a training line and a matching attempt throughout
#: this file.
SENTENCE_LINE = _line_for(SENTENCE_PHRASE)


def _create_party(client: TestClient, level: str = "sentence") -> dict:
    resp = client.post("/api/game/party", json={"level": level})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _create_player(client: TestClient, name: str | None = None) -> dict:
    resp = client.post(
        "/api/game/players", json={"name": name, "training_lines": [SENTENCE_LINE] * 5}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------- party lifecycle ----------


def test_create_party_returns_the_phrase_and_no_players(client: TestClient) -> None:
    party = _create_party(client)
    assert party["phrase"] == SENTENCE_PHRASE
    assert party["players"] == []
    assert len(party["targets"]) == 3  # the three sample bots, always present


def test_get_party_with_no_session_returns_404(client: TestClient) -> None:
    resp = client.get("/api/game/party")
    assert resp.status_code == 404


def test_get_party_round_trips_after_create(client: TestClient) -> None:
    created = _create_party(client)
    fetched = client.get("/api/game/party").json()
    assert fetched["id"] == created["id"]


def test_party_reset_clears_the_session(client: TestClient) -> None:
    _create_party(client)
    resp = client.post("/api/game/party/reset")
    assert resp.status_code == 204
    assert client.get("/api/game/party").status_code == 404


# ---------- session isolation ----------


def test_one_session_cannot_see_another_sessions_party() -> None:
    with (
        TestClient(app, headers={"origin": "http://testserver"}) as alice,
        TestClient(app, headers={"origin": "http://testserver"}) as bob,
    ):
        alice_party = _create_party(alice)
        assert bob.get("/api/game/party").status_code == 404

        bob_party = _create_party(bob)
        assert alice_party["id"] != bob_party["id"]
        # Each only ever sees their own party's state.
        assert alice.get("/api/game/party").json()["id"] == alice_party["id"]
        assert bob.get("/api/game/party").json()["id"] == bob_party["id"]


def test_a_players_id_from_another_party_is_not_a_valid_target() -> None:
    with (
        TestClient(app, headers={"origin": "http://testserver"}) as alice,
        TestClient(app, headers={"origin": "http://testserver"}) as bob,
    ):
        _create_party(alice)
        alice_player = _create_player(alice, "Alice")
        _create_party(bob)

        # Bob names Alice's real player id as his attempt's target --
        # it must not resolve, even though the id is real and active.
        resp = bob.post(
            "/api/game/attempts",
            json={
                "typist_id": None,
                "target_id": alice_player["id"],
                "mode": "attack",
                "events": SENTENCE_LINE,
                "client_attempt_id": "x1",
            },
        )
        assert resp.status_code == 400


# ---------- players ----------


def test_create_player_generates_a_name_when_none_given(client: TestClient) -> None:
    _create_party(client)
    player = _create_player(client, name=None)
    assert player["name"]  # non-empty, generated
    assert player["kind"] == "player"


def test_create_player_rejects_a_blocked_word_name(client: TestClient) -> None:
    _create_party(client)
    resp = client.post(
        "/api/game/players", json={"name": "admin", "training_lines": [SENTENCE_LINE] * 5}
    )
    assert resp.status_code == 400


def test_create_player_rejects_a_duplicate_name_within_the_party(client: TestClient) -> None:
    _create_party(client)
    _create_player(client, "Alice")
    resp = client.post(
        "/api/game/players", json={"name": "alice", "training_lines": [SENTENCE_LINE] * 5}
    )
    assert resp.status_code == 400


def test_player_name_with_html_round_trips_as_plain_text(client: TestClient) -> None:
    # The API stores and returns it verbatim -- escaping it on display
    # is the frontend's job (Jinja autoescape / DOM text assignment),
    # not something the wire format does. See docs/plans/done/PARTY_LAUNCH_PLAN.md
    # Part 1 section 3 for the full "render as text only" requirement,
    # which still needs a frontend/Playwright check once that exists.
    _create_party(client)
    name = "<b>bob</b>"
    player = _create_player(client, name)
    assert player["name"] == name
    party = client.get("/api/game/party").json()
    assert party["players"][0]["name"] == name


def test_player_view_never_includes_the_underlying_profile(client: TestClient) -> None:
    _create_party(client)
    player = _create_player(client, "Alice")
    assert set(player.keys()) == {
        "id",
        "name",
        "color",
        "threshold",
        "notes",
        "kind",
        "owner_member_id",
    }


def test_rename_player(client: TestClient) -> None:
    _create_party(client)
    player = _create_player(client, "Alice")
    resp = client.patch(f"/api/game/players/{player['id']}", json={"name": "Alicia"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Alicia"


def test_rename_to_an_existing_name_is_rejected(client: TestClient) -> None:
    _create_party(client)
    _create_player(client, "Alice")
    bob = _create_player(client, "Bob")
    resp = client.patch(f"/api/game/players/{bob['id']}", json={"name": "alice"})
    assert resp.status_code == 400


def test_rename_unknown_player_returns_404(client: TestClient) -> None:
    _create_party(client)
    resp = client.patch("/api/game/players/does-not-exist", json={"name": "New Name"})
    assert resp.status_code == 404


def test_delete_player(client: TestClient) -> None:
    _create_party(client)
    player = _create_player(client, "Alice")
    assert client.delete(f"/api/game/players/{player['id']}").status_code == 204
    party = client.get("/api/game/party").json()
    assert party["players"] == []


def test_delete_unknown_player_returns_404(client: TestClient) -> None:
    _create_party(client)
    assert client.delete("/api/game/players/does-not-exist").status_code == 404


def test_players_per_party_limit_returns_409(client: TestClient, monkeypatch) -> None:
    from keystroke_dynamics.api import game as game_api
    from keystroke_dynamics.game.store import InMemoryGameStore

    tiny_store = InMemoryGameStore(
        party_limit=500,
        players_per_party_limit=1,
        attempts_per_party_limit=200,
        idle_expiry_seconds=7200,
    )
    monkeypatch.setattr(game_api, "_store", tiny_store)
    _create_party(client)
    _create_player(client, "Alice")
    resp = client.post(
        "/api/game/players", json={"name": "Bob", "training_lines": [SENTENCE_LINE] * 5}
    )
    assert resp.status_code == 409


# ---------- attempts ----------


def test_attack_against_a_real_player_with_matching_rhythm_fools_it(client: TestClient) -> None:
    _create_party(client)
    player = _create_player(client, "Alice")
    resp = client.post(
        "/api/game/attempts",
        json={
            "typist_id": None,
            "target_id": player["id"],
            "mode": "attack",
            "events": SENTENCE_LINE,
            "client_attempt_id": "a1",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["attempt"]["word"] == "Fooled it!"
    assert body["attempt"]["passed"] is True
    # Pace and clue (docs/plans/done/PARTY_LAUNCH_PLAN.md section 8): present on every
    # scoreable attempt, not just disguise mode.
    assert isinstance(body["attempt"]["pace"], float)
    assert isinstance(body["clue"], str)


def test_attack_against_a_sample_bot(client: TestClient) -> None:
    party = _create_party(client)
    bot_id = party["targets"][0]["id"]
    resp = client.post(
        "/api/game/attempts",
        json={
            "typist_id": None,
            "target_id": bot_id,
            "mode": "attack",
            "events": SENTENCE_LINE,
            "client_attempt_id": "a1",
        },
    )
    assert resp.status_code == 200


def test_unknown_target_returns_400(client: TestClient) -> None:
    _create_party(client)
    resp = client.post(
        "/api/game/attempts",
        json={
            "typist_id": None,
            "target_id": "does-not-exist",
            "mode": "attack",
            "events": SENTENCE_LINE,
            "client_attempt_id": "a1",
        },
    )
    assert resp.status_code == 400


def test_unknown_typist_returns_400(client: TestClient) -> None:
    _create_party(client)
    player = _create_player(client, "Alice")
    resp = client.post(
        "/api/game/attempts",
        json={
            "typist_id": "does-not-exist",
            "target_id": player["id"],
            "mode": "attack",
            "events": SENTENCE_LINE,
            "client_attempt_id": "a1",
        },
    )
    assert resp.status_code == 400


def test_attempt_is_idempotent_on_client_attempt_id(client: TestClient) -> None:
    _create_party(client)
    player = _create_player(client, "Alice")
    body = {
        "typist_id": None,
        "target_id": player["id"],
        "mode": "attack",
        "events": SENTENCE_LINE,
        "client_attempt_id": "same-key",
    }
    first = client.post("/api/game/attempts", json=body).json()
    second = client.post("/api/game/attempts", json=body).json()
    assert first["attempt"]["id"] == second["attempt"]["id"]

    party = client.get("/api/game/party").json()
    assert len(party["attempts"]) == 1  # not recorded twice


def test_a_different_client_attempt_id_is_recorded_separately(client: TestClient) -> None:
    _create_party(client)
    player = _create_player(client, "Alice")
    for key in ("key-1", "key-2"):
        client.post(
            "/api/game/attempts",
            json={
                "typist_id": None,
                "target_id": player["id"],
                "mode": "attack",
                "events": SENTENCE_LINE,
                "client_attempt_id": key,
            },
        )
    party = client.get("/api/game/party").json()
    assert len(party["attempts"]) == 2


# ---------- replay ----------


def test_replay_against_a_real_player(client: TestClient) -> None:
    _create_party(client)
    player = _create_player(client, "Alice")
    resp = client.post("/api/game/replay", json={"target_id": player["id"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["attempt"]["word"] == "Replay wins"
    assert body["notes"] == player["notes"]  # exactly what's needed to animate it


def test_replay_against_an_unknown_target_returns_400(client: TestClient) -> None:
    _create_party(client)
    resp = client.post("/api/game/replay", json={"target_id": "does-not-exist"})
    assert resp.status_code == 400


# ---------- origin + rate limiting ----------


STATE_CHANGING_REQUESTS = [
    ("post", "/api/game/party", {"level": "sentence"}),
    ("post", "/api/game/party/reset", None),
    ("post", "/api/game/players", {"name": None, "training_lines": [SENTENCE_LINE] * 5}),
    ("patch", "/api/game/players/x", {"name": "New Name"}),
    ("delete", "/api/game/players/x", None),
    (
        "post",
        "/api/game/attempts",
        {
            "typist_id": None,
            "target_id": "x",
            "mode": "attack",
            "events": SENTENCE_LINE,
            "client_attempt_id": "a1",
        },
    ),
    ("post", "/api/game/replay", {"target_id": "x"}),
]


def _call(c: TestClient, method: str, path: str, body: dict | None):
    fn = getattr(c, method)
    return fn(path, json=body) if body is not None else fn(path)


def test_get_party_does_not_require_a_matching_origin(client: TestClient) -> None:
    # The one read-only route in this router -- confirms it was never
    # swept into _STATE_CHANGING by accident.
    with TestClient(app) as bare_client:  # no Origin header at all
        resp = bare_client.get("/api/game/party")
        assert resp.status_code == 404  # no session party -- not 403


def test_missing_origin_is_rejected_on_every_state_changing_route() -> None:
    for method, path, body in STATE_CHANGING_REQUESTS:
        with TestClient(app) as bare_client:  # no Origin header
            resp = _call(bare_client, method, path, body)
            assert resp.status_code == 403, f"{method} {path}"


def test_mismatched_origin_is_rejected_on_every_state_changing_route() -> None:
    for method, path, body in STATE_CHANGING_REQUESTS:
        with TestClient(app, headers={"origin": "http://evil.example"}) as evil_client:
            resp = _call(evil_client, method, path, body)
            assert resp.status_code == 403, f"{method} {path}"


def test_rate_limiting_blocks_after_too_many_requests(client: TestClient) -> None:
    # The rate-limit dependency runs before the route body on every
    # state-changing route, so it's exercised the same way whether or
    # not a party happens to exist -- repeatedly hitting reset is
    # enough, regardless of its own 204/404 outcome.
    for _ in range(game_rate_limiter.max_attempts):
        resp = client.post("/api/game/party/reset")
        assert resp.status_code != 429
    resp = client.post("/api/game/party/reset")
    assert resp.status_code == 429


# ---------- debug-only target recording (Part 1 section 7) ----------
#
# tests/conftest.py sets DEBUG=true, so the route exists in this
# suite's app instance -- its *absence* outside debug mode needs a
# fresh process instead (settings.debug is read once, at import time,
# to decide whether to register the route at all); see
# tests/test_public_mode.py's own subprocess for why.


def test_record_target_writes_a_file_the_game_can_then_load(
    client: TestClient, monkeypatch, tmp_path
) -> None:
    from keystroke_dynamics.api import game as game_api
    from keystroke_dynamics.game import targets as targets_module

    monkeypatch.setattr(game_api, "TARGETS_DIR", tmp_path)
    monkeypatch.setattr(targets_module, "TARGETS_DIR", tmp_path)

    resp = client.post(
        "/api/game/debug/record-target",
        json={"name": "Yuliia", "lines": {"sentence": [SENTENCE_LINE] * 5}},
    )
    assert resp.status_code == 204, resp.text
    assert list(tmp_path.glob("*.json"))

    _create_party(client, level="sentence")
    party = client.get("/api/game/party").json()
    recorded = [t for t in party["targets"] if t["kind"] == "target"]
    assert recorded and recorded[0]["name"] == "Yuliia"


def test_record_target_requires_a_matching_origin(client: TestClient) -> None:
    with TestClient(app) as bare_client:  # no Origin header
        resp = bare_client.post(
            "/api/game/debug/record-target",
            json={"name": "Yuliia", "lines": {"sentence": [SENTENCE_LINE] * 5}},
        )
        assert resp.status_code == 403
