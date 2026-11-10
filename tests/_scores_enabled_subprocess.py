"""Not a pytest module -- a standalone script run in a fresh
subprocess by tests/scores/test_api_integration.py. Needs its own
process for the same reason as _public_mode_subprocess.py/
_debug_false_subprocess.py: config.py's settings (and api/game.py's
module-level score_writer/_store) are already built with no
SCORES_DATABASE_URL by the time tests/conftest.py's own imports run,
and there's no way to rebuild them with a different setting from
inside that same process.

argv[1] is the real scores test database URL (tests/scores/conftest.py's
own SCORES_TEST_DATABASE_URL, passed in rather than hardcoded here, so
this script never carries its own copy to drift out of sync).

Drives a full game over real HTTP (never scores anything itself) and
verifies every attempt is stored, the column values, and "Delete me"/"New party"
cascades by querying the real scores database afterward -- the same
database the app just wrote to, not a mock.

Prints "OK" and exits 0 on success. Any failed assertion or exception
propagates as a nonzero exit with a traceback on stderr.
"""

from __future__ import annotations

import os
import sys

scores_url = sys.argv[1]

os.environ["ENABLE_ACCOUNTS"] = "false"
os.environ["DEBUG"] = "true"
os.environ["ALLOWED_ORIGIN"] = "http://testserver"
os.environ["SCORES_DATABASE_URL"] = scores_url
# Fast enough that a .stop()/.start() checkpoint (see below) isn't
# even needed to observe a write, but checkpoints are used anyway for
# a deterministic flush rather than a timing-based wait.
os.environ["SCORES_WRITER_BATCH_INTERVAL_SECONDS"] = "0.05"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("SESSION_SECRET", None)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from keystroke_dynamics.main import app  # noqa: E402
from keystroke_dynamics.scores.db import scores_session  # noqa: E402
from keystroke_dynamics.scores.models import ScoreAttempt  # noqa: E402
from keystroke_dynamics.scores.writer import score_writer  # noqa: E402

SENTENCE_PHRASE = "quiet rhythm hides in every small habit of your hands"


def _char_to_code(ch: str) -> str:
    return "Space" if ch == " " else f"Key{ch.upper()}"


def _line_for(phrase: str, *, hold_ms: float = 80.0, gap_ms: float = 150.0) -> list[dict]:
    events: list[dict] = []
    t = 0.0
    for i, ch in enumerate(phrase):
        if i > 0:
            t += gap_ms
        code = _char_to_code(ch)
        events.append({"code": code, "action": "down", "t_ms": t})
        events.append({"code": code, "action": "up", "t_ms": t + hold_ms})
    return events


SENTENCE_LINE = _line_for(SENTENCE_PHRASE)


def flush() -> None:
    """A deterministic sync point: stop()'s own best-effort flush,
    then start() again so the rest of the script can keep going."""
    score_writer.stop()
    score_writer.start()


def row_ids_for(party_id: str) -> set[str]:
    with scores_session() as session:
        return {
            row.id
            for row in session.execute(
                select(ScoreAttempt).where(ScoreAttempt.party_id == party_id)
            ).scalars()
        }


with TestClient(app, headers={"origin": "http://testserver"}) as client:
    party = client.post("/api/game/party", json={"level": "sentence"}).json()
    party_score_id = None  # filled in once we can read it back -- see below

    def create_player(name: str) -> dict:
        resp = client.post(
            "/api/game/players",
            json={"name": name, "training_lines": [SENTENCE_LINE] * 5},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    attempt_counter = [0]

    def attack(typist_id: str | None, target_id: str) -> dict:
        attempt_counter[0] += 1
        resp = client.post(
            "/api/game/attempts",
            json={
                "typist_id": typist_id,
                "target_id": target_id,
                "mode": "attack",
                "events": SENTENCE_LINE,
                "client_attempt_id": f"attack-{attempt_counter[0]}",
            },
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    alice = create_player("Alice")
    bob = create_player("Bob")
    carol = create_player("Carol")
    bot_id = party["targets"][0]["id"]

    # PartyView says collection is on, and carries nothing left over
    # from the old opt-in.
    assert party["scores_enabled"] is True
    assert "consent_label" not in party
    assert "consent_explanation" not in party

    # Every attempt is recorded -- nobody is asked, so there's no
    # combination of typist and target that isn't stored.
    attack(bob["id"], alice["id"])
    attack(carol["id"], alice["id"])
    attack(bob["id"], carol["id"])
    attack(bob["id"], bot_id)
    attack(None, alice["id"])  # a Guest
    attack(None, alice["id"])  # a second Guest attempt, its own row

    for replay_target in (alice, carol):
        replayed = client.post("/api/game/replay", json={"target_id": replay_target["id"]})
        assert replayed.status_code == 200, replayed.text

    # A second browser joins the same room by its code and attacks
    # Alice from its own keyboard (docs/plans/active/ROOMS_PLAN.md
    # Phase 1 section 5) -- the one row here with same_keyboard False.
    other_browser = TestClient(app, headers={"origin": "http://testserver"})
    joined = other_browser.post(f"/api/game/rooms/{party['code']}/join")
    assert joined.status_code == 200, joined.text
    dave = other_browser.post(
        "/api/game/players",
        json={"name": "Dave", "training_lines": [SENTENCE_LINE] * 5},
    ).json()
    from_other_keyboard = other_browser.post(
        "/api/game/attempts",
        json={
            "typist_id": dave["id"],
            "target_id": alice["id"],
            "mode": "attack",
            "events": SENTENCE_LINE,
            "client_attempt_id": "other-keyboard-1",
        },
    )
    assert from_other_keyboard.status_code == 200, from_other_keyboard.text
    assert from_other_keyboard.json()["attempt"]["same_keyboard"] is False

    flush()

    # Read party.score_id the only way anything outside this process
    # can: by party_id showing up on the rows it should have produced.
    # (It's never exposed over the API -- PlayerView/PartyView
    # deliberately don't carry it.)
    with scores_session() as session:
        all_rows = list(session.execute(select(ScoreAttempt)).scalars())
    # Six attacks and two replays from the first browser, and one
    # attack from the second: one row each.
    assert len(all_rows) == 9, [r.mode for r in all_rows]
    party_score_id = all_rows[0].party_id
    assert all(r.party_id == party_score_id for r in all_rows)

    for row in all_rows:
        assert row.device_type == "keyboard"
        assert row.line_id == "sentence"
        # 5 for Alice and Carol (created with 5 training lines
        # above); 6 (SAMPLE_TRAINING_RUNS) for the one row targeting
        # the bot.
        assert row.training_lines in (5, 6)
        assert row.consent_version == "2"
        assert row.scoring_version
        assert row.outcome in ("pass", "fail")
        # No disallowed value snuck through -- test_models.py checks
        # the column *set* exhaustively; this checks these particular
        # rows' values are all from the real request, not placeholders.
        assert row.rhythm is not None
        assert row.pace is not None

    modes = sorted(r.mode for r in all_rows)
    assert modes == ["attack"] * 7 + ["replay"] * 2
    # Every target is a real player except bob->bot, the only
    # simulated one. No permanent target
    # is ever attacked here (bot_id is always party["targets"][0], a
    # sample bot -- see _party_view), so "permanent" never appears
    # regardless of whether a recording happens to exist locally.
    kinds = sorted(r.target_kind for r in all_rows)
    assert kinds == ["player"] * 8 + ["simulated"]

    # The two Guest attempts and the two replays can't be linked to
    # each other: each got its own typist_id, shared with no other row.
    typist_ids = [r.typist_id for r in all_rows]
    assert len(set(typist_ids)) == 7, typist_ids  # bob, carol, dave, 2 guests, 2 replays

    # same_keyboard, as stored: True for the five attacks on a player
    # from the browser that enrolled them (bob->alice, carol->alice,
    # bob->carol, and the two Guest attempts), False for dave->alice
    # (the second browser), null for the bot target and for replays.
    stored_same_keyboard = sorted(
        (r.mode, r.target_kind, r.same_keyboard) for r in all_rows if r.same_keyboard is not None
    )
    assert (
        stored_same_keyboard == [("attack", "player", False)] + [("attack", "player", True)] * 5
    ), stored_same_keyboard
    not_applicable = sorted((r.mode, r.target_kind) for r in all_rows if r.same_keyboard is None)
    assert not_applicable == [
        ("attack", "simulated"),
        ("replay", "player"),
        ("replay", "player"),
    ], not_applicable

    # "Delete me": removes Alice's rows (she's the target on 6 of the
    # 9), leaving bob->carol, bob->bot, and replay->carol.
    deleted = client.delete(f"/api/game/players/{alice['id']}")
    assert deleted.status_code == 204
    flush()
    remaining = row_ids_for(party_score_id)
    assert len(remaining) == 3, remaining

    # A member leaving takes their own players' rows with them: Dave
    # attacks the bot (recorded), then his browser leaves.
    dave_vs_bot = other_browser.post(
        "/api/game/attempts",
        json={
            "typist_id": dave["id"],
            "target_id": bot_id,
            "mode": "attack",
            "events": SENTENCE_LINE,
            "client_attempt_id": "other-keyboard-2",
        },
    )
    assert dave_vs_bot.status_code == 200, dave_vs_bot.text
    flush()
    assert len(row_ids_for(party_score_id)) == 4
    assert other_browser.post("/api/game/rooms/leave").status_code == 204
    flush()
    assert row_ids_for(party_score_id) == remaining

    # "New party": the last member leaving ends the room, which
    # removes everything left for it.
    reset = client.post("/api/game/party/reset")
    assert reset.status_code == 204
    flush()
    assert row_ids_for(party_score_id) == set()

print("OK")
