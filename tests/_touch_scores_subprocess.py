"""Not a pytest module -- a standalone script run in a fresh
subprocess by tests/scores/test_api_integration.py, for the same
reason as _scores_enabled_subprocess.py: score collection is switched
on by a setting that's read once, at import.

argv[1] is the real scores test database URL.

Drives a touch room over real HTTP with score collection on
(docs/plans/active/MOBILE_PLAN.md Phase 1 section 6), then reads the
real scores database and the process's own logs to confirm:
- touch attempts are stored as device_type "touch" on the "touch"
  line, with rhythm, place, and total filled in
- a grip test is stored as its own mode
- same_keyboard is true on the target's own phone, false from another
- no tap position or timing reaches a stored row or a log line
- a keyboard room's rows still leave place empty

Prints "OK" and exits 0 on success.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Run by path, so the repository root isn't on sys.path yet -- and
# this script shares tests/touch_lines.py with the pytest modules.
sys.path.insert(0, str(Path(__file__).parent.parent))

scores_url = sys.argv[1]

os.environ["ENABLE_ACCOUNTS"] = "false"
os.environ["DEBUG"] = "true"
os.environ["ALLOWED_ORIGIN"] = "http://testserver"
os.environ["SCORES_DATABASE_URL"] = scores_url
os.environ["SCORES_WRITER_BATCH_INTERVAL_SECONDS"] = "0.05"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("SESSION_SECRET", None)


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


# Everything, from every logger, at the most talkative level -- the
# database driver's own statement logging included.
capture = _Capture()
logging.getLogger().addHandler(capture)
logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger("sqlalchemy.engine").setLevel(logging.DEBUG)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from keystroke_dynamics.game.scoring import SCORING_VERSION  # noqa: E402
from keystroke_dynamics.main import app  # noqa: E402
from keystroke_dynamics.scores.db import scores_session  # noqa: E402
from keystroke_dynamics.scores.models import ScoreAttempt  # noqa: E402
from keystroke_dynamics.scores.writer import score_writer  # noqa: E402
from tests.api.test_game import SENTENCE_LINE  # noqa: E402
from tests.touch_lines import TOUCH_PHRASE, tap_line, tap_lines  # noqa: E402

ORIGIN = {"origin": "http://testserver"}
TOUCH = {"device_type": "touch"}


def flush() -> None:
    score_writer.stop()
    score_writer.start()


def rows_for(party_id: str) -> list[ScoreAttempt]:
    with scores_session() as session:
        return list(
            session.execute(select(ScoreAttempt).where(ScoreAttempt.party_id == party_id)).scalars()
        )


def all_rows() -> list[ScoreAttempt]:
    with scores_session() as session:
        return list(session.execute(select(ScoreAttempt)).scalars())


#: Every raw number this script submits, so it can check afterward
#: that none of them was stored or logged.
submitted: list[float] = []


def remember(events: list[dict]) -> list[dict]:
    for event in events:
        submitted.append(event["t_ms"])
        if "dx" in event:
            submitted.extend([event["dx"], event["dy"]])
    return events


counter = [0]


def attempt(
    client: TestClient, typist_id: str | None, target_id: str, mode: str, events: list[dict]
) -> dict:
    counter[0] += 1
    resp = client.post(
        "/api/game/attempts",
        json={
            "typist_id": typist_id,
            "target_id": target_id,
            "mode": mode,
            "events": remember(events),
            "client_attempt_id": f"t{counter[0]}",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["attempt"]


def enroll(client: TestClient, name: str) -> dict:
    lines = [remember(line) for line in tap_lines(name.lower())]
    resp = client.post("/api/game/players", json={"name": name, "training_lines": lines})
    assert resp.status_code == 200, resp.text
    return resp.json()


with (
    TestClient(app, headers=ORIGIN) as phone,
    TestClient(app, headers=ORIGIN) as other_phone,
    TestClient(app, headers=ORIGIN) as laptop,
):
    room = phone.post("/api/game/rooms", json={"level": "touch", **TOUCH}).json()
    assert room["scores_enabled"] is True
    joined = other_phone.post(f"/api/game/rooms/{room['code']}/join", json=TOUCH)
    assert joined.status_code == 200, joined.text

    alice = enroll(phone, "Alice")
    amy = enroll(phone, "Amy")
    bob = enroll(other_phone, "Bob")
    sample_id = room["targets"][0]["id"]

    own = attempt(phone, alice["id"], alice["id"], "self", tap_line("alice", line=9))
    grip = attempt(
        phone, alice["id"], alice["id"], "grip", tap_line("alice", line=8, shift=(0.5, -0.5))
    )
    same_phone = attempt(phone, amy["id"], alice["id"], "attack", tap_line("amy", line=9))
    other = attempt(other_phone, bob["id"], alice["id"], "attack", tap_line("bob", line=9))
    guest = attempt(other_phone, None, alice["id"], "attack", tap_line("guest", line=0))
    versus_sample = attempt(phone, alice["id"], sample_id, "attack", tap_line("alice", line=7))
    messy = attempt(
        phone, amy["id"], alice["id"], "attack", tap_line("amy", line=6)[: len(TOUCH_PHRASE)]
    )
    replayed = phone.post("/api/game/replay", json={"target_id": alice["id"]})
    assert replayed.status_code == 200, replayed.text
    replay = replayed.json()["attempt"]

    assert own["passed"] is True and grip["passed"] is False
    assert messy["word"] == "Too messy"
    flush()

    stored = all_rows()
    assert len(stored) == 8, [r.mode for r in stored]
    party_score_id = stored[0].party_id
    assert all(r.party_id == party_score_id for r in stored)
    for row in stored:
        assert row.device_type == "touch"
        assert row.line_id == "touch"
        assert row.scoring_version == SCORING_VERSION == "3"
        assert row.consent_version == "2"
        # 4 for Alice (enrolled above with 4 lines), 6 for the sample.
        assert row.training_lines in (4, 6)

    def stored_row(mode: str, **where: object) -> ScoreAttempt:
        matches = [
            r
            for r in stored
            if r.mode == mode and all(getattr(r, k) == v for k, v in where.items())
        ]
        assert len(matches) == 1, (mode, where, [(r.mode, r.total) for r in stored])
        return matches[0]

    # Each response's rhythm, place, and total are what was stored.
    for view, row in (
        (own, stored_row("self")),
        (grip, stored_row("grip")),
        (replay, stored_row("replay")),
        (versus_sample, stored_row("attack", target_kind="simulated")),
    ):
        assert row.rhythm == view["rhythm"] is not None
        assert row.place == view["place"] is not None
        assert row.total == view["distance"] is not None
        assert row.limit_value == view["threshold"]
        assert row.compared_features == 84
        assert row.outcome == ("pass" if view["passed"] else "fail")
    # Rhythm, place, and total are three different numbers: total is
    # not just a copy of rhythm, as it is for a keyboard row.
    grip_row = stored_row("grip")
    assert grip_row.rhythm < grip_row.total < grip_row.place

    # The one unusable line: no scores at all, and still recorded.
    unusable = stored_row("attack", outcome="unusable")
    assert unusable.rhythm is None and unusable.place is None and unusable.total is None
    assert 0 < unusable.compared_features < 58
    assert unusable.pace is not None

    # same_keyboard, as stored. True: Alice's own two lines and Amy's
    # two attacks, all from the phone Alice enrolled on. False: Bob's
    # and the Guest's, from the other phone. Null: the sample target
    # and the replay.
    assert sorted((r.mode, r.same_keyboard) for r in stored if r.target_kind == "player") == [
        ("attack", False),
        ("attack", False),
        ("attack", True),
        ("attack", True),
        ("grip", True),
        ("replay", None),
        ("self", True),
    ]
    assert stored_row("attack", target_kind="simulated").same_keyboard is None
    assert other["same_keyboard"] is False and same_phone["same_keyboard"] is True
    assert guest["same_keyboard"] is False

    # Nothing raw was stored: no value in any row is a submitted tap
    # position or timing.
    # (Minus 0.0: every line starts at t=0, and a replay's place score
    # is exactly 0 too, so that one value proves nothing either way.)
    raw = set(submitted) - {0.0}
    assert len(raw) > 500
    numeric_columns = ("rhythm", "place", "total", "limit_value", "pace")
    for row in stored:
        for column in numeric_columns:
            assert getattr(row, column) not in raw, (column, getattr(row, column))

    # A keyboard room in the same process: its rows are still keyboard
    # rows, with rhythm equal to total and no place.
    laptop.post("/api/game/rooms", json={"level": "sentence"})
    kate = laptop.post(
        "/api/game/players", json={"name": "Kate", "training_lines": [SENTENCE_LINE] * 5}
    ).json()
    keyboard_attempt = laptop.post(
        "/api/game/attempts",
        json={
            "typist_id": kate["id"],
            "target_id": kate["id"],
            "mode": "self",
            "events": SENTENCE_LINE,
            "client_attempt_id": "k1",
        },
    )
    assert keyboard_attempt.status_code == 200, keyboard_attempt.text
    flush()
    keyboard_rows = [r for r in all_rows() if r.device_type == "keyboard"]
    assert len(keyboard_rows) == 1
    assert keyboard_rows[0].line_id == "sentence"
    assert keyboard_rows[0].place is None
    assert keyboard_rows[0].rhythm == keyboard_rows[0].total is not None
    assert keyboard_rows[0].scoring_version == "3"

    # "Delete me" works for a touch player: Alice is the target of
    # seven of the eight rows and the typist of the eighth.
    assert phone.delete(f"/api/game/players/{alice['id']}").status_code == 204
    flush()
    assert rows_for(party_score_id) == []

# Nothing raw was logged either, at any level, by anything.
logged = "\n".join(capture.lines)
assert "INSERT INTO score_attempts" in logged, "the capture missed the driver's own logging"
for value in raw:
    assert repr(value) not in logged, value
for word in ("'dx'", '"dx"', "dx=", "t_ms", "tap_x", "KeyT"):
    assert word not in logged, word

print("OK")
