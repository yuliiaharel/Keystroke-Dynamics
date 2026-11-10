"""game/events.py: how a room change reaches the streams listening to
it (docs/plans/active/ROOMS_PLAN.md Phase 2), the two caps, and that
signals cross from the threads rooms change on to the loop a stream
waits on.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from keystroke_dynamics.game.events import (
    MemberStreamLimitError,
    RoomEvents,
    TotalStreamLimitError,
)

WAIT = 2.0


def make_events(per_member: int = 3, total: int = 300) -> RoomEvents:
    return RoomEvents(streams_per_member_limit=per_member, streams_total_limit=total)


def test_a_change_reaches_every_stream_of_that_room_and_no_other() -> None:
    async def scenario() -> None:
        events = make_events()
        first = events.subscribe("room-1", "m1")
        second = events.subscribe("room-1", "m2")
        other = events.subscribe("room-2", "m3")

        events.room_changed("room-1", 7)

        assert await asyncio.wait_for(first.next(), WAIT) == 7
        assert await asyncio.wait_for(second.next(), WAIT) == 7
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(other.next(), 0.05)

    asyncio.run(scenario())


def test_changes_that_land_together_are_one_signal_with_the_latest_version() -> None:
    async def scenario() -> None:
        events = make_events()
        subscription = events.subscribe("room-1", "m1")

        # Out of order on purpose: two threads can signal either way round.
        for version in (3, 5, 4):
            events.room_changed("room-1", version)

        assert await asyncio.wait_for(subscription.next(), WAIT) == 5
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(subscription.next(), 0.05)

    asyncio.run(scenario())


def test_a_change_signalled_from_another_thread_wakes_the_stream() -> None:
    async def scenario() -> None:
        events = make_events()
        subscription = events.subscribe("room-1", "m1")
        waiting = asyncio.ensure_future(subscription.next())
        await asyncio.sleep(0)  # let it start waiting

        thread = threading.Thread(target=events.room_changed, args=("room-1", 2))
        thread.start()
        thread.join()

        assert await asyncio.wait_for(waiting, WAIT) == 2

    asyncio.run(scenario())


def test_an_ended_room_ends_every_one_of_its_streams() -> None:
    async def scenario() -> None:
        events = make_events()
        first = events.subscribe("room-1", "m1")
        second = events.subscribe("room-1", "m2")
        other = events.subscribe("room-2", "m3")

        events.room_changed("room-1", 9)  # a pending version must not hide the end
        events.room_ended("room-1")

        assert await asyncio.wait_for(first.next(), WAIT) is None
        assert await asyncio.wait_for(second.next(), WAIT) is None
        # Ended is final, however often it's asked.
        assert await asyncio.wait_for(first.next(), WAIT) is None
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(other.next(), 0.05)

    asyncio.run(scenario())


def test_removing_a_member_ends_only_that_members_streams() -> None:
    async def scenario() -> None:
        events = make_events()
        removed_tab_1 = events.subscribe("room-1", "m1")
        removed_tab_2 = events.subscribe("room-1", "m1")
        stays = events.subscribe("room-1", "m2")

        events.member_removed("room-1", "m1")

        assert await asyncio.wait_for(removed_tab_1.next(), WAIT) is None
        assert await asyncio.wait_for(removed_tab_2.next(), WAIT) is None
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(stays.next(), 0.05)

    asyncio.run(scenario())


def test_the_per_member_cap_holds_and_a_closed_stream_frees_its_slot() -> None:
    async def scenario() -> None:
        events = make_events(per_member=3)
        opened = [events.subscribe("room-1", "m1") for _ in range(3)]

        with pytest.raises(MemberStreamLimitError):
            events.subscribe("room-1", "m1")
        # Another member of the same room, and the same member id in
        # another room, have their own allowance.
        events.subscribe("room-1", "m2")
        events.subscribe("room-2", "m1")

        events.unsubscribe(opened[0])
        events.subscribe("room-1", "m1")
        with pytest.raises(MemberStreamLimitError):
            events.subscribe("room-1", "m1")

    asyncio.run(scenario())


def test_the_total_cap_holds_across_rooms_and_a_closed_stream_frees_its_slot() -> None:
    async def scenario() -> None:
        events = make_events(total=4)
        opened = [events.subscribe(f"room-{i}", f"m{i}") for i in range(4)]
        assert events.open_streams() == 4

        with pytest.raises(TotalStreamLimitError):
            events.subscribe("room-9", "m9")
        assert events.open_streams() == 4

        events.unsubscribe(opened[0])
        events.subscribe("room-9", "m9")
        assert events.open_streams() == 4

    asyncio.run(scenario())


def test_a_refused_stream_is_not_counted() -> None:
    async def scenario() -> None:
        events = make_events(per_member=1)
        events.subscribe("room-1", "m1")
        for _ in range(5):
            with pytest.raises(MemberStreamLimitError):
                events.subscribe("room-1", "m1")
        assert events.open_streams() == 1

    asyncio.run(scenario())


def test_unsubscribing_twice_or_after_the_room_ended_is_harmless() -> None:
    async def scenario() -> None:
        events = make_events()
        subscription = events.subscribe("room-1", "m1")
        events.room_ended("room-1")
        # Still an open connection until its stream lets go.
        assert events.open_streams() == 1

        events.unsubscribe(subscription)
        events.unsubscribe(subscription)
        assert events.open_streams() == 0
        events.room_changed("room-1", 1)  # nobody left to tell

    asyncio.run(scenario())


def test_a_stream_whose_loop_is_gone_is_dropped_instead_of_breaking_the_change() -> None:
    events = make_events()

    async def subscribe_and_abandon() -> None:
        events.subscribe("room-1", "m1")

    asyncio.run(subscribe_and_abandon())  # the loop closes with the stream still registered
    assert events.open_streams() == 1

    events.room_changed("room-1", 1)

    assert events.open_streams() == 0
