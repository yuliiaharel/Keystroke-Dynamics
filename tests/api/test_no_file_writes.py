"""Confirms the Done-when requirement "nothing writes files during a
request" by intercepting every filesystem write while a request is in
flight, rather than just trusting that nothing in the source calls
open() -- the plan's raw-data rule (events processed in memory only,
never persisted or logged) is this same guarantee, made explicit.
"""

from __future__ import annotations

import builtins
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

_WRITE_MODE_CHARS = frozenset("wax+")

_real_open = builtins.open


def _guarded_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
    if any(c in _WRITE_MODE_CHARS for c in mode):
        raise AssertionError(f"request attempted to open {file!r} in write mode {mode!r}")
    return _real_open(file, mode, *args, **kwargs)


@pytest.fixture
def no_file_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builtins, "open", _guarded_open)
    monkeypatch.setattr(Path, "write_text", _fail_write_text)
    monkeypatch.setattr(Path, "write_bytes", _fail_write_bytes)


def _fail_write_text(self: Path, *args: Any, **kwargs: Any) -> int:
    raise AssertionError(f"request attempted Path.write_text on {self!r}")


def _fail_write_bytes(self: Path, *args: Any, **kwargs: Any) -> int:
    raise AssertionError(f"request attempted Path.write_bytes on {self!r}")


SAMPLE = {
    "events": [
        {"code": "KeyA", "action": "down", "t_ms": 0},
        {"code": "KeyA", "action": "up", "t_ms": 90},
    ]
}


def test_register_login_sample_verify_and_delete_write_no_files(
    client: TestClient, no_file_writes: None
) -> None:
    credentials = {"username": "dana", "password": "correct-password-123"}

    assert client.post("/api/register", json=credentials).status_code == 201
    assert client.post("/api/login", json=credentials).status_code == 200
    assert client.post("/api/profile/samples", json=SAMPLE).status_code == 200
    assert client.post("/api/profile/verify", json=SAMPLE).status_code == 200
    assert client.delete("/api/profile").status_code == 204
    assert client.post("/api/logout").status_code == 204


_WORD_LINE = [
    {"code": "KeyN", "action": "down", "t_ms": 0.0},
    {"code": "KeyN", "action": "up", "t_ms": 80.0},
    {"code": "KeyU", "action": "down", "t_ms": 230.0},
    {"code": "KeyU", "action": "up", "t_ms": 310.0},
    {"code": "KeyK", "action": "down", "t_ms": 460.0},
    {"code": "KeyK", "action": "up", "t_ms": 540.0},
    {"code": "KeyI", "action": "down", "t_ms": 690.0},
    {"code": "KeyI", "action": "up", "t_ms": 770.0},
    {"code": "KeyA", "action": "down", "t_ms": 920.0},
    {"code": "KeyA", "action": "up", "t_ms": 1000.0},
    {"code": "KeyE", "action": "down", "t_ms": 1150.0},
    {"code": "KeyE", "action": "up", "t_ms": 1230.0},
]


def test_a_full_game_writes_no_files(client: TestClient, no_file_writes: None) -> None:
    """The anonymous game's own version of the same guarantee: raw
    keystroke events are processed in memory and discarded, never
    persisted anywhere -- not just "never stored in a database",
    which public mode has none of anyway."""
    party = client.post("/api/game/party", json={"level": "word"}).json()
    player = client.post(
        "/api/game/players", json={"name": "Dana", "training_lines": [_WORD_LINE] * 5}
    ).json()
    assert (
        client.post(
            "/api/game/attempts",
            json={
                "typist_id": None,
                "target_id": player["id"],
                "mode": "attack",
                "events": _WORD_LINE,
                "client_attempt_id": "a1",
            },
        ).status_code
        == 200
    )
    assert client.post("/api/game/replay", json={"target_id": player["id"]}).status_code == 200
    assert (
        client.patch(f"/api/game/players/{player['id']}", json={"name": "Dana2"}).status_code == 200
    )
    assert client.delete(f"/api/game/players/{player['id']}").status_code == 204
    assert client.post("/api/game/party/reset").status_code == 204
    assert party["phrase"] == "nukiae"  # sanity: the flow above actually ran
