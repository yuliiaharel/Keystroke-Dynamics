"""Live-update signals: who is listening to which room, and how a
change reaches them (docs/plans/active/ROOMS_PLAN.md Phase 2).

A signal is only ever "this room is now at version N" or "this is
over for you" -- never anything about the room itself. A browser that
hears one fetches the room the normal way, so every access check
stays where it already is (api/game.py).

Threads: rooms change on threadpool threads (the store's sync
callers), while each listener waits on an event loop. Ownership is
split to match:
- the registry of subscriptions is guarded by `_lock`, and may be
  touched from any thread;
- a Subscription's own state is only ever touched on its loop's
  thread. Other threads reach it through `call_soon_threadsafe`,
  which is also what keeps signalling from blocking the store, whose
  lock is held while RoomEvents is called.
RoomEvents never calls into the store, so the lock order is always
store, then `_lock`.
"""

from __future__ import annotations

import asyncio
import logging
import threading

logger = logging.getLogger(__name__)


class MemberStreamLimitError(Exception):
    """One browser already has as many streams open as it may."""


class TotalStreamLimitError(Exception):
    """The whole app already has as many streams open as it may."""


class Subscription:
    """One open stream's inbox. Holds at most one pending version:
    several changes that land before the stream wakes are a single
    "the room changed"."""

    def __init__(self, party_id: str, member_id: str, loop: asyncio.AbstractEventLoop) -> None:
        self.party_id = party_id
        self.member_id = member_id
        self.loop = loop
        self._wake = asyncio.Event()
        self._version: int | None = None
        self._ended = False

    async def next(self) -> int | None:
        """Waits for the next signal: the room's latest version, or
        None once this stream is over (the room ended or expired, or
        this member left or was removed)."""
        await self._wake.wait()
        if self._ended:
            return None
        self._wake.clear()
        version, self._version = self._version, None
        return version

    def _deliver_version(self, version: int) -> None:
        # Two changes can be signalled out of order; only the highest
        # matters.
        if self._version is None or version > self._version:
            self._version = version
        self._wake.set()

    def _deliver_end(self) -> None:
        self._ended = True
        self._wake.set()


class RoomEvents:
    """Implements game/store.py's RoomListener."""

    def __init__(self, *, streams_per_member_limit: int, streams_total_limit: int) -> None:
        self._streams_per_member_limit = streams_per_member_limit
        self._streams_total_limit = streams_total_limit
        self._lock = threading.Lock()
        self._by_room: dict[str, set[Subscription]] = {}
        self._total = 0

    def subscribe(self, party_id: str, member_id: str) -> Subscription:
        """Must be called on the event loop the stream will run on.
        The caller owns the subscription and must unsubscribe() it."""
        subscription = Subscription(party_id, member_id, asyncio.get_running_loop())
        with self._lock:
            if self._total >= self._streams_total_limit:
                raise TotalStreamLimitError(
                    "Live updates are at capacity. This page will keep refreshing on its own."
                )
            room = self._by_room.get(party_id, set())
            if sum(s.member_id == member_id for s in room) >= self._streams_per_member_limit:
                raise MemberStreamLimitError(
                    f"This browser already has {self._streams_per_member_limit} live "
                    "connections to this room. Close another tab."
                )
            room.add(subscription)
            self._by_room[party_id] = room
            self._total += 1
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        """Safe to call more than once, and after the room is gone."""
        with self._lock:
            self._discard(subscription)

    def open_streams(self) -> int:
        with self._lock:
            return self._total

    def room_changed(self, party_id: str, version: int) -> None:
        with self._lock:
            for subscription in list(self._by_room.get(party_id, ())):
                self._signal(subscription, version)

    def room_ended(self, party_id: str) -> None:
        with self._lock:
            for subscription in list(self._by_room.get(party_id, ())):
                self._signal(subscription, None)

    def member_removed(self, party_id: str, member_id: str) -> None:
        with self._lock:
            for subscription in list(self._by_room.get(party_id, ())):
                if subscription.member_id == member_id:
                    self._signal(subscription, None)

    def _signal(self, subscription: Subscription, version: int | None) -> None:
        """Caller holds the lock. An ended subscription stays counted
        until its stream unsubscribes: it's still an open connection."""
        try:
            if version is None:
                subscription.loop.call_soon_threadsafe(subscription._deliver_end)
            else:
                subscription.loop.call_soon_threadsafe(subscription._deliver_version, version)
        except RuntimeError:
            # The loop is closed, so the stream that owned this died
            # with it and will never unsubscribe. Free its slot here.
            logger.warning("dropping a live-update stream whose event loop is closed")
            self._discard(subscription)

    def _discard(self, subscription: Subscription) -> None:
        room = self._by_room.get(subscription.party_id)
        if room is None or subscription not in room:
            return
        room.remove(subscription)
        self._total -= 1
        if not room:
            del self._by_room[subscription.party_id]
