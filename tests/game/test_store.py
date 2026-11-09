"""In-memory game store: party/player/attempt limits, idle expiry,
and that the party-limit fallback never evicts a still-active party."""

from __future__ import annotations

import concurrent.futures
import time

import pytest

from keystroke_dynamics.game import store as store_module
from keystroke_dynamics.game.codes import CODE_ALPHABET, CODE_LENGTH
from keystroke_dynamics.game.store import (
    Attempt,
    InMemoryGameStore,
    Note,
    PartyFullError,
    PartyLimitReached,
    Player,
    RoomLockedError,
    RoomMembersFullError,
    RoomNotFoundError,
)


def make_store(**overrides: object) -> InMemoryGameStore:
    defaults: dict[str, object] = {
        "party_limit": 3,
        "players_per_party_limit": 2,
        "attempts_per_party_limit": 3,
        "idle_expiry_seconds": 60.0,
        "members_per_party_limit": 3,
    }
    defaults.update(overrides)
    return InMemoryGameStore(**defaults)  # type: ignore[arg-type]


def make_player(player_id: str = "p1", name: str = "Quiet Otter") -> Player:
    return Player(
        id=player_id,
        name=name,
        color=0,
        profile={},
        threshold=1.5,
        notes=[Note(ch="a", start_ms=0.0, dur_ms=80.0)],
    )


def make_attempt(target_id: str = "p1", typist_id: str | None = "p2") -> Attempt:
    return Attempt(
        id="a1",
        typist_name="Someone",
        typist_id=typist_id,
        target_id=target_id,
        target_name="Target",
        mode="attack",
        distance=1.0,
        threshold=1.5,
        ratio=1.0 / 1.5,
        word="Caught!",
        counted=True,
        passed=False,
    )


# ---------- parties ----------


def test_create_and_get_party_round_trips() -> None:
    store = make_store()
    party = store.create_party("sentence")
    assert store.get_party(party.id) is party


def test_get_party_returns_none_for_unknown_id() -> None:
    store = make_store()
    assert store.get_party("does-not-exist") is None


def test_party_limit_raises_when_nothing_has_expired() -> None:
    store = make_store(party_limit=2, idle_expiry_seconds=60.0)
    store.create_party("sentence")
    store.create_party("sentence")
    with pytest.raises(PartyLimitReached):
        store.create_party("sentence")


def test_party_limit_does_not_evict_a_still_active_party() -> None:
    # The required regression: at capacity, with nothing expired, the
    # store must refuse the new party rather than silently delete
    # someone's real, active game to make room.
    store = make_store(party_limit=1, idle_expiry_seconds=60.0)
    kept = store.create_party("sentence")
    with pytest.raises(PartyLimitReached):
        store.create_party("sentence")
    assert store.get_party(kept.id) is kept


def test_expired_party_is_swept_and_frees_capacity() -> None:
    store = make_store(party_limit=1, idle_expiry_seconds=0.01)
    first = store.create_party("sentence")
    time.sleep(0.05)
    # Creating a new party sweeps expired ones first.
    second = store.create_party("sentence")
    assert store.get_party(first.id) is None
    assert store.get_party(second.id) is second


def test_get_party_itself_also_expires_a_stale_party() -> None:
    store = make_store(idle_expiry_seconds=0.01)
    party = store.create_party("sentence")
    time.sleep(0.05)
    assert store.get_party(party.id) is None


def test_touch_resets_the_idle_clock() -> None:
    store = make_store(idle_expiry_seconds=0.1)
    party = store.create_party("sentence")
    time.sleep(0.06)
    store.touch(party.id)
    time.sleep(0.06)
    # 0.12s have passed since creation, but only 0.06s since the touch.
    assert store.get_party(party.id) is not None


def test_sweep_expired_reports_how_many_it_removed() -> None:
    store = make_store(idle_expiry_seconds=0.01)
    store.create_party("sentence")
    store.create_party("sentence")
    time.sleep(0.05)
    assert store.sweep_expired() == 2


def test_delete_party_removes_it() -> None:
    store = make_store()
    party = store.create_party("sentence")
    store.delete_party(party.id)
    assert store.get_party(party.id) is None


# ---------- players ----------


def test_add_player_and_look_it_up_through_the_party() -> None:
    store = make_store()
    party = store.create_party("sentence")
    store.add_player(party.id, make_player("p1"))
    assert store.get_party(party.id).players["p1"].name == "Quiet Otter"  # type: ignore[union-attr]


def test_players_per_party_limit_is_enforced() -> None:
    store = make_store(players_per_party_limit=1)
    party = store.create_party("sentence")
    store.add_player(party.id, make_player("p1"))
    with pytest.raises(PartyFullError):
        store.add_player(party.id, make_player("p2"))


def test_rename_player_changes_the_name_only() -> None:
    store = make_store()
    party = store.create_party("sentence")
    store.add_player(party.id, make_player("p1", "Quiet Otter"))
    original = store.get_party(party.id).players["p1"]  # type: ignore[union-attr]
    assert store.rename_player(party.id, "p1", "Loud Otter") is True
    renamed = store.get_party(party.id).players["p1"]  # type: ignore[union-attr]
    assert renamed.name == "Loud Otter"
    assert renamed.threshold == 1.5  # everything else carried over
    # A rename must never mint a new score_id -- score_attempts rows
    # recorded before the rename must still be reachable by "Delete
    # me" afterward (docs/plans/done/PARTY_LAUNCH_PLAN.md section 10).
    assert renamed.score_id == original.score_id
    assert renamed.training_line_count == original.training_line_count


def test_each_player_gets_a_distinct_random_score_id() -> None:
    store = make_store()
    party = store.create_party("sentence")
    store.add_player(party.id, make_player("p1"))
    store.add_player(party.id, make_player("p2"))
    players = store.get_party(party.id).players  # type: ignore[union-attr]
    assert players["p1"].score_id != players["p2"].score_id
    # Never derived from the game-facing id.
    assert players["p1"].score_id != players["p1"].id


def test_each_party_gets_a_distinct_random_score_id() -> None:
    store = make_store()
    a = store.create_party("sentence")
    b = store.create_party("sentence")
    assert a.score_id != b.score_id
    assert a.score_id != a.id


def test_rename_unknown_player_returns_false() -> None:
    store = make_store()
    party = store.create_party("sentence")
    assert store.rename_player(party.id, "nope", "New Name") is False


def test_delete_player_removes_them_and_their_attempts() -> None:
    store = make_store()
    party = store.create_party("sentence")
    store.add_player(party.id, make_player("p1"))
    store.add_attempt(party.id, make_attempt(target_id="p1"))
    assert store.delete_player(party.id, "p1") is True
    updated = store.get_party(party.id)
    assert "p1" not in updated.players  # type: ignore[union-attr]
    assert updated.attempts == []  # type: ignore[union-attr]


# ---------- attempts ----------


def test_attempts_per_party_limit_keeps_only_the_most_recent() -> None:
    store = make_store(attempts_per_party_limit=2)
    party = store.create_party("sentence")
    for i in range(4):
        store.add_attempt(party.id, Attempt(**{**make_attempt().__dict__, "id": f"a{i}"}))
    kept = store.get_party(party.id).attempts  # type: ignore[union-attr]
    assert [a.id for a in kept] == ["a2", "a3"]


def test_add_attempt_to_unknown_party_returns_false() -> None:
    store = make_store()
    assert store.add_attempt("does-not-exist", make_attempt()) is False


# ---------- concurrency ----------
#
# FastAPI dispatches sync routes to a threadpool, so these really do
# run concurrently within the one game process -- the store's lock
# (not just its single-threaded-looking code) is what these tests
# actually exercise.


def test_concurrent_add_player_never_exceeds_the_limit() -> None:
    store = make_store(players_per_party_limit=5)
    party = store.create_party("sentence")
    n = 20

    def add(i: int) -> bool:
        try:
            store.add_player(party.id, make_player(f"p{i}", f"Player {i}"))
            return True
        except PartyFullError:
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(add, range(n)))

    assert sum(results) == 5
    assert len(store.get_party(party.id).players) == 5  # type: ignore[union-attr]


def test_concurrent_add_attempt_keeps_the_count_capped_and_intact() -> None:
    store = make_store(attempts_per_party_limit=5)
    party = store.create_party("sentence")
    n = 20

    def add(i: int) -> None:
        attempt = Attempt(**{**make_attempt().__dict__, "id": f"a{i}"})
        assert store.add_attempt(party.id, attempt) is True

    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
        list(pool.map(add, range(n)))

    kept = store.get_party(party.id).attempts  # type: ignore[union-attr]
    assert len(kept) == 5
    assert len({a.id for a in kept}) == 5  # no duplicate/corrupted entries


# ---------- rooms: codes, members, host, lock, version ----------


def make_owned_player(player_id: str, owner_member_id: str) -> Player:
    return Player(
        id=player_id,
        name=f"Player {player_id}",
        color=0,
        profile={},
        threshold=1.5,
        notes=[Note(ch="a", start_ms=0.0, dur_ms=80.0)],
        owner_member_id=owner_member_id,
    )


def test_a_new_room_has_a_code_and_its_creator_as_host_and_only_member() -> None:
    store = make_store()
    party = store.create_party("sentence")
    assert len(party.code) == CODE_LENGTH
    assert set(party.code) <= set(CODE_ALPHABET)
    assert list(party.members) == [party.host_member_id]
    host = party.members[party.host_member_id]
    assert host.device_type == "keyboard"
    assert host.created_at <= host.last_seen
    assert party.locked is False


def test_room_and_member_ids_are_random_and_unrelated_to_the_code() -> None:
    store = make_store()
    a = store.create_party("sentence")
    b = store.create_party("sentence")
    assert len({a.id, b.id, a.host_member_id, b.host_member_id, a.score_id, b.score_id}) == 6
    assert a.code not in a.id


def test_codes_stay_unique_among_live_rooms_even_when_the_generator_repeats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Forces the clash a 40-bit code would otherwise never produce in a test.
    draws = iter(["AAAAAAAA", "AAAAAAAA", "AAAAAAAA", "BBBBBBBB"])
    monkeypatch.setattr(store_module, "generate_code", lambda: next(draws))
    store = make_store()
    first = store.create_party("sentence")
    second = store.create_party("sentence")
    assert first.code == "AAAAAAAA"
    assert second.code == "BBBBBBBB"


def test_an_ended_rooms_code_can_be_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    # Uniqueness is among *live* rooms only.
    monkeypatch.setattr(store_module, "generate_code", lambda: "AAAAAAAA")
    store = make_store()
    first = store.create_party("sentence")
    store.delete_party(first.id)
    assert store.create_party("sentence").code == "AAAAAAAA"


def test_join_adds_a_member_to_the_room_with_that_code() -> None:
    store = make_store()
    party = store.create_party("sentence")
    joined, member = store.join_party(party.code)
    assert joined is party
    assert member.id in party.members
    assert member.id != party.host_member_id
    assert member.device_type == "keyboard"


def test_join_unknown_code_raises_room_not_found() -> None:
    store = make_store()
    with pytest.raises(RoomNotFoundError):
        store.join_party("ZZZZZZZZ")


def test_join_ended_room_raises_room_not_found() -> None:
    store = make_store()
    party = store.create_party("sentence")
    store.delete_party(party.id)
    with pytest.raises(RoomNotFoundError):
        store.join_party(party.code)


def test_join_expired_room_raises_room_not_found_and_frees_it() -> None:
    store = make_store(idle_expiry_seconds=0.01)
    party = store.create_party("sentence")
    time.sleep(0.05)
    with pytest.raises(RoomNotFoundError):
        store.join_party(party.code)
    assert store.party_count() == 0


def test_join_locked_room_raises_and_adds_nobody() -> None:
    store = make_store()
    party = store.create_party("sentence")
    assert store.set_locked(party.id, True) is True
    with pytest.raises(RoomLockedError):
        store.join_party(party.code)
    assert len(party.members) == 1
    store.set_locked(party.id, False)
    store.join_party(party.code)
    assert len(party.members) == 2


def test_set_locked_on_unknown_room_returns_false() -> None:
    assert make_store().set_locked("does-not-exist", True) is False


def test_member_limit_is_enforced() -> None:
    store = make_store(members_per_party_limit=2)
    party = store.create_party("sentence")
    store.join_party(party.code)
    with pytest.raises(RoomMembersFullError):
        store.join_party(party.code)
    assert len(party.members) == 2


def test_concurrent_joins_never_exceed_the_member_limit() -> None:
    store = make_store(members_per_party_limit=5)
    party = store.create_party("sentence")

    def join(_: int) -> bool:
        try:
            store.join_party(party.code)
            return True
        except RoomMembersFullError:
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(join, range(20)))

    assert sum(results) == 4  # the host already holds one of the five places
    assert len(party.members) == 5


def test_remove_member_takes_their_players_and_those_players_attempts() -> None:
    store = make_store(players_per_party_limit=5)
    party = store.create_party("sentence")
    host_id = party.host_member_id
    _, friend = store.join_party(party.code)
    store.add_player(party.id, make_owned_player("h1", host_id))
    store.add_player(party.id, make_owned_player("f1", friend.id))
    store.add_player(party.id, make_owned_player("f2", friend.id))
    store.add_attempt(party.id, make_attempt(target_id="h1", typist_id="f1"))
    store.add_attempt(party.id, make_attempt(target_id="f2", typist_id="h1"))
    store.add_attempt(party.id, make_attempt(target_id="h1", typist_id=None))

    removal = store.remove_member(party.id, friend.id)

    assert removal is not None
    assert removal.room_ended is False
    assert sorted(p.id for p in removal.players) == ["f1", "f2"]
    assert list(party.players) == ["h1"]
    assert list(party.members) == [host_id]
    # Only the Guest attempt on the host's own player is left.
    assert [(a.typist_id, a.target_id) for a in party.attempts] == [(None, "h1")]


def test_removing_the_host_passes_host_to_the_longest_standing_member() -> None:
    store = make_store()
    party = store.create_party("sentence")
    old_host = party.host_member_id
    _, second = store.join_party(party.code)
    time.sleep(0.01)
    store.join_party(party.code)
    store.remove_member(party.id, old_host)
    assert party.host_member_id == second.id


def test_removing_the_last_member_ends_the_room() -> None:
    store = make_store()
    party = store.create_party("sentence")
    store.add_player(party.id, make_owned_player("h1", party.host_member_id))
    removal = store.remove_member(party.id, party.host_member_id)
    assert removal is not None
    assert removal.room_ended is True
    assert [p.id for p in removal.players] == ["h1"]
    assert store.get_party(party.id) is None
    with pytest.raises(RoomNotFoundError):
        store.join_party(party.code)


def test_remove_unknown_member_or_room_returns_none() -> None:
    store = make_store()
    party = store.create_party("sentence")
    assert store.remove_member(party.id, "nobody") is None
    assert store.remove_member("does-not-exist", party.host_member_id) is None
    assert len(party.members) == 1


def test_rename_keeps_the_players_owner() -> None:
    store = make_store()
    party = store.create_party("sentence")
    store.add_player(party.id, make_owned_player("p1", party.host_member_id))
    store.rename_player(party.id, "p1", "New Name")
    assert party.players["p1"].owner_member_id == party.host_member_id


def test_version_increases_on_every_change() -> None:
    store = make_store(players_per_party_limit=5)
    party = store.create_party("sentence")
    versions = [party.version]

    def expect_bump() -> None:
        assert party.version == versions[-1] + 1
        versions.append(party.version)

    _, friend = store.join_party(party.code)
    expect_bump()
    store.add_player(party.id, make_owned_player("p1", party.host_member_id))
    expect_bump()
    store.rename_player(party.id, "p1", "New Name")
    expect_bump()
    store.add_attempt(party.id, make_attempt(target_id="p1", typist_id=None))
    expect_bump()
    store.set_locked(party.id, True)
    expect_bump()
    store.delete_player(party.id, "p1")
    expect_bump()
    store.remove_member(party.id, friend.id)
    expect_bump()


def test_version_does_not_move_when_nothing_changed() -> None:
    store = make_store()
    party = store.create_party("sentence")
    before = party.version
    store.set_locked(party.id, False)  # already unlocked
    store.mark_member_seen(party.id, party.host_member_id)
    store.get_party(party.id)
    assert party.version == before


def test_mark_member_seen_updates_last_seen_but_not_the_idle_clock() -> None:
    store = make_store(idle_expiry_seconds=0.1)
    party = store.create_party("sentence")
    host = party.members[party.host_member_id]
    first_seen = host.last_seen
    time.sleep(0.06)
    store.mark_member_seen(party.id, host.id)
    assert host.last_seen > first_seen
    time.sleep(0.06)
    # Being seen is not activity: the room still expires on schedule.
    assert store.get_party(party.id) is None
