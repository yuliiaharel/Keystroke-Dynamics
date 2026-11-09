"""Load generator for docs/plans/done/PARTY_LAUNCH_PLAN.md Part 1's Done-when check:
"A short load test against a container limited to 512 MiB, with 100
parties at the player limit, stays within memory."

This script only generates the load -- it has no visibility into the
server process's own memory. Run it against a live instance (e.g. a
container started with --memory=512m) while something else polls
that container's actual memory from outside (`docker stats`); see
scripts/run_party_load_test.sh, which does both and reports peak
memory.

    uv run python3 scripts/load_test_party.py --base-url http://127.0.0.1:8000

Each party gets its own httpx.Client (so its own cookie jar --
docs/plans/done/PARTY_LAUNCH_PLAN.md's whole identity model is one party per session)
and is built up to the configured player limit, each player enrolled
with a handful of training lines through the real backend pipeline --
the same shape a real party actually reaches in memory, not a
synthetic shortcut.
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx

#: A clean, consistent typing of the sentence level's own phrase --
#: the cheapest remaining level to enroll on, keeping the load test's
#: own request volume down without changing what's actually kept in
#: memory per player.
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


def build_one_party(base_url: str, origin: str, players: int, lines_per_player: int) -> None:
    with httpx.Client(base_url=base_url, headers={"origin": origin}, timeout=30.0) as client:
        resp = client.post("/api/game/party", json={"level": "sentence"})
        resp.raise_for_status()
        for _ in range(players):
            resp = client.post(
                "/api/game/players",
                json={"name": None, "training_lines": [SENTENCE_LINE] * lines_per_player},
            )
            resp.raise_for_status()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--origin", default=None, help="defaults to --base-url")
    parser.add_argument("--parties", type=int, default=100)
    parser.add_argument("--players-per-party", type=int, default=12)
    parser.add_argument("--lines-per-player", type=int, default=5)
    args = parser.parse_args()
    origin = args.origin or args.base_url

    start = time.monotonic()
    for i in range(args.parties):
        build_one_party(args.base_url, origin, args.players_per_party, args.lines_per_player)
        if (i + 1) % 10 == 0:
            elapsed = time.monotonic() - start
            print(f"{i + 1}/{args.parties} parties built ({elapsed:.1f}s elapsed)", file=sys.stderr)

    elapsed = time.monotonic() - start
    total_players = args.parties * args.players_per_party
    print(
        f"Built {args.parties} parties x {args.players_per_party} players "
        f"({total_players} players total) in {elapsed:.1f}s"
    )


if __name__ == "__main__":
    main()
