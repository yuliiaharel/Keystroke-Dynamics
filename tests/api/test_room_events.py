"""GET /api/game/room/events (docs/plans/active/ROOMS_PLAN.md Phase 2):
events fire on every change, ended and removed members are
disconnected, the caps hold, and the stream never carries room data.

These run against a real uvicorn server on a local port, not
TestClient: TestClient waits for a response to finish before handing
it back, and a live stream never finishes. Each "browser" is its own
httpx.Client, so its own session cookie and its own room member.
"""

from __future__ import annotations

import json
import queue
import socket
import threading
import time
from collections.abc import Callable, Iterator

import httpx
import pytest
import uvicorn

from keystroke_dynamics.api import game as game_api
from keystroke_dynamics.config import settings
from keystroke_dynamics.game.events import RoomEvents
from keystroke_dynamics.game.store import InMemoryGameStore
from keystroke_dynamics.main import app
from tests.api.test_game import SENTENCE_LINE
from tests.touch_lines import tap_line, tap_lines

ORIGIN = {"origin": "http://testserver"}
#: The plan's own bar for "live".
WITHIN = 2.0


@pytest.fixture(scope="module")
def server_url() -> Iterator[str]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "the test server did not start"
        time.sleep(0.01)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


class Stream:
    """One open event stream, read on a background thread."""

    def __init__(self, client: httpx.Client) -> None:
        self.raw = ""
        self.status_code: int | None = None
        self.headers: httpx.Headers | None = None
        self.finished = threading.Event()
        self._opened = threading.Event()
        self._lines: queue.Queue[str] = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._read, args=(client,), daemon=True)
        self._thread.start()
        assert self._opened.wait(5), "the stream request got no response"

    def _read(self, client: httpx.Client) -> None:
        try:
            with client.stream("GET", "/api/game/room/events", timeout=None) as response:
                self.status_code = response.status_code
                self.headers = response.headers
                self._opened.set()
                for line in response.iter_lines():
                    self.raw += line + "\n"
                    if line:
                        self._lines.put(line)
                    if self._stop.is_set():
                        break
        except httpx.HTTPError:
            # Closing the client under a blocked read is how close()
            # hangs up, like a browser tab going away.
            pass
        finally:
            self._opened.set()
            self.finished.set()

    def next_line(self, timeout: float = WITHIN) -> str:
        try:
            return self._lines.get(timeout=timeout)
        except queue.Empty:
            raise AssertionError(f"nothing arrived on the stream within {timeout}s") from None

    def next_event(self, timeout: float = WITHIN) -> dict[str, object]:
        """The next data line, skipping heartbeat comments."""
        deadline = time.monotonic() + timeout
        while True:
            line = self.next_line(max(deadline - time.monotonic(), 0.001))
            if line.startswith("data: "):
                event: dict[str, object] = json.loads(line.removeprefix("data: "))
                return event

    def body(self) -> str:
        """Everything a short, refused response said."""
        assert self.finished.wait(WITHIN), "the response never finished"
        return self.raw

    def expect_quiet(self, seconds: float = 0.3) -> None:
        with pytest.raises(AssertionError, match="nothing arrived"):
            self.next_event(seconds)

    def expect_ended(self) -> None:
        """The last thing sent is "ended", and then the server hangs up."""
        event = self.next_event()
        while event != {"ended": True}:
            assert set(event) == {"version"}
            event = self.next_event()
        assert self.finished.wait(WITHIN), "the server kept the stream open after ending it"


Browser = Callable[[], httpx.Client]


@pytest.fixture
def browser(server_url: str) -> Iterator[Browser]:
    clients: list[httpx.Client] = []

    def new() -> httpx.Client:
        client = httpx.Client(base_url=server_url, headers=ORIGIN, timeout=10)
        clients.append(client)
        return client

    yield new
    for client in clients:
        client.close()


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> RoomEvents:
    """A fresh hub and store per test, so one test's open streams
    can't count against another's caps."""
    return _use(monkeypatch)


def _use(
    monkeypatch: pytest.MonkeyPatch,
    *,
    per_member: int = 3,
    total: int = 300,
    idle_expiry_seconds: float = 7200.0,
) -> RoomEvents:
    hub = RoomEvents(streams_per_member_limit=per_member, streams_total_limit=total)
    store = InMemoryGameStore(
        party_limit=500,
        players_per_party_limit=12,
        attempts_per_party_limit=200,
        idle_expiry_seconds=idle_expiry_seconds,
        members_per_party_limit=12,
        listener=hub,
    )
    monkeypatch.setattr(game_api, "_events", hub)
    monkeypatch.setattr(game_api, "_store", store)
    return hub


def _create_room(client: httpx.Client) -> dict:
    resp = client.post("/api/game/rooms", json={"level": "sentence"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _join(client: httpx.Client, code: str) -> dict:
    resp = client.post(f"/api/game/rooms/{code}/join")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _enroll(client: httpx.Client, name: str) -> dict:
    resp = client.post(
        "/api/game/players", json={"name": name, "training_lines": [SENTENCE_LINE] * 5}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _version(client: httpx.Client) -> int:
    resp = client.get("/api/game/room")
    assert resp.status_code == 200, resp.text
    version: int = resp.json()["version"]
    return version


def _wait_until(condition: Callable[[], bool], what: str) -> None:
    deadline = time.monotonic() + WITHIN
    while not condition():
        assert time.monotonic() < deadline, what
        time.sleep(0.01)


# ---------- opening ----------


def test_a_stream_opens_with_the_rooms_current_version(
    browser: Browser, events: RoomEvents
) -> None:
    host = browser()
    _create_room(host)
    _enroll(host, "Ada")

    stream = Stream(host)

    assert stream.status_code == 200
    assert stream.headers is not None
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert stream.headers["cache-control"] == "no-cache"
    assert stream.headers["x-accel-buffering"] == "no"
    assert stream.next_event() == {"version": _version(host)}
    stream.expect_quiet()


def test_a_browser_with_no_room_gets_a_404_not_a_stream(
    browser: Browser, events: RoomEvents
) -> None:
    stream = Stream(browser())

    assert stream.status_code == 404
    assert stream.finished.wait(WITHIN)
    assert events.open_streams() == 0


def test_a_quiet_stream_sends_heartbeat_comments(
    browser: Browser, events: RoomEvents, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "game_stream_heartbeat_seconds", 0.05)
    host = browser()
    _create_room(host)

    stream = Stream(host)

    assert stream.next_line().startswith("data: ")
    # A comment line: an EventSource ignores it, a proxy sees traffic.
    assert stream.next_line() == ": keep-alive"
    assert stream.next_line() == ": keep-alive"
    # Watching alone neither changes the room nor ends it.
    assert _version(host) == 0


# ---------- events fire on every change ----------


def test_every_kind_of_change_reaches_every_member_within_two_seconds(
    browser: Browser, events: RoomEvents
) -> None:
    host, friend, third = browser(), browser(), browser()
    room = _create_room(host)
    _join(friend, room["code"])
    host_stream, friend_stream = Stream(host), Stream(friend)
    assert host_stream.next_event() == friend_stream.next_event() == {"version": 1}

    ada: dict = {}
    bob: dict = {}
    third_member: dict = {}

    def attack() -> httpx.Response:
        return friend.post(
            "/api/game/attempts",
            json={
                "typist_id": bob["id"],
                "target_id": ada["id"],
                "mode": "attack",
                "events": SENTENCE_LINE,
                "client_attempt_id": "a1",
            },
        )

    changes: list[tuple[str, Callable[[], object]]] = [
        ("a player enrolls", lambda: ada.update(_enroll(host, "Ada"))),
        ("another member enrolls", lambda: bob.update(_enroll(friend, "Bob"))),
        (
            "a rename",
            lambda: host.patch(f"/api/game/players/{ada['id']}", json={"name": "Ada L"}),
        ),
        ("an attack", attack),
        ("a replay", lambda: host.post("/api/game/replay", json={"target_id": bob["id"]})),
        ("a lock", lambda: host.post("/api/game/room/lock", json={"locked": True})),
        ("an unlock", lambda: host.post("/api/game/room/lock", json={"locked": False})),
        ("a join", lambda: third_member.update(_join(third, room["code"]))),
        (
            "the host removing a member",
            lambda: host.delete(f"/api/game/room/members/{third_member['member_id']}"),
        ),
        ("a deleted player", lambda: friend.delete(f"/api/game/room/players/{bob['id']}")),
    ]
    for expected_version, (what, change) in enumerate(changes, start=2):
        result = change()
        if isinstance(result, httpx.Response):
            assert result.is_success, f"{what}: {result.text}"
        for stream in (host_stream, friend_stream):
            assert stream.next_event() == {"version": expected_version}, what
    assert _version(host) == len(changes) + 1


def test_a_member_leaving_is_a_change_for_the_ones_who_stay(
    browser: Browser, events: RoomEvents
) -> None:
    host, friend = browser(), browser()
    room = _create_room(host)
    _join(friend, room["code"])
    host_stream = Stream(host)
    assert host_stream.next_event() == {"version": 1}

    assert friend.post("/api/game/rooms/leave").status_code == 204

    assert host_stream.next_event() == {"version": 2}


def test_reading_the_room_is_not_an_event(browser: Browser, events: RoomEvents) -> None:
    host = browser()
    _create_room(host)
    stream = Stream(host)
    assert stream.next_event() == {"version": 0}

    for _ in range(3):
        _version(host)

    stream.expect_quiet()


def test_a_change_in_one_room_is_not_an_event_in_another(
    browser: Browser, events: RoomEvents
) -> None:
    host, elsewhere = browser(), browser()
    _create_room(host)
    _create_room(elsewhere)
    stream = Stream(host)
    assert stream.next_event() == {"version": 0}

    _enroll(elsewhere, "Stranger")

    stream.expect_quiet()


# ---------- ended and removed members are disconnected ----------


def test_ending_the_room_disconnects_every_member(browser: Browser, events: RoomEvents) -> None:
    host, friend = browser(), browser()
    room = _create_room(host)
    _join(friend, room["code"])
    streams = [Stream(host), Stream(friend), Stream(friend)]

    assert host.post("/api/game/room/end").status_code == 204

    for stream in streams:
        stream.expect_ended()
    _wait_until(lambda: events.open_streams() == 0, "ended streams were never released")


def test_a_removed_member_is_disconnected_and_the_rest_stay_connected(
    browser: Browser, events: RoomEvents
) -> None:
    host, friend = browser(), browser()
    room = _create_room(host)
    friend_view = _join(friend, room["code"])
    host_stream, friend_stream = Stream(host), Stream(friend)
    assert host_stream.next_event() == {"version": 1}

    resp = host.delete(f"/api/game/room/members/{friend_view['member_id']}")
    assert resp.status_code == 204

    friend_stream.expect_ended()
    assert host_stream.next_event() == {"version": 2}
    assert not host_stream.finished.is_set()
    # And the way back in is shut the usual way too.
    assert friend.get("/api/game/room").status_code == 404
    assert Stream(friend).status_code == 404


def test_leaving_disconnects_your_own_streams(browser: Browser, events: RoomEvents) -> None:
    host, friend = browser(), browser()
    room = _create_room(host)
    _join(friend, room["code"])
    friend_tabs = [Stream(friend), Stream(friend)]

    assert friend.post("/api/game/rooms/leave").status_code == 204

    for stream in friend_tabs:
        stream.expect_ended()


def test_the_last_member_leaving_disconnects_their_stream(
    browser: Browser, events: RoomEvents
) -> None:
    host = browser()
    _create_room(host)
    stream = Stream(host)

    assert host.post("/api/game/rooms/leave").status_code == 204

    stream.expect_ended()


def test_an_expired_room_disconnects_its_streams_with_nobody_else_asking(
    browser: Browser, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = _use(monkeypatch, idle_expiry_seconds=0.3)
    monkeypatch.setattr(settings, "game_stream_heartbeat_seconds", 0.05)
    host, friend = browser(), browser()
    room = _create_room(host)
    _join(friend, room["code"])
    streams = [Stream(host), Stream(friend)]

    # No requests from here on: the streams' own heartbeats are the
    # only thing that can notice the idle time running out -- and
    # they must not count as activity that postpones it.
    for stream in streams:
        stream.expect_ended()
    _wait_until(lambda: hub.open_streams() == 0, "expired streams were never released")


def test_a_browser_that_hangs_up_gives_its_slot_back(browser: Browser, events: RoomEvents) -> None:
    host = browser()
    _create_room(host)
    tab = browser()
    tab.cookies.update(host.cookies)
    stream = Stream(tab)
    assert stream.next_event() == {"version": 0}
    assert events.open_streams() == 1

    tab.close()

    # Noticed on the next write to the dead connection.
    _enroll(host, "Ada")
    _wait_until(lambda: events.open_streams() == 0, "a closed stream was never released")


# ---------- the caps hold ----------


def test_a_fourth_stream_from_one_browser_is_refused_with_a_clear_message(
    browser: Browser, events: RoomEvents
) -> None:
    host, friend = browser(), browser()
    room = _create_room(host)
    _join(friend, room["code"])
    tabs = [Stream(host) for _ in range(3)]
    assert all(tab.status_code == 200 for tab in tabs)

    refused = Stream(host)

    assert refused.status_code == 429
    assert "3 live connections" in refused.body()
    assert events.open_streams() == 3
    # It's per browser: the friend still gets theirs.
    assert Stream(friend).status_code == 200
    # The three that were open are untouched.
    _enroll(host, "Ada")
    for tab in tabs:
        assert tab.next_event() == {"version": 1}
        assert tab.next_event() == {"version": 2}


def test_the_total_cap_is_shared_by_every_room(
    browser: Browser, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = _use(monkeypatch, total=4)
    hosts = [browser(), browser(), browser()]
    for host in hosts:
        _create_room(host)
    assert [Stream(hosts[0]).status_code, Stream(hosts[0]).status_code] == [200, 200]
    assert [Stream(hosts[1]).status_code, Stream(hosts[1]).status_code] == [200, 200]

    refused = Stream(hosts[2])

    assert refused.status_code == 503
    assert "at capacity" in refused.body()
    assert hub.open_streams() == 4
    # Refused live updates, not refused the room: polling still works.
    assert hosts[2].get("/api/game/room").status_code == 200


def test_a_refused_stream_frees_nothing_and_a_closed_one_frees_a_slot(
    browser: Browser, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = _use(monkeypatch, per_member=1)
    host = browser()
    _create_room(host)
    tab = browser()
    tab.cookies.update(host.cookies)
    first = Stream(tab)
    assert first.next_event() == {"version": 0}
    for _ in range(3):
        assert Stream(host).status_code == 429
    assert hub.open_streams() == 1

    tab.close()
    _enroll(host, "Ada")
    _wait_until(lambda: hub.open_streams() == 0, "a closed stream was never released")

    assert Stream(host).status_code == 200


# ---------- the stream never includes room data ----------


def test_the_stream_carries_only_version_numbers_and_ended(
    browser: Browser, events: RoomEvents, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "game_stream_heartbeat_seconds", 0.05)
    host, friend = browser(), browser()
    room = _create_room(host)
    friend_view = _join(friend, room["code"])
    stream = Stream(friend)

    ada = _enroll(host, "Ada Lovelace")
    bob = _enroll(friend, "Bob Kahn")
    host.patch(f"/api/game/players/{ada['id']}", json={"name": "Countess Ada"})
    attempt = friend.post(
        "/api/game/attempts",
        json={
            "typist_id": bob["id"],
            "target_id": ada["id"],
            "mode": "attack",
            "events": SENTENCE_LINE,
            "client_attempt_id": "a1",
        },
    )
    assert attempt.status_code == 200, attempt.text
    time.sleep(0.15)  # a few heartbeats' worth
    host.post("/api/game/room/end")
    stream.expect_ended()

    lines = [line for line in stream.raw.split("\n") if line]
    data_lines = [line for line in lines if line.startswith("data: ")]
    assert data_lines, "nothing was sent"
    assert set(lines) - set(data_lines) == {": keep-alive"}
    for line in data_lines:
        payload = json.loads(line.removeprefix("data: "))
        if payload == {"ended": True}:
            continue
        assert list(payload) == ["version"]
        assert type(payload["version"]) is int
    assert data_lines[-1] == 'data: {"ended":true}'

    secrets = [
        "Ada",
        "Bob",
        "Countess",
        room["code"],
        room["id"],
        room["member_id"],
        friend_view["member_id"],
        ada["id"],
        bob["id"],
        attempt.json()["attempt"]["id"],
        attempt.json()["attempt"]["word"],
        str(attempt.json()["attempt"]["distance"]),
        str(ada["threshold"]),
        str(ada["notes"][0]["dur_ms"]),
    ]
    for secret in secrets:
        assert secret not in stream.raw


def test_a_touch_rooms_stream_never_carries_a_tap_map(
    browser: Browser, events: RoomEvents, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Tap maps travel only in GET /room
    # (docs/plans/active/MOBILE_PLAN.md Phase 1 section 7).
    monkeypatch.setattr(settings, "game_stream_heartbeat_seconds", 0.05)
    host, friend = browser(), browser()
    created = host.post("/api/game/rooms", json={"level": "touch", "device_type": "touch"})
    assert created.status_code == 200, created.text
    joined = friend.post(
        f"/api/game/rooms/{created.json()['code']}/join", json={"device_type": "touch"}
    )
    assert joined.status_code == 200, joined.text
    stream = Stream(friend)

    enrolled = host.post(
        "/api/game/players", json={"name": "Ada", "training_lines": tap_lines("ada")}
    )
    assert enrolled.status_code == 200, enrolled.text
    ada = enrolled.json()
    attempt = friend.post(
        "/api/game/attempts",
        json={
            "typist_id": None,
            "target_id": ada["id"],
            "mode": "attack",
            "events": tap_line("grace"),
            "client_attempt_id": "a1",
        },
    )
    assert attempt.status_code == 200, attempt.text
    replay = friend.post("/api/game/replay", json={"target_id": ada["id"]})
    assert replay.status_code == 200, replay.text
    time.sleep(0.15)  # a few heartbeats' worth

    # The room state does have the tap map...
    state = friend.get("/api/game/room").json()
    tap_map = state["players"][0]["tap_map"]
    assert len(tap_map) == 14

    host.post("/api/game/room/end")
    stream.expect_ended()

    # ...and the stream has nothing but version numbers.
    lines = [line for line in stream.raw.split("\n") if line]
    data_lines = [line for line in lines if line.startswith("data: ")]
    assert len(data_lines) >= 4
    assert set(lines) - set(data_lines) <= {": keep-alive"}
    for line in data_lines[:-1]:
        payload = json.loads(line.removeprefix("data: "))
        assert list(payload) == ["version"]
        assert type(payload["version"]) is int
    assert data_lines[-1] == 'data: {"ended":true}'

    for word in ("tap_map", "x_spread", "KeyT", "Space", "touch", "Ada"):
        assert word not in stream.raw
    for point in tap_map:
        for value in (point["x"], point["y"], point["x_spread"], point["y_spread"]):
            if value:
                assert str(value) not in stream.raw
    scores = attempt.json()["attempt"]
    for value in (scores["rhythm"], scores["place"], scores["distance"]):
        assert str(value) not in stream.raw
