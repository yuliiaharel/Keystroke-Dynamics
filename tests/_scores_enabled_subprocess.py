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
verifies the consent rule, column values, and "Delete me"/"New party"
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

    def create_player(name: str, share_scores: bool) -> dict:
        resp = client.post(
            "/api/game/players",
            json={
                "name": name,
                "training_lines": [SENTENCE_LINE] * 5,
                "share_scores": share_scores,
            },
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    attempt_counter = [0]

    def attack(typist_id: str | None, target_id: str, guest_shares: bool = False) -> dict:
        attempt_counter[0] += 1
        resp = client.post(
            "/api/game/attempts",
            json={
                "typist_id": typist_id,
                "target_id": target_id,
                "mode": "attack",
                "events": SENTENCE_LINE,
                "client_attempt_id": f"attack-{attempt_counter[0]}",
                "guest_shares_scores": guest_shares,
            },
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    alice = create_player("Alice", share_scores=True)
    bob = create_player("Bob", share_scores=True)
    carol = create_player("Carol", share_scores=False)
    bot_id = party["targets"][0]["id"]

    # PartyView must show the opt-in as on, with real copy.
    assert party["scores_enabled"] is True
    assert party["consent_label"]
    assert party["consent_explanation"]

    attack(bob["id"], alice["id"])  # both consent -> recorded
    attack(carol["id"], alice["id"])  # typist doesn't consent -> not recorded
    attack(bob["id"], carol["id"])  # target doesn't consent -> not recorded
    attack(bob["id"], bot_id)  # target is simulated -> recorded regardless
    attack(None, alice["id"], guest_shares=True)  # consenting guest -> recorded
    attack(None, alice["id"], guest_shares=False)  # non-consenting guest -> not recorded

    replay_ok = client.post("/api/game/replay", json={"target_id": alice["id"]})
    assert replay_ok.status_code == 200, replay_ok.text  # target consents -> recorded
    replay_blocked = client.post("/api/game/replay", json={"target_id": carol["id"]})
    assert replay_blocked.status_code == 200, replay_blocked.text  # target doesn't -> not recorded

    flush()

    # Read party.score_id the only way anything outside this process
    # can: by party_id showing up on the rows it should have produced.
    # (It's never exposed over the API -- PlayerView/PartyView
    # deliberately don't carry it.)
    with scores_session() as session:
        all_rows = list(session.execute(select(ScoreAttempt)).scalars())
    # bob->alice, bob->bot, guest->alice, replay->alice.
    assert len(all_rows) == 4, [r.mode for r in all_rows]
    party_score_id = all_rows[0].party_id
    assert all(r.party_id == party_score_id for r in all_rows)

    for row in all_rows:
        assert row.device_type == "keyboard"
        assert row.line_id == "sentence"
        # 5 for Alice (created with 5 training lines above); 6
        # (SAMPLE_TRAINING_RUNS) for the one row targeting the bot.
        assert row.training_lines in (5, 6)
        assert row.consent_version == "1"
        assert row.scoring_version
        assert row.outcome in ("pass", "fail")
        # No disallowed value snuck through -- test_models.py checks
        # the column *set* exhaustively; this checks these particular
        # rows' values are all from the real request, not placeholders.
        assert row.rhythm is not None
        assert row.pace is not None

    modes = sorted(r.mode for r in all_rows)
    assert modes == ["attack", "attack", "attack", "replay"]
    # bob->alice, guest->alice, replay->alice are all real-player
    # targets; bob->bot is the only simulated one. No permanent target
    # is ever attacked here (bot_id is always party["targets"][0], a
    # sample bot -- see _party_view), so "permanent" never appears
    # regardless of whether a recording happens to exist locally.
    kinds = sorted(r.target_kind for r in all_rows)
    assert kinds == ["player", "player", "player", "simulated"]

    # "Delete me": removes Alice's rows (she's the target on 3 of the
    # 4), leaving only the bob->bot row.
    deleted = client.delete(f"/api/game/players/{alice['id']}")
    assert deleted.status_code == 204
    flush()
    remaining = row_ids_for(party_score_id)
    assert len(remaining) == 1, remaining

    # "New party": removes everything left for this party.
    reset = client.post("/api/game/party/reset")
    assert reset.status_code == 204
    flush()
    assert row_ids_for(party_score_id) == set()

print("OK")
