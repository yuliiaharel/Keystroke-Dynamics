"""/api/game touch rooms (docs/plans/active/MOBILE_PLAN.md Phase 1):
one device type per room, the other kind of device watching, touch
lines validated and scored, tap maps shared with the room only, and
keyboard rooms left as they were. Each "browser" is its own
TestClient, so its own session cookie and its own room member.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from keystroke_dynamics.config import settings
from keystroke_dynamics.game.levels import TOUCH_LEVEL
from keystroke_dynamics.game.touch_scoring import TOUCH_MAX_THRESHOLD, TOUCH_MIN_THRESHOLD
from keystroke_dynamics.main import app
from tests.api.test_game import SENTENCE_LINE
from tests.touch_lines import TOUCH_PHRASE, tap_line, tap_lines

ORIGIN = {"origin": "http://testserver"}
TOUCH = {"device_type": "touch"}


@pytest.fixture
def phone() -> Iterator[TestClient]:
    with TestClient(app, headers=ORIGIN) as c:
        yield c


@pytest.fixture
def second_phone() -> Iterator[TestClient]:
    with TestClient(app, headers=ORIGIN) as c:
        yield c


@pytest.fixture
def laptop() -> Iterator[TestClient]:
    with TestClient(app, headers=ORIGIN) as c:
        yield c


def _create_touch_room(client: TestClient) -> dict:
    resp = client.post("/api/game/rooms", json={"level": TOUCH_LEVEL, **TOUCH})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _create_keyboard_room(client: TestClient) -> dict:
    resp = client.post("/api/game/rooms", json={"level": "sentence"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _join(client: TestClient, code: str, **body: object) -> dict:
    resp = client.post(f"/api/game/rooms/{code}/join", json=body or None)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _enroll_touch(client: TestClient, name: str, typist: str | None = None) -> dict:
    resp = client.post(
        "/api/game/players",
        json={"name": name, "training_lines": tap_lines(typist or name.lower())},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _enroll_keyboard(client: TestClient, name: str) -> dict:
    resp = client.post(
        "/api/game/players", json={"name": name, "training_lines": [SENTENCE_LINE] * 5}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _attempt(
    client: TestClient,
    *,
    target_id: str,
    events: list[dict],
    typist_id: str | None = None,
    mode: str = "attack",
    attempt_id: str = "a1",
):
    return client.post(
        "/api/game/attempts",
        json={
            "typist_id": typist_id,
            "target_id": target_id,
            "mode": mode,
            "events": events,
            "client_attempt_id": attempt_id,
        },
    )


# ---------- creating and joining ----------


def test_creating_a_touch_room_gives_the_touch_line_and_touch_samples(phone: TestClient) -> None:
    room = _create_touch_room(phone)
    assert room["device_type"] == "touch"
    assert room["watching"] is False
    assert room["level"] == TOUCH_LEVEL
    assert room["phrase"] == TOUCH_PHRASE
    assert room["is_host"] is True
    assert [t["name"] for t in room["targets"]] == [
        "Sample: Speedy Thumbs",
        "Sample: One-Finger Pecker",
    ]
    assert all(t["kind"] == "sample" for t in room["targets"])


def test_a_keyboard_room_reports_its_type_and_is_otherwise_as_before(laptop: TestClient) -> None:
    room = _create_keyboard_room(laptop)
    assert room["device_type"] == "keyboard"
    assert room["watching"] is False
    assert room["level"] == "sentence"
    assert len(room["targets"]) == 3
    assert all(t["tap_map"] == [] for t in room["targets"])


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"level": "sentence", "device_type": "touch"}, id="touch-room-keyboard-level"),
        pytest.param({"level": "long", "device_type": "touch"}, id="touch-room-long-level"),
        pytest.param({"level": TOUCH_LEVEL}, id="keyboard-room-touch-level-by-default"),
        pytest.param(
            {"level": TOUCH_LEVEL, "device_type": "keyboard"}, id="keyboard-room-touch-level"
        ),
    ],
)
def test_the_touch_level_and_touch_rooms_only_go_together(phone: TestClient, body: dict) -> None:
    resp = phone.post("/api/game/rooms", json=body)
    assert resp.status_code == 400
    assert "touch room always uses" in resp.json()["detail"]
    assert phone.get("/api/game/room").status_code == 404


def test_an_unknown_device_type_is_refused(phone: TestClient) -> None:
    resp = phone.post("/api/game/rooms", json={"level": TOUCH_LEVEL, "device_type": "tablet"})
    assert resp.status_code == 422


def test_a_second_phone_joins_a_touch_room_and_both_enroll(
    phone: TestClient, second_phone: TestClient
) -> None:
    code = _create_touch_room(phone)["code"]
    joined = _join(second_phone, code, **TOUCH)
    assert joined["device_type"] == "touch"
    assert joined["watching"] is False
    assert joined["is_host"] is False
    assert joined["member_count"] == 2

    alice = _enroll_touch(phone, "Alice")
    bob = _enroll_touch(second_phone, "Bob")
    room = phone.get("/api/game/room").json()
    assert {p["name"] for p in room["players"]} == {"Alice", "Bob"}
    assert alice["owner_member_id"] == room["member_id"]
    assert bob["owner_member_id"] == joined["member_id"]
    for player in (alice, bob):
        assert TOUCH_MIN_THRESHOLD <= player["threshold"] <= TOUCH_MAX_THRESHOLD
        assert len(player["notes"]) == len(TOUCH_PHRASE)


# ---------- watching ----------


def test_a_computer_can_watch_a_touch_room_but_not_play(
    phone: TestClient, laptop: TestClient
) -> None:
    code = _create_touch_room(phone)["code"]
    alice = _enroll_touch(phone, "Alice")

    # A page from before touch rooms sends no device type at all.
    watching = _join(laptop, code)
    assert watching["watching"] is True
    assert watching["device_type"] == "touch"
    # A watcher is a member like any other, and counts toward the limit.
    assert watching["member_count"] == 2

    # They can read the room, with its players and tap maps...
    room = laptop.get("/api/game/room")
    assert room.status_code == 200
    assert [p["name"] for p in room.json()["players"]] == ["Alice"]
    # ...and run a replay, as a phone in a keyboard room could before.
    replay = laptop.post("/api/game/replay", json={"target_id": alice["id"]})
    assert replay.status_code == 200, replay.text
    assert replay.json()["attempt"]["word"] == "Replay wins"

    # They can't enroll, with a keyboard line or a tap line...
    for lines in ([SENTENCE_LINE] * 5, tap_lines("mallory")):
        enroll = laptop.post("/api/game/players", json={"name": "Mallory", "training_lines": lines})
        assert enroll.status_code == 403
        assert enroll.json()["detail"] == (
            "This room is for phones. You can watch it here, but not play."
        )
    # ...or type, even as Guest, even with a perfectly good tap line.
    for events in (SENTENCE_LINE, tap_line("alice", line=9)):
        attempt = _attempt(laptop, target_id=alice["id"], events=events)
        assert attempt.status_code == 403
        assert "This room is for phones" in attempt.json()["detail"]

    after = phone.get("/api/game/room").json()
    assert [p["name"] for p in after["players"]] == ["Alice"]
    # Only the replay was recorded.
    assert [a["mode"] for a in after["attempts"]] == ["replay"]


def test_a_phone_can_watch_a_keyboard_room_but_not_play(
    laptop: TestClient, phone: TestClient
) -> None:
    code = _create_keyboard_room(laptop)["code"]
    alice = _enroll_keyboard(laptop, "Alice")

    watching = _join(phone, code, **TOUCH)
    assert watching["watching"] is True
    assert watching["device_type"] == "keyboard"
    assert watching["member_count"] == 2

    assert phone.get("/api/game/room").status_code == 200
    replay = phone.post("/api/game/replay", json={"target_id": alice["id"]})
    assert replay.status_code == 200, replay.text

    for lines in (tap_lines("mallory"), [SENTENCE_LINE] * 5):
        enroll = phone.post("/api/game/players", json={"name": "Mallory", "training_lines": lines})
        assert enroll.status_code == 403
        assert enroll.json()["detail"] == (
            "This room is for computers. You can watch it here, but not play."
        )
    for events in (tap_line("alice", line=9), SENTENCE_LINE):
        attempt = _attempt(phone, target_id=alice["id"], events=events)
        assert attempt.status_code == 403
        assert "This room is for computers" in attempt.json()["detail"]

    after = laptop.get("/api/game/room").json()
    assert [p["name"] for p in after["players"]] == ["Alice"]
    assert [a["mode"] for a in after["attempts"]] == ["replay"]


def test_a_watcher_cannot_rename_anyone(phone: TestClient, laptop: TestClient) -> None:
    code = _create_touch_room(phone)["code"]
    alice = _enroll_touch(phone, "Alice")
    _join(laptop, code)
    resp = laptop.patch(f"/api/game/players/{alice['id']}", json={"name": "Renamed"})
    assert resp.status_code == 403
    assert "This room is for phones" in resp.json()["detail"]
    assert phone.get("/api/game/room").json()["players"][0]["name"] == "Alice"


def test_a_watcher_counts_toward_the_member_limit(
    phone: TestClient, laptop: TestClient, second_phone: TestClient, monkeypatch
) -> None:
    from tests.api.test_rooms import _use_store

    _use_store(monkeypatch, members_per_party_limit=2)
    code = _create_touch_room(phone)["code"]
    _join(laptop, code)  # a watcher takes the second and last place
    resp = second_phone.post(f"/api/game/rooms/{code}/join", json=TOUCH)
    assert resp.status_code == 409
    assert "full" in resp.json()["detail"]


def test_a_watcher_who_becomes_host_keeps_host_powers_and_still_cannot_play(
    phone: TestClient, laptop: TestClient, second_phone: TestClient
) -> None:
    # The rooms plan's host rules are unchanged for touch rooms: the
    # longest-standing member takes over, whatever they type on.
    code = _create_touch_room(phone)["code"]
    _join(laptop, code)
    _join(second_phone, code, **TOUCH)
    bob = _enroll_touch(second_phone, "Bob")
    assert phone.post("/api/game/rooms/leave").status_code == 204

    room = laptop.get("/api/game/room").json()
    assert room["is_host"] is True
    assert room["watching"] is True
    assert laptop.post("/api/game/room/lock", json={"locked": True}).status_code == 200
    assert _attempt(laptop, target_id=bob["id"], events=tap_line("bob", line=9)).status_code == 403
    assert laptop.delete(f"/api/game/room/players/{bob['id']}").status_code == 204


# ---------- ownership between phones ----------


def test_one_phone_cannot_rename_delete_or_type_as_anothers_player(
    phone: TestClient, second_phone: TestClient
) -> None:
    code = _create_touch_room(phone)["code"]
    _join(second_phone, code, **TOUCH)
    alice = _enroll_touch(phone, "Alice")
    bob = _enroll_touch(second_phone, "Bob")
    not_yours = "that player belongs to another member of this room"

    rename = second_phone.patch(f"/api/game/players/{alice['id']}", json={"name": "Hacked"})
    assert rename.status_code == 403
    assert rename.json()["detail"] == not_yours

    for path in ("/api/game/players/{id}", "/api/game/room/players/{id}"):
        delete = second_phone.delete(path.format(id=alice["id"]))
        assert delete.status_code == 403
        assert delete.json()["detail"] == not_yours

    typed = _attempt(
        second_phone,
        typist_id=alice["id"],
        target_id=bob["id"],
        events=tap_line("alice", line=9),
    )
    assert typed.status_code == 403
    assert typed.json()["detail"] == not_yours

    room = phone.get("/api/game/room").json()
    assert {p["name"] for p in room["players"]} == {"Alice", "Bob"}
    assert room["attempts"] == []
    # The owner still can do all three.
    assert (
        phone.patch(f"/api/game/players/{alice['id']}", json={"name": "Alicia"}).status_code == 200
    )
    assert (
        _attempt(
            phone, typist_id=alice["id"], target_id=bob["id"], events=tap_line("alice", line=9)
        ).status_code
        == 200
    )
    assert phone.delete(f"/api/game/players/{alice['id']}").status_code == 204


def test_the_host_phone_can_delete_another_phones_player(
    phone: TestClient, second_phone: TestClient
) -> None:
    code = _create_touch_room(phone)["code"]
    _join(second_phone, code, **TOUCH)
    bob = _enroll_touch(second_phone, "Bob")
    assert phone.delete(f"/api/game/room/players/{bob['id']}").status_code == 204


# ---------- attempts ----------


def test_a_touch_attempt_returns_rhythm_place_pace_and_a_clue(phone: TestClient) -> None:
    _create_touch_room(phone)
    alice = _enroll_touch(phone, "Alice")
    resp = _attempt(
        phone,
        typist_id=alice["id"],
        target_id=alice["id"],
        mode="self",
        events=tap_line("alice", line=9),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    attempt = body["attempt"]
    assert attempt["word"] == "That's you"
    assert attempt["passed"] is True
    assert attempt["rhythm"] is not None and attempt["place"] is not None
    assert attempt["distance"] <= attempt["threshold"] == alice["threshold"]
    assert attempt["pace"] == pytest.approx(1.0, abs=0.1)
    assert body["clue"] == "Speed, rhythm, and tap places all fit"
    # And the same numbers are in the room's history.
    history = phone.get("/api/game/room").json()["attempts"]
    assert history == [attempt]


def test_a_different_tapper_is_caught(phone: TestClient) -> None:
    _create_touch_room(phone)
    alice = _enroll_touch(phone, "Alice")
    resp = _attempt(phone, target_id=alice["id"], events=tap_line("bob", line=0))
    assert resp.status_code == 200, resp.text
    assert resp.json()["attempt"]["word"] == "Caught!"
    assert resp.json()["attempt"]["typist_name"] == "Guest"


def test_a_touch_sample_target_can_be_attacked_and_replayed(phone: TestClient) -> None:
    room = _create_touch_room(phone)
    speedy = room["targets"][0]
    attack = _attempt(phone, target_id=speedy["id"], events=tap_line("alice", line=0))
    assert attack.status_code == 200, attack.text
    assert attack.json()["attempt"]["same_keyboard"] is None
    replay = phone.post("/api/game/replay", json={"target_id": speedy["id"]})
    assert replay.status_code == 200, replay.text
    body = replay.json()
    assert body["attempt"]["word"] == "Replay wins"
    assert body["attempt"]["mode"] == "replay"
    assert body["attempt"]["place"] == pytest.approx(0.0, abs=1e-9)
    assert body["attempt"]["rhythm"] is not None
    assert body["attempt"]["same_keyboard"] is None
    # What the browser animates: median timing only, no positions.
    assert len(body["notes"]) == len(TOUCH_PHRASE)
    assert set(body["notes"][0]) == {"ch", "start_ms", "dur_ms"}


def test_a_touch_line_too_short_to_score_is_too_messy(phone: TestClient) -> None:
    _create_touch_room(phone)
    alice = _enroll_touch(phone, "Alice")
    resp = _attempt(
        phone, target_id=alice["id"], events=tap_line("alice", line=9)[: len(TOUCH_PHRASE)]
    )
    assert resp.status_code == 200, resp.text
    attempt = resp.json()["attempt"]
    assert attempt["word"] == "Too messy"
    assert attempt["counted"] is False
    assert attempt["distance"] is None
    assert attempt["rhythm"] is None and attempt["place"] is None and attempt["pace"] is None
    assert resp.json()["clue"] is None


def test_a_grip_test_is_recorded_as_its_own_mode(phone: TestClient) -> None:
    _create_touch_room(phone)
    alice = _enroll_touch(phone, "Alice")
    resp = _attempt(
        phone,
        typist_id=alice["id"],
        target_id=alice["id"],
        mode="grip",
        events=tap_line("alice", line=9, shift=(0.5, -0.5)),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["attempt"]["mode"] == "grip"
    assert body["attempt"]["word"] == "Who are you?"
    assert body["verdict_text"] == "The new grip was enough to throw it off."
    assert body["attempt"]["rhythm"] < body["attempt"]["threshold"] < body["attempt"]["place"]
    assert body["clue"] == "Right speed and rhythm, wrong tap places"


def test_grip_is_for_touch_rooms_and_disguise_for_keyboard_rooms(
    phone: TestClient, laptop: TestClient
) -> None:
    _create_touch_room(phone)
    alice = _enroll_touch(phone, "Alice")
    disguise = _attempt(
        phone,
        typist_id=alice["id"],
        target_id=alice["id"],
        mode="disguise",
        events=tap_line("alice", line=9),
    )
    assert disguise.status_code == 400
    assert disguise.json()["detail"] == "'disguise' attempts aren't part of a touch room"

    _create_keyboard_room(laptop)
    kate = _enroll_keyboard(laptop, "Kate")
    grip = _attempt(
        laptop, typist_id=kate["id"], target_id=kate["id"], mode="grip", events=SENTENCE_LINE
    )
    assert grip.status_code == 400
    assert grip.json()["detail"] == "'grip' attempts aren't part of a keyboard room"
    # Disguise still works there, exactly as before.
    ok = _attempt(
        laptop, typist_id=kate["id"], target_id=kate["id"], mode="disguise", events=SENTENCE_LINE
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["attempt"]["word"] == "Still you"


def test_a_keyboard_attempt_has_no_rhythm_or_place(laptop: TestClient) -> None:
    _create_keyboard_room(laptop)
    kate = _enroll_keyboard(laptop, "Kate")
    resp = _attempt(laptop, target_id=kate["id"], events=SENTENCE_LINE)
    assert resp.status_code == 200, resp.text
    attempt = resp.json()["attempt"]
    assert attempt["rhythm"] is None and attempt["place"] is None
    assert attempt["distance"] is not None
    assert resp.json()["clue"] == "Right speed, and the rhythm fits"


def test_touch_attempts_record_whether_typist_and_target_share_a_phone(
    phone: TestClient, second_phone: TestClient
) -> None:
    room = _create_touch_room(phone)
    _join(second_phone, room["code"], **TOUCH)
    alice = _enroll_touch(phone, "Alice")
    amy = _enroll_touch(phone, "Amy")
    bob = _enroll_touch(second_phone, "Bob")
    line = tap_line("someone", line=0)

    def same_keyboard(client: TestClient, typist: dict | None, target_id: str, n: int):
        resp = _attempt(
            client,
            typist_id=typist["id"] if typist else None,
            target_id=target_id,
            events=line,
            attempt_id=f"a{n}",
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["attempt"]["same_keyboard"]

    # Passing the phone around: both players enrolled on this phone.
    assert same_keyboard(phone, amy, alice["id"], 1) is True
    # From the other phone, as a player or as Guest.
    assert same_keyboard(second_phone, bob, alice["id"], 2) is False
    assert same_keyboard(second_phone, None, alice["id"], 3) is False
    # A Guest on Alice's own phone.
    assert same_keyboard(phone, None, alice["id"], 4) is True
    # A sample has no phone to share.
    assert same_keyboard(phone, alice, room["targets"][0]["id"], 5) is None

    history = phone.get("/api/game/room").json()["attempts"]
    assert [a["same_keyboard"] for a in history] == [True, False, False, True, None]


def test_a_touch_attempt_is_idempotent_on_its_client_attempt_id(phone: TestClient) -> None:
    _create_touch_room(phone)
    alice = _enroll_touch(phone, "Alice")
    first = _attempt(phone, target_id=alice["id"], events=tap_line("bob"), attempt_id="same")
    again = _attempt(phone, target_id=alice["id"], events=tap_line("bob"), attempt_id="same")
    assert first.status_code == again.status_code == 200
    assert first.json()["attempt"] == again.json()["attempt"]
    assert len(phone.get("/api/game/room").json()["attempts"]) == 1


# ---------- validation ----------


def _with(events: list[dict], index: int, **changes: object) -> list[dict]:
    """A copy of `events` with one event changed; a value of ... drops
    that field."""
    out = [dict(e) for e in events]
    for key, value in changes.items():
        if value is ...:
            out[index].pop(key, None)
        else:
            out[index][key] = value
    return out


GOOD = tap_line("alice", line=9)

BAD_TOUCH_LINES = [
    pytest.param(_with(GOOD, 0, dx=...), "missing its tap position", id="down-without-dx"),
    pytest.param(_with(GOOD, 4, dy=None), "missing its tap position", id="down-with-null-dy"),
    pytest.param(_with(GOOD, 1, dx=0.1), "up event can't carry", id="position-on-up"),
    pytest.param(_with(GOOD, 0, dx=4.5), "too far from its key", id="dx-too-far"),
    pytest.param(_with(GOOD, 0, dy=-1.5), "too far from its key", id="dy-too-far"),
    pytest.param(_with(GOOD, 0, code="Backspace"), "on-page keyboard", id="key-not-on-keyboard"),
    pytest.param(_with(GOOD, 2, t_ms=-5.0), "go backward", id="time-goes-backward"),
    pytest.param(GOOD, "exceeds limit", id="oversized"),
    pytest.param(
        [{"code": e["code"], "action": e["action"], "t_ms": e["t_ms"]} for e in GOOD],
        "missing its tap position",
        id="a-keyboard-line",
    ),
]


@pytest.mark.parametrize(("events", "message"), BAD_TOUCH_LINES)
def test_an_invalid_touch_attempt_is_a_400_and_records_nothing(
    phone: TestClient, events: list[dict], message: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _create_touch_room(phone)
    alice = _enroll_touch(phone, "Alice")
    if message == "exceeds limit":
        # A real 2,000-event line is stopped earlier, by the request
        # size limit; lower the event limit to reach this check.
        monkeypatch.setattr(settings, "max_events", len(events) - 1)
    resp = _attempt(phone, target_id=alice["id"], events=events)
    assert resp.status_code == 400, resp.text
    assert message in resp.json()["detail"]
    assert phone.get("/api/game/room").json()["attempts"] == []


@pytest.mark.parametrize(("events", "message"), BAD_TOUCH_LINES)
def test_an_invalid_touch_training_line_is_a_400_and_enrolls_nobody(
    phone: TestClient, events: list[dict], message: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _create_touch_room(phone)
    if message == "exceeds limit":
        monkeypatch.setattr(settings, "max_events", len(events) - 1)
        events = [*events, *_with(GOOD, 0)[:2]]
    lines = tap_lines("alice", 3)
    resp = phone.post(
        "/api/game/players", json={"name": "Alice", "training_lines": [*lines, events]}
    )
    assert resp.status_code == 400, resp.text
    assert message in resp.json()["detail"]
    assert phone.get("/api/game/room").json()["players"] == []


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("field", ["dx", "dy"])
def test_a_non_finite_tap_position_is_a_400(phone: TestClient, field: str, literal: str) -> None:
    _create_touch_room(phone)
    alice = _enroll_touch(phone, "Alice")
    body = json.dumps(
        {
            "typist_id": None,
            "target_id": alice["id"],
            "mode": "attack",
            "events": _with(GOOD, 0, **{field: "__BAD__"}),
            "client_attempt_id": "a1",
        }
    ).replace('"__BAD__"', literal)
    resp = phone.post(
        "/api/game/attempts", content=body, headers={"content-type": "application/json"}
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "non-finite tap position"


def test_a_validation_error_never_echoes_a_submitted_position(phone: TestClient) -> None:
    _create_touch_room(phone)
    alice = _enroll_touch(phone, "Alice")
    resp = _attempt(phone, target_id=alice["id"], events=_with(GOOD, 0, dx=3.987654, dy=7.123456))
    assert resp.status_code == 400
    assert "3.98" not in resp.text and "7.12" not in resp.text


def test_a_keyboard_room_refuses_tap_positions(laptop: TestClient) -> None:
    _create_keyboard_room(laptop)
    kate = _enroll_keyboard(laptop, "Kate")
    with_position = _with(SENTENCE_LINE, 0, dx=0.1, dy=0.1)

    attempt = _attempt(laptop, target_id=kate["id"], events=with_position)
    assert attempt.status_code == 400
    assert attempt.json()["detail"] == "tap positions are only accepted in touch rooms"

    enroll = laptop.post(
        "/api/game/players",
        json={"name": "Tess", "training_lines": [with_position, *[SENTENCE_LINE] * 4]},
    )
    assert enroll.status_code == 400
    assert enroll.json()["detail"] == "tap positions are only accepted in touch rooms"

    room = laptop.get("/api/game/room").json()
    assert [p["name"] for p in room["players"]] == ["Kate"]
    assert room["attempts"] == []


# ---------- tap maps ----------


def test_tap_maps_are_in_room_state_for_every_member(
    phone: TestClient, second_phone: TestClient, laptop: TestClient
) -> None:
    room = _create_touch_room(phone)
    alice = _enroll_touch(phone, "Alice")
    _join(second_phone, room["code"], **TOUCH)
    _join(laptop, room["code"])  # a watcher is a member too

    # The player's own enrollment response has it...
    assert len(alice["tap_map"]) == 14  # 13 letters and the space bar
    by_code = {p["code"]: p for p in alice["tap_map"]}
    assert set(by_code["KeyT"]) == {"code", "x", "x_spread", "y", "y_spread"}
    assert by_code["Space"]["x"] is None and by_code["Space"]["x_spread"] is None
    assert all(-1 <= p["y"] <= 1 and p["y_spread"] >= 0 for p in alice["tap_map"])

    # ...and so does the room, for each member, samples included.
    for member in (phone, second_phone, laptop):
        state = member.get("/api/game/room").json()
        assert state["players"][0]["tap_map"] == alice["tap_map"]
        assert all(len(t["tap_map"]) == 14 for t in state["targets"])


def test_a_tap_map_is_an_average_never_a_single_tap(phone: TestClient) -> None:
    _create_touch_room(phone)
    lines = tap_lines("alice")
    alice = _enroll_touch(phone, "Alice")
    key_t = next(p for p in alice["tap_map"] if p["code"] == "KeyT")
    taps = [e for line in lines for e in line if e["code"] == "KeyT" and e["action"] == "down"]
    assert key_t["x"] == pytest.approx(sum(e["dx"] for e in taps) / len(taps))
    assert key_t["y"] == pytest.approx(sum(e["dy"] for e in taps) / len(taps))
    assert key_t["x"] not in {e["dx"] for e in taps}


def test_tap_maps_are_not_readable_from_outside_the_room(
    phone: TestClient, second_phone: TestClient
) -> None:
    _create_touch_room(phone)
    _enroll_touch(phone, "Alice")
    # No room at all.
    assert second_phone.get("/api/game/room").status_code == 404
    # A member of a different room sees only their own room.
    _create_touch_room(second_phone)
    other = second_phone.get("/api/game/room").json()
    assert other["players"] == []


def test_a_member_who_leaves_or_is_removed_loses_the_tap_maps(
    phone: TestClient, second_phone: TestClient
) -> None:
    room = _create_touch_room(phone)
    _enroll_touch(phone, "Alice")
    joined = _join(second_phone, room["code"], **TOUCH)
    assert second_phone.get("/api/game/room").json()["players"][0]["tap_map"]
    assert phone.delete(f"/api/game/room/members/{joined['member_id']}").status_code == 204
    assert second_phone.get("/api/game/room").status_code == 404


def test_timing_statistics_stay_private_in_a_touch_room(phone: TestClient) -> None:
    room = _create_touch_room(phone)
    alice = _enroll_touch(phone, "Alice")
    state = phone.get("/api/game/room").json()
    for view in (alice, *state["players"], *state["targets"], *room["targets"]):
        assert set(view) == {
            "id",
            "name",
            "color",
            "threshold",
            "notes",
            "kind",
            "owner_member_id",
            "tap_map",
        }
    # No per-feature timing statistics under any name: the only
    # timing a view carries is the median notes the ring is drawn from.
    text = json.dumps(state)
    assert "flight" not in text and "m2" not in text and "profile" not in text


# ---------- nothing raw is logged ----------


def test_a_touch_game_logs_no_tap_positions_or_timings(
    phone: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    # Distinctive values in the submitted lines: an offset and a time
    # that no code could plausibly produce on its own.
    lines = tap_lines("alice")
    lines[0] = _with(lines[0], 0, dx=0.31337, dy=-0.27183)
    lines[0] = _with(lines[0], 1, t_ms=61.80339)
    attack = _with(tap_line("bob"), 0, dx=0.14159, dy=0.26535)
    attack = _with(attack, 1, t_ms=57.72156)

    with caplog.at_level(logging.DEBUG):
        _create_touch_room(phone)
        resp = phone.post("/api/game/players", json={"name": "Alice", "training_lines": lines})
        assert resp.status_code == 200, resp.text
        alice = resp.json()
        assert _attempt(phone, target_id=alice["id"], events=attack).status_code == 200
        assert phone.post("/api/game/replay", json={"target_id": alice["id"]}).status_code == 200
        # And a refused line, whose error path must not log it either.
        bad = _with(attack, 2, dx=3.99999)
        assert (
            _attempt(phone, target_id=alice["id"], events=bad, attempt_id="a2").status_code == 200
        )
        worse = _with(attack, 2, dx=9.87654)
        assert (
            _attempt(phone, target_id=alice["id"], events=worse, attempt_id="a3").status_code == 400
        )

    logged = "\n".join(record.getMessage() for record in caplog.records)
    for secret in (
        "31337",
        "27183",
        "61.80339",
        "14159",
        "26535",
        "57.72156",
        "3.99999",
        "9.87654",
    ):
        assert secret not in logged
    for word in ('"dx"', "'dx'", "dx=", "t_ms", "KeyT"):
        assert word not in logged


# ---------- screen size ----------


def _member(member_id: str):
    from keystroke_dynamics.api import game as game_api

    for party in game_api._store._parties.values():  # type: ignore[attr-defined]
        if member_id in party.members:
            return party.members[member_id]
    raise AssertionError("no such member")


def test_a_touch_members_viewport_width_is_kept_only_as_a_bucket(
    phone: TestClient, second_phone: TestClient, laptop: TestClient
) -> None:
    created = phone.post(
        "/api/game/rooms", json={"level": TOUCH_LEVEL, **TOUCH, "viewport_width": 320}
    )
    assert created.status_code == 200, created.text
    room = created.json()
    joined = _join(second_phone, room["code"], **TOUCH, viewport_width=430)
    # A computer watching has no bucket, whatever width it sends.
    watcher = _join(laptop, room["code"], viewport_width=1440)

    assert _member(room["member_id"]).screen_size == "small"
    assert _member(joined["member_id"]).screen_size == "large"
    assert _member(watcher["member_id"]).screen_size is None
    # The width isn't on the member, and no room response has either.
    for member_id in (room["member_id"], joined["member_id"]):
        assert not hasattr(_member(member_id), "viewport_width")
    for view in (room, joined, watcher, phone.get("/api/game/room").json()):
        assert "screen_size" not in view and "viewport_width" not in view


def test_a_touch_member_who_sends_no_width_has_no_bucket(phone: TestClient) -> None:
    room = _create_touch_room(phone)
    assert _member(room["member_id"]).screen_size is None


def test_a_keyboard_room_never_records_a_screen_size(laptop: TestClient) -> None:
    created = laptop.post("/api/game/rooms", json={"level": "sentence", "viewport_width": 1440})
    assert created.status_code == 200, created.text
    assert _member(created.json()["member_id"]).screen_size is None


@pytest.mark.parametrize("width", [0, -390, 20_001, 390.5, "wide"])
def test_a_nonsense_viewport_width_is_refused(phone: TestClient, width: object) -> None:
    created = phone.post(
        "/api/game/rooms", json={"level": TOUCH_LEVEL, **TOUCH, "viewport_width": width}
    )
    assert created.status_code == 422
    room = _create_touch_room(phone)
    joined = phone.post(
        f"/api/game/rooms/{room['code']}/join", json={**TOUCH, "viewport_width": width}
    )
    assert joined.status_code == 422
