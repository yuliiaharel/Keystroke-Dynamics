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

docs/plans/active/ROOMS_PLAN.md Phase 2 extends it: with
--stream-rooms N, the first N of those parties each get a second
member browser, and both browsers hold --streams-per-member live-update
streams open (50 rooms x 2 browsers x 3 streams = 300, the app's own
cap). While they're open it changes every one of those rooms once and
checks that all the streams heard, then checks that one stream more is
refused.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field

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


@dataclass(frozen=True)
class BuiltParty:
    code: str
    host_cookies: dict[str, str]


def build_one_party(base_url: str, origin: str, players: int, lines_per_player: int) -> BuiltParty:
    with httpx.Client(base_url=base_url, headers={"origin": origin}, timeout=30.0) as client:
        resp = client.post("/api/game/party", json={"level": "sentence"})
        resp.raise_for_status()
        code = resp.json()["code"]
        for _ in range(players):
            resp = client.post(
                "/api/game/players",
                json={"name": None, "training_lines": [SENTENCE_LINE] * lines_per_player},
            )
            resp.raise_for_status()
        return BuiltParty(code=code, host_cookies=dict(client.cookies))


@dataclass
class OpenStream:
    """One held-open live-update stream and what it has heard."""

    versions: list[int] = field(default_factory=list)
    heartbeats: int = 0
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    opened: asyncio.Event = field(default_factory=asyncio.Event)

    async def read(self, client: httpx.AsyncClient) -> None:
        async with client.stream("GET", "/api/game/room/events", timeout=None) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith(":"):
                    self.heartbeats += 1
                elif line.startswith("data: "):
                    self.versions.append(json.loads(line.removeprefix("data: "))["version"])
                    self.opened.set()
                    if len(self.versions) > 1:
                        self.changed.set()


async def hold_streams(
    base_url: str,
    origin: str,
    parties: list[BuiltParty],
    streams_per_member: int,
    hold_seconds: float,
) -> None:
    """Opens the streams, changes every room once, and holds the
    streams open for hold_seconds so the server's memory (read from
    outside, by run_party_load_test.sh) includes them at rest."""
    clients: list[httpx.AsyncClient] = []
    hosts: list[httpx.AsyncClient] = []
    streams: list[OpenStream] = []
    tasks: list[asyncio.Task[None]] = []
    try:
        for party in parties:
            host = httpx.AsyncClient(
                base_url=base_url, headers={"origin": origin}, cookies=party.host_cookies
            )
            friend = httpx.AsyncClient(base_url=base_url, headers={"origin": origin})
            clients += [host, friend]
            hosts.append(host)
            (await friend.post(f"/api/game/rooms/{party.code}/join")).raise_for_status()
            for client in (host, friend):
                for _ in range(streams_per_member):
                    stream = OpenStream()
                    streams.append(stream)
                    tasks.append(asyncio.create_task(stream.read(client)))

        await asyncio.wait_for(asyncio.gather(*(s.opened.wait() for s in streams)), timeout=30)
        print(f"{len(streams)} streams open across {len(parties)} rooms")

        start = time.monotonic()
        for host in hosts:
            (await host.post("/api/game/room/lock", json={"locked": True})).raise_for_status()
        await asyncio.wait_for(asyncio.gather(*(s.changed.wait() for s in streams)), timeout=10)
        print(
            f"One change in each room reached all {len(streams)} streams "
            f"{time.monotonic() - start:.2f}s after the first change was sent"
        )

        extra = await hosts[0].get("/api/game/room/events")
        print(f"One stream more than that: HTTP {extra.status_code} ({extra.text.strip()})")

        print(f"Holding the streams open for {hold_seconds:.0f}s...")
        await asyncio.sleep(hold_seconds)
        failed = [t for t in tasks if t.done()]
        if failed:
            raise RuntimeError(f"{len(failed)} streams closed early: {failed[0].exception()!r}")
        print(
            f"All {len(streams)} streams still open after {hold_seconds:.0f}s; "
            f"heartbeats seen per stream: {min(s.heartbeats for s in streams)} to "
            f"{max(s.heartbeats for s in streams)}"
        )
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for client in clients:
            await client.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--origin", default=None, help="defaults to --base-url")
    parser.add_argument("--parties", type=int, default=100)
    parser.add_argument("--players-per-party", type=int, default=12)
    parser.add_argument("--lines-per-player", type=int, default=5)
    parser.add_argument(
        "--stream-rooms", type=int, default=0, help="how many of the parties also hold streams"
    )
    parser.add_argument("--streams-per-member", type=int, default=3)
    parser.add_argument("--stream-hold-seconds", type=float, default=45.0)
    args = parser.parse_args()
    origin = args.origin or args.base_url

    start = time.monotonic()
    built: list[BuiltParty] = []
    for i in range(args.parties):
        built.append(
            build_one_party(args.base_url, origin, args.players_per_party, args.lines_per_player)
        )
        if (i + 1) % 10 == 0:
            elapsed = time.monotonic() - start
            print(f"{i + 1}/{args.parties} parties built ({elapsed:.1f}s elapsed)", file=sys.stderr)

    elapsed = time.monotonic() - start
    total_players = args.parties * args.players_per_party
    print(
        f"Built {args.parties} parties x {args.players_per_party} players "
        f"({total_players} players total) in {elapsed:.1f}s"
    )

    if args.stream_rooms:
        asyncio.run(
            hold_streams(
                args.base_url,
                origin,
                built[: args.stream_rooms],
                args.streams_per_member,
                args.stream_hold_seconds,
            )
        )


if __name__ == "__main__":
    main()
