"""In-memory game store: party/player/attempt limits, idle expiry,
and that the party-limit fallback never evicts a still-active party."""

from __future__ import annotations

import concurrent.futures
import time

import pytest

from keystroke_dynamics.game.store import (
    Attempt,
    InMemoryGameStore,
    Note,
    PartyFullError,
    PartyLimitReached,
    Player,
)


def make_store(**overrides: object) -> InMemoryGameStore:
    defaults: dict[str, object] = {
        "party_limit": 3,
        "players_per_party_limit": 2,
        "attempts_per_party_limit": 3,
        "idle_expiry_seconds": 60.0,
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
    store.create_party("word")
    store.create_party("word")
    with pytest.raises(PartyLimitReached):
        store.create_party("word")


def test_party_limit_does_not_evict_a_still_active_party() -> None:
    # The required regression: at capacity, with nothing expired, the
    # store must refuse the new party rather than silently delete
    # someone's real, active game to make room.
    store = make_store(party_limit=1, idle_expiry_seconds=60.0)
    kept = store.create_party("word")
    with pytest.raises(PartyLimitReached):
        store.create_party("word")
    assert store.get_party(kept.id) is kept


def test_expired_party_is_swept_and_frees_capacity() -> None:
    store = make_store(party_limit=1, idle_expiry_seconds=0.01)
    first = store.create_party("word")
    time.sleep(0.05)
    # Creating a new party sweeps expired ones first.
    second = store.create_party("word")
    assert store.get_party(first.id) is None
    assert store.get_party(second.id) is second


def test_get_party_itself_also_expires_a_stale_party() -> None:
    store = make_store(idle_expiry_seconds=0.01)
    party = store.create_party("word")
    time.sleep(0.05)
    assert store.get_party(party.id) is None


def test_touch_resets_the_idle_clock() -> None:
    store = make_store(idle_expiry_seconds=0.1)
    party = store.create_party("word")
    time.sleep(0.06)
    store.touch(party.id)
    time.sleep(0.06)
    # 0.12s have passed since creation, but only 0.06s since the touch.
    assert store.get_party(party.id) is not None


def test_sweep_expired_reports_how_many_it_removed() -> None:
    store = make_store(idle_expiry_seconds=0.01)
    store.create_party("word")
    store.create_party("word")
    time.sleep(0.05)
    assert store.sweep_expired() == 2


def test_delete_party_removes_it() -> None:
    store = make_store()
    party = store.create_party("word")
    store.delete_party(party.id)
    assert store.get_party(party.id) is None


# ---------- players ----------


def test_add_player_and_look_it_up_through_the_party() -> None:
    store = make_store()
    party = store.create_party("word")
    store.add_player(party.id, make_player("p1"))
    assert store.get_party(party.id).players["p1"].name == "Quiet Otter"  # type: ignore[union-attr]


def test_players_per_party_limit_is_enforced() -> None:
    store = make_store(players_per_party_limit=1)
    party = store.create_party("word")
    store.add_player(party.id, make_player("p1"))
    with pytest.raises(PartyFullError):
        store.add_player(party.id, make_player("p2"))


def test_rename_player_changes_the_name_only() -> None:
    store = make_store()
    party = store.create_party("word")
    store.add_player(party.id, make_player("p1", "Quiet Otter"))
    assert store.rename_player(party.id, "p1", "Loud Otter") is True
    renamed = store.get_party(party.id).players["p1"]  # type: ignore[union-attr]
    assert renamed.name == "Loud Otter"
    assert renamed.threshold == 1.5  # everything else carried over


def test_rename_unknown_player_returns_false() -> None:
    store = make_store()
    party = store.create_party("word")
    assert store.rename_player(party.id, "nope", "New Name") is False


def test_delete_player_removes_them_and_their_attempts() -> None:
    store = make_store()
    party = store.create_party("word")
    store.add_player(party.id, make_player("p1"))
    store.add_attempt(party.id, make_attempt(target_id="p1"))
    assert store.delete_player(party.id, "p1") is True
    updated = store.get_party(party.id)
    assert "p1" not in updated.players  # type: ignore[union-attr]
    assert updated.attempts == []  # type: ignore[union-attr]


# ---------- attempts ----------


def test_attempts_per_party_limit_keeps_only_the_most_recent() -> None:
    store = make_store(attempts_per_party_limit=2)
    party = store.create_party("word")
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
    party = store.create_party("word")
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
    party = store.create_party("word")
    n = 20

    def add(i: int) -> None:
        attempt = Attempt(**{**make_attempt().__dict__, "id": f"a{i}"})
        assert store.add_attempt(party.id, attempt) is True

    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
        list(pool.map(add, range(n)))

    kept = store.get_party(party.id).attempts  # type: ignore[union-attr]
    assert len(kept) == 5
    assert len({a.id for a in kept}) == 5  # no duplicate/corrupted entries
