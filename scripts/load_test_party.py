"""Load generator for PARTY_LAUNCH_PLAN.md Part 1's Done-when check:
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
PARTY_LAUNCH_PLAN.md's whole identity model is one party per session)
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

#: A clean, consistent typing of "nukiae" (the word level's phrase --
#: the cheapest level to enroll on, keeping the load test's own
#: request volume down without changing what's actually kept in
#: memory per player).
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


def build_one_party(base_url: str, origin: str, players: int, lines_per_player: int) -> None:
    with httpx.Client(base_url=base_url, headers={"origin": origin}, timeout=30.0) as client:
        resp = client.post("/api/game/party", json={"level": "word"})
        resp.raise_for_status()
        for _ in range(players):
            resp = client.post(
                "/api/game/players",
                json={"name": None, "training_lines": [WORD_LINE] * lines_per_player},
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
