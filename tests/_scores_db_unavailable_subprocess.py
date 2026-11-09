"""Not a pytest module -- a standalone script run in a fresh
subprocess by tests/scores/test_db_unavailable.py. Needs its own
process for the same reason as _public_mode_subprocess.py/
_debug_false_subprocess.py/_scores_enabled_subprocess.py: config.py's
settings (and the module-level score_writer) are already built by the
time tests/conftest.py's own imports run.

PARTY_LAUNCH_PLAN.md section 10's own "Done when" bullet: "a stopped,
slow, or unavailable database doesn't delay requests or break a
game." SCORES_DATABASE_URL here points at port 1 on localhost --
nothing listens there, so the OS refuses the connection immediately
(a non-routable address would instead hang for a slow OS-level
connect timeout, which is exactly what this script needs to avoid to
stay fast and deterministic) -- giving the background writer and
retention task a database that is genuinely unavailable for the
script's entire run, on every attempt.

Drives a full game over real HTTP -- party, enrollment (opted in),
attack (opted in), replay, deletion, reset -- timing every request,
and asserts each one stays fast despite the background writer
failing, in the background, on every single batch it tries to flush.

Prints "OK" and exits 0 on success. Any failed assertion or exception
propagates as a nonzero exit with a traceback on stderr.
"""

from __future__ import annotations

import os
import time

os.environ["ENABLE_ACCOUNTS"] = "false"
os.environ["DEBUG"] = "true"
os.environ["ALLOWED_ORIGIN"] = "http://testserver"
os.environ["SCORES_DATABASE_URL"] = "postgresql+psycopg://user:pass@127.0.0.1:1/nope"
os.environ["SCORES_WRITER_BATCH_INTERVAL_SECONDS"] = "0.02"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("SESSION_SECRET", None)

from fastapi.testclient import TestClient  # noqa: E402

from keystroke_dynamics.main import app  # noqa: E402

WORD_LINE = [
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

#: Generous even on a slow CI runner -- the point isn't to nail an
#: exact millisecond budget, it's to catch "the request silently
#: blocked on a dead database connection", which would show up as
#: several *seconds*, not a close call at this boundary.
MAX_REQUEST_SECONDS = 2.0


def timed(label: str, fn) -> None:  # type: ignore[no-untyped-def]
    start = time.monotonic()
    fn()
    elapsed = time.monotonic() - start
    assert elapsed < MAX_REQUEST_SECONDS, f"{label} took {elapsed:.2f}s with the database down"


with TestClient(app, headers={"origin": "http://testserver"}) as client:
    party = {}

    def create_party() -> None:
        resp = client.post("/api/game/party", json={"level": "word"})
        assert resp.status_code == 200, resp.text
        party.update(resp.json())

    timed("creating a party", create_party)

    player = {}

    def create_player() -> None:
        resp = client.post(
            "/api/game/players",
            json={"name": "Alice", "training_lines": [WORD_LINE] * 5, "share_scores": True},
        )
        assert resp.status_code == 200, resp.text
        player.update(resp.json())

    timed("enrolling a player", create_player)

    def attack() -> None:
        resp = client.post(
            "/api/game/attempts",
            json={
                "typist_id": None,
                "target_id": player["id"],
                "mode": "attack",
                "events": WORD_LINE,
                "client_attempt_id": "attack-1",
                "guest_shares_scores": True,
            },
        )
        assert resp.status_code == 200, resp.text

    # Give the background writer a few failed-batch cycles first, so
    # this attempt's own enqueue lands while it's actively mid-retry,
    # not just once before anything has had a chance to break.
    time.sleep(0.2)
    timed("an opted-in attack with the database down", attack)

    def replay() -> None:
        resp = client.post("/api/game/replay", json={"target_id": player["id"]})
        assert resp.status_code == 200, resp.text

    timed("a replay with the database down", replay)

    def delete_player() -> None:
        resp = client.delete(f"/api/game/players/{player['id']}")
        assert resp.status_code == 204, resp.text

    timed("deleting a player with the database down", delete_player)

    def reset_party() -> None:
        resp = client.post("/api/game/party/reset")
        assert resp.status_code == 204, resp.text

    timed("resetting the party with the database down", reset_party)

print("OK")
