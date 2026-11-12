"""The touch game above the scorer: enrollment, verdicts and clues,
the replay, the simulated practice targets, and the permanent target
(docs/plans/active/MOBILE_PLAN.md Phase 1 sections 5 to 8)."""

from __future__ import annotations

import json

import pytest

from keystroke_dynamics.game import targets as targets_module
from keystroke_dynamics.game.enroll import build_touch_profiles_and_threshold, median_notes
from keystroke_dynamics.game.judge import _touch_clue, judge_touch
from keystroke_dynamics.game.levels import LEVELS, TOUCH_LEVEL
from keystroke_dynamics.game.replay import notes_to_taps
from keystroke_dynamics.game.store import InMemoryGameStore, Player
from keystroke_dynamics.game.taps import to_key_events, validate_taps
from keystroke_dynamics.game.targets import (
    load_permanent_target,
    sample_targets,
    save_permanent_target,
    save_permanent_touch_target,
    touch_targets_dir,
)
from keystroke_dynamics.game.touch_scoring import (
    TOUCH_MAX_THRESHOLD,
    TOUCH_MIN_THRESHOLD,
    extract_touch_line,
    min_compared_timing_features,
)
from tests.touch_lines import TOUCH_PHRASE, tap_line, tap_lines, to_taps


def make_touch_player(typist: str = "alice", name: str = "Alice") -> Player:
    runs = [to_taps(line) for line in tap_lines(typist)]
    profile, place_profile, threshold = build_touch_profiles_and_threshold(TOUCH_PHRASE, runs)
    return Player(
        id=typist,
        name=name,
        color=0,
        profile=profile,
        place_profile=place_profile,
        threshold=threshold,
        notes=median_notes(TOUCH_PHRASE, [to_key_events(run) for run in runs]),
        training_line_count=len(runs),
    )


def _judge(target: Player, events: list[dict], mode: str = "attack", typist_name: str = "Bob"):
    return judge_touch(
        extract_touch_line(to_taps(events)),
        typist_name=typist_name,
        target=target,
        mode=mode,  # type: ignore[arg-type]
        phrase=TOUCH_PHRASE,
        run_duration_ms=events[-1]["t_ms"],
    )


# ---------- the level ----------


def test_the_touch_level_is_the_plans_line_with_five_rounds() -> None:
    level = LEVELS[TOUCH_LEVEL]
    assert level.phrase == "tap the rhythm of your thumbs"
    assert level.rounds == 5
    # Letters and spaces only: all the on-page keyboard has.
    assert set(level.phrase) <= set("abcdefghijklmnopqrstuvwxyz ")


def test_the_keyboard_levels_are_unchanged() -> None:
    assert LEVELS["sentence"].phrase == "quiet rhythm hides in every small habit of your hands"
    assert LEVELS["sentence"].rounds == 5
    assert LEVELS["long"].rounds == 4


# ---------- verdicts ----------


def test_a_touch_players_own_line_passes_with_rhythm_place_and_pace() -> None:
    alice = make_touch_player()
    verdict = _judge(alice, tap_line("alice", line=9), mode="self", typist_name="Alice")
    assert verdict.word == "That's you"
    assert verdict.passed is True
    assert verdict.rhythm is not None and verdict.place is not None
    assert verdict.distance <= alice.threshold
    assert verdict.pace == pytest.approx(1.0, abs=0.1)
    assert verdict.clue == "Speed, rhythm, and tap places all fit"
    assert verdict.compared_features == 84


def test_someone_elses_line_is_caught() -> None:
    verdict = _judge(make_touch_player(), tap_line("bob", line=0))
    assert verdict.word == "Caught!"
    assert verdict.passed is False
    assert verdict.distance > TOUCH_MAX_THRESHOLD


@pytest.mark.parametrize(
    ("shift", "word", "passed", "text"),
    [
        ((0.0, 0.0), "That's you", True, "It still recognized you with that grip."),
        ((0.5, -0.5), "Who are you?", False, "The new grip was enough to throw it off."),
    ],
)
def test_grip_mode_has_its_own_words(
    shift: tuple[float, float], word: str, passed: bool, text: str
) -> None:
    verdict = _judge(
        make_touch_player(), tap_line("alice", line=9, shift=shift), mode="grip", typist_name="A"
    )
    assert (verdict.word, verdict.passed, verdict.text) == (word, passed, text)
    assert verdict.counted is True


def test_grip_mode_has_no_pace_rule() -> None:
    # Twice as slow would disqualify a keyboard disguise before it was
    # scored. A grip test is scored whatever the pace.
    verdict = _judge(make_touch_player(), tap_line("alice", line=9, speed=2.0), mode="grip")
    assert verdict.counted is True
    assert verdict.passed is False
    assert verdict.pace > 1.15


def test_a_line_too_short_to_score_is_too_messy_with_no_scores() -> None:
    events = tap_line("alice", line=9)[: len(TOUCH_PHRASE)]
    verdict = _judge(make_touch_player(), events)
    assert verdict.word == "Too messy"
    assert verdict.counted is False
    assert verdict.passed is None
    assert verdict.distance is None
    assert verdict.rhythm is None
    assert verdict.place is None
    assert verdict.pace is None
    assert verdict.clue is None
    # 14 keys: 27 timing features, under the 40 the line needs.
    assert 0 < verdict.compared_features
    assert 27 < min_compared_timing_features(TOUCH_PHRASE)


# ---------- the clue ----------


@pytest.mark.parametrize(
    ("rhythm", "place", "pace", "expected"),
    [
        (1.0, 1.0, 1.0, "Speed, rhythm, and tap places all fit"),
        (2.5, 1.0, 1.0, "Right speed, wrong rhythm"),
        (2.5, 2.5, 1.0, "Right speed, wrong rhythm"),
        (1.0, 2.5, 1.0, "Right speed and rhythm, wrong tap places"),
        (1.0, 1.0, 0.7, "Too fast, but the rhythm and tap places fit"),
        (2.5, 1.0, 0.7, "Too fast, and the rhythm is off too"),
        (1.0, 2.5, 0.7, "Too fast, with the right rhythm but wrong tap places"),
        (1.0, 1.0, 1.3, "Too slow, but the rhythm and tap places fit"),
        (2.5, 2.5, 1.3, "Too slow, and the rhythm is off too"),
        (1.0, 2.5, 1.3, "Too slow, with the right rhythm but wrong tap places"),
        # Exactly on the limit, and exactly on the pace band's edges, fit.
        (1.65, 1.65, 0.85, "Speed, rhythm, and tap places all fit"),
        (1.65, 1.65, 1.15, "Speed, rhythm, and tap places all fit"),
    ],
)
def test_touch_clue(rhythm: float, place: float, pace: float, expected: str) -> None:
    assert _touch_clue(rhythm=rhythm, place=place, threshold=1.65, pace=pace) == expected


@pytest.mark.parametrize("shift", [(0.0, 0.0), (0.2, 0.0), (0.35, -0.35), (0.5, -0.5)])
@pytest.mark.parametrize("typist", ["alice", "bob", "carol"])
@pytest.mark.parametrize("speed", [0.7, 1.0, 1.4])
def test_the_clue_never_says_everything_fits_on_a_failed_attempt(
    shift: tuple[float, float], typist: str, speed: float
) -> None:
    verdict = _judge(make_touch_player(), tap_line(typist, line=9, shift=shift, speed=speed))
    assert verdict.clue is not None
    if verdict.passed is False:
        assert "all fit" not in verdict.clue
        assert "tap places fit" not in verdict.clue


def test_the_clue_names_tap_position_when_that_is_the_giveaway() -> None:
    # Alice's own rhythm at her own pace, from a different grip.
    verdict = _judge(make_touch_player(), tap_line("alice", line=9, shift=(0.5, -0.5)))
    assert verdict.passed is False
    assert verdict.rhythm <= make_touch_player().threshold < verdict.place
    assert verdict.clue == "Right speed and rhythm, wrong tap places"


# ---------- replay ----------


def test_notes_to_taps_lands_on_the_targets_average_spot_for_each_key() -> None:
    alice = make_touch_player()
    taps = notes_to_taps(alice.notes, alice.place_profile)
    validate_taps(taps, max_events=2000)
    downs = [t for t in taps if t.action == "down"]
    assert len(downs) == len(TOUCH_PHRASE)
    first_t = downs[0]
    assert first_t.code == "KeyT"
    assert first_t.dx == alice.place_profile[("tap_x", "KeyT")].mean
    assert first_t.dy == alice.place_profile[("tap_y", "KeyT")].mean
    space = next(t for t in downs if t.code == "Space")
    assert space.dx == 0.0  # never scored: the space bar has no tap_x
    assert space.dy == alice.place_profile[("tap_y", "Space")].mean
    assert all(t.dx is None and t.dy is None for t in taps if t.action == "up")


def test_a_touch_replay_passes_as_its_target() -> None:
    alice = make_touch_player()
    taps = notes_to_taps(alice.notes, alice.place_profile)
    verdict = judge_touch(
        extract_touch_line(taps),
        typist_name="Replay bot",
        target=alice,
        mode="replay",
        phrase=TOUCH_PHRASE,
        run_duration_ms=taps[-1].t_ms,
    )
    assert verdict.word == "Replay wins"
    assert verdict.passed is True
    # Every tap landed on the average spot, so place is as close as a
    # line can get.
    assert verdict.place == pytest.approx(0.0, abs=1e-9)
    assert verdict.pace == pytest.approx(1.0)


def test_a_touch_replay_does_not_pass_as_someone_else() -> None:
    alice, bob = make_touch_player("alice"), make_touch_player("bob", "Bob")
    taps = notes_to_taps(alice.notes, alice.place_profile)
    verdict = judge_touch(
        extract_touch_line(taps),
        typist_name="Replay bot",
        target=bob,
        mode="replay",
        phrase=TOUCH_PHRASE,
        run_duration_ms=taps[-1].t_ms,
    )
    assert verdict.word == "Replay failed"


# ---------- simulated practice targets ----------


def test_touch_sample_targets_are_two_clearly_labeled_tappers() -> None:
    bots = sample_targets(TOUCH_LEVEL, TOUCH_PHRASE)
    assert [b.name for b in bots] == ["Sample: Speedy Thumbs", "Sample: One-Finger Pecker"]
    assert all(b.id.startswith("sample-") for b in bots)
    assert all(b.owner_member_id is None for b in bots)
    for bot in bots:
        assert TOUCH_MIN_THRESHOLD <= bot.threshold <= TOUCH_MAX_THRESHOLD
        assert len(bot.place_profile) == 27
        assert len(bot.notes) == len(TOUCH_PHRASE)


def test_touch_sample_targets_are_deterministic_and_differ_from_each_other() -> None:
    sample_targets.cache_clear()
    first = sample_targets(TOUCH_LEVEL, TOUCH_PHRASE)
    sample_targets.cache_clear()
    second = sample_targets(TOUCH_LEVEL, TOUCH_PHRASE)
    assert [b.profile for b in first] == [b.profile for b in second]
    assert [b.place_profile for b in first] == [b.place_profile for b in second]
    speedy, pecker = first
    # Their thumbs land in different places, as the mockup's do.
    assert (
        speedy.place_profile[("tap_y", "KeyT")].mean > pecker.place_profile[("tap_y", "KeyT")].mean
    )


def test_keyboard_sample_targets_have_no_tap_positions() -> None:
    bots = sample_targets("sentence", LEVELS["sentence"].phrase)
    assert len(bots) == 3
    assert all(b.place_profile == {} for b in bots)


def test_a_touch_sample_target_can_be_replayed_and_attacked() -> None:
    speedy, pecker = sample_targets(TOUCH_LEVEL, TOUCH_PHRASE)
    taps = notes_to_taps(speedy.notes, speedy.place_profile)

    def judge(target: Player):
        return judge_touch(
            extract_touch_line(taps),
            typist_name="Replay bot",
            target=target,
            mode="replay",
            phrase=TOUCH_PHRASE,
            run_duration_ms=taps[-1].t_ms,
        )

    assert judge(speedy).passed is True
    assert judge(pecker).passed is False


# ---------- the permanent target ----------


def test_the_game_works_with_no_permanent_touch_target(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(targets_module, "TARGETS_DIR", tmp_path)
    assert load_permanent_target(TOUCH_LEVEL) is None


def test_a_permanent_touch_target_round_trips(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(targets_module, "TARGETS_DIR", tmp_path)
    runs = [to_taps(line) for line in tap_lines("yuliia")]
    touch_targets_dir().mkdir()
    save_permanent_touch_target(touch_targets_dir() / "yuliia.json", name="Yuliia", runs=runs)

    loaded = load_permanent_target(TOUCH_LEVEL)
    assert loaded is not None
    assert loaded.name == "Yuliia"
    assert loaded.id == "target-touch-yuliia"
    assert loaded.training_line_count == 4
    profile, place_profile, threshold = build_touch_profiles_and_threshold(TOUCH_PHRASE, runs)
    assert loaded.profile == profile
    assert loaded.place_profile == place_profile
    assert loaded.threshold == threshold
    # A fresh line of hers passes against the loaded target.
    assert _judge(loaded, tap_line("yuliia", line=9), mode="attack").passed is True


def test_touch_and_keyboard_permanent_targets_do_not_replace_each_other(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(targets_module, "TARGETS_DIR", tmp_path)
    phrase = LEVELS["sentence"].phrase
    keyboard_runs = [
        to_key_events(to_taps(tap_line("yuliia", line=i, phrase=phrase))) for i in range(4)
    ]
    save_permanent_target(
        tmp_path / "yuliia.json", name="Yuliia", lines={"sentence": keyboard_runs}
    )
    touch_targets_dir().mkdir()
    save_permanent_touch_target(
        touch_targets_dir() / "yuliia.json",
        name="Yuliia",
        runs=[to_taps(line) for line in tap_lines("yuliia")],
    )

    keyboard, touch = load_permanent_target("sentence"), load_permanent_target(TOUCH_LEVEL)
    assert keyboard is not None and touch is not None
    assert keyboard.place_profile == {}
    assert touch.place_profile
    # Separate ids, so separate ids in stored scores too.
    assert keyboard.id != touch.id
    assert keyboard.score_id != touch.score_id
    # Neither is offered for the other's level.
    assert load_permanent_target("long") is None


def test_a_permanent_touch_target_file_holds_no_raw_taps(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(targets_module, "TARGETS_DIR", tmp_path)
    lines = tap_lines("yuliia")
    touch_targets_dir().mkdir()
    path = touch_targets_dir() / "yuliia.json"
    save_permanent_touch_target(path, name="Yuliia", runs=[to_taps(line) for line in lines])

    text = path.read_text()
    data = json.loads(text)
    assert set(data["lines"][TOUCH_LEVEL]) == {
        "threshold",
        "profile",
        "place_profile",
        "notes",
        "training_line_count",
    }
    # Statistics only: no event list, and no single tap's own offset.
    assert "events" not in text and '"dx"' not in text and '"action"' not in text
    for stats in data["lines"][TOUCH_LEVEL]["place_profile"].values():
        assert set(stats) == {"count", "mean", "m2"}
    one_tap_dx = lines[0][0]["dx"]
    assert repr(one_tap_dx) not in text


# ---------- the store ----------


def _store() -> InMemoryGameStore:
    return InMemoryGameStore(
        party_limit=10,
        players_per_party_limit=12,
        attempts_per_party_limit=200,
        idle_expiry_seconds=7200.0,
    )


def test_a_room_takes_its_device_type_from_its_creator() -> None:
    store = _store()
    touch_room = store.create_party(TOUCH_LEVEL, "touch")
    assert touch_room.device_type == "touch"
    assert touch_room.members[touch_room.host_member_id].device_type == "touch"
    keyboard_room = store.create_party("sentence")
    assert keyboard_room.device_type == "keyboard"
    assert keyboard_room.members[keyboard_room.host_member_id].device_type == "keyboard"


def test_a_member_keeps_the_device_type_they_joined_with() -> None:
    store = _store()
    room = store.create_party(TOUCH_LEVEL, "touch")
    _, phone = store.join_party(room.code, "touch")
    _, laptop = store.join_party(room.code, "keyboard")
    _, unstated = store.join_party(room.code)
    assert (phone.device_type, laptop.device_type, unstated.device_type) == (
        "touch",
        "keyboard",
        "keyboard",
    )
    # Joining never changes the room's own type.
    assert room.device_type == "touch"


def test_renaming_a_touch_player_keeps_their_tap_profile_and_score_id() -> None:
    store = _store()
    room = store.create_party(TOUCH_LEVEL, "touch")
    alice = make_touch_player()
    store.add_player(room.id, alice)
    assert store.rename_player(room.id, alice.id, "Alicia")
    renamed = room.players[alice.id]
    assert renamed.name == "Alicia"
    assert renamed.place_profile == alice.place_profile
    assert renamed.profile == alice.profile
    assert renamed.score_id == alice.score_id
    assert renamed.threshold == alice.threshold
    assert renamed.created_at == alice.created_at
