"""game/touch_scoring.py: rhythm and place each scored with its own
floor and its own minimum, averaged with equal weight, and the touch
limit's clamps."""

from __future__ import annotations

import pytest

from keystroke_dynamics.core.features import Feature, FeatureKey
from keystroke_dynamics.core.scoring import Decision
from keystroke_dynamics.core.stats import RunningStats, from_values
from keystroke_dynamics.game.place import PlaceFeature, PlaceKey
from keystroke_dynamics.game.scoring import GAME_MAX_THRESHOLD, GAME_MIN_STD_MS
from keystroke_dynamics.game.touch_scoring import (
    TOUCH_MAX_THRESHOLD,
    TOUCH_MIN_PLACE_STD,
    TOUCH_MIN_THRESHOLD,
    TouchLine,
    build_place_profile,
    build_touch_profiles,
    calibrate_touch_threshold,
    extract_touch_line,
    line_place_feature_count,
    line_timing_feature_count,
    min_compared_place_features,
    min_compared_timing_features,
    score_touch,
)
from tests.touch_lines import TOUCH_PHRASE, tap_line, tap_lines, to_taps

#: A two-key phrase small enough to build cases by hand. One correct
#: typing gives 3 timing features (2 holds, 1 flight) and 4 position
#: features (2 tap_x, 2 tap_y). 70% of each, rounded up, is 3 and 3.
TINY = "ab"

HOLD_A: FeatureKey = ("hold", "KeyA")
HOLD_B: FeatureKey = ("hold", "KeyB")
FLIGHT: FeatureKey = ("flight", "KeyA", "KeyB")
TIMING_KEYS = (HOLD_A, HOLD_B, FLIGHT)
X_A: PlaceKey = ("tap_x", "KeyA")
Y_A: PlaceKey = ("tap_y", "KeyA")
X_B: PlaceKey = ("tap_x", "KeyB")
Y_B: PlaceKey = ("tap_y", "KeyB")
PLACE_KEYS = (X_A, Y_A, X_B, Y_B)


def _lines(typist: str = "alice", count: int = 4, **kwargs: object) -> list[TouchLine]:
    return [extract_touch_line(to_taps(line)) for line in tap_lines(typist, count, **kwargs)]


def _exact(mean: float) -> RunningStats:
    """Seen three times at exactly `mean`: a standard deviation of 0,
    so only the floor stands between a sample and a huge distance."""
    return from_values([mean, mean, mean])


def _timing_profile(mean: float = 100.0) -> dict[FeatureKey, RunningStats]:
    return {key: _exact(mean) for key in TIMING_KEYS}


def _place_profile(stats: RunningStats | None = None) -> dict[PlaceKey, RunningStats]:
    return {key: stats or _exact(0.0) for key in PLACE_KEYS}


def _line(timing: float = 100.0, place: float = 0.0) -> TouchLine:
    """Every timing feature at `timing` ms and every tap at `place`."""
    return TouchLine(
        timing=[Feature(key, timing) for key in TIMING_KEYS],
        place=[PlaceFeature(key, place) for key in PLACE_KEYS],
    )


def _score(line: TouchLine, profile=None, place_profile=None, threshold: float = 1.65):
    return score_touch(
        line,
        _timing_profile() if profile is None else profile,
        _place_profile() if place_profile is None else place_profile,
        phrase=TINY,
        threshold=threshold,
    )


# ---------- what a line produces ----------


def test_the_touch_lines_feature_counts_and_minimums() -> None:
    # 29 keys: a hold each, and a flight between each consecutive pair.
    assert line_timing_feature_count(TOUCH_PHRASE) == 29 + 28
    # 13 distinct letters and the space bar.
    assert line_place_feature_count(TOUCH_PHRASE) == 13 + 14
    # At least 70% of each: 39.9 and 18.9, rounded up.
    assert min_compared_timing_features(TOUCH_PHRASE) == 40
    assert min_compared_place_features(TOUCH_PHRASE) == 19


@pytest.mark.parametrize(
    ("phrase", "timing", "place"),
    [
        ("ab", 3, 3),  # 70% of 3 and of 4
        ("a", 1, 2),  # 70% of 1 and of 2
        ("abcde", 7, 7),  # 70% of 9 is 6.3; of 10 is exactly 7, not 8
        ("", 1, 1),  # never zero: nothing compared is never enough
    ],
)
def test_the_minimums_are_at_least_70_percent_rounded_up(
    phrase: str, timing: int, place: int
) -> None:
    assert min_compared_timing_features(phrase) == timing
    assert min_compared_place_features(phrase) == place


def test_the_feature_counts_are_what_a_real_line_produces() -> None:
    line = extract_touch_line(to_taps(tap_line()))
    assert len(line.timing) == line_timing_feature_count(TOUCH_PHRASE)
    assert len(line.place) == line_place_feature_count(TOUCH_PHRASE)


def test_extract_touch_line_has_timing_and_place() -> None:
    line = extract_touch_line(to_taps(tap_line()))
    assert {f.key[0] for f in line.timing} == {"hold", "flight"}
    assert {f.key[0] for f in line.place} == {"tap_x", "tap_y"}


def test_place_profile_counts_one_value_per_training_line() -> None:
    lines = _lines(count=4)
    profile = build_place_profile([line.place for line in lines])
    # "t" appears four times in the line, but averages to one value.
    assert profile[("tap_x", "KeyT")].count == 4
    assert all(stats.count == 4 for stats in profile.values())


# ---------- floors ----------


def test_place_floor_is_in_key_widths_not_milliseconds() -> None:
    # Each tap exactly one floor away from a spot hit identically on
    # every training line.
    score = _score(_line(place=TOUCH_MIN_PLACE_STD))
    assert score.place == pytest.approx(1.0)
    # Had position gone through the timing floor of 12, a 0.08 offset
    # would have scored 0.08 / 12 -- next to nothing.
    assert score.place > 100 * (TOUCH_MIN_PLACE_STD / GAME_MIN_STD_MS)


def test_a_real_place_spread_above_the_floor_is_used_as_it_is() -> None:
    wide = from_values([-0.3, 0.0, 0.3])  # std 0.3
    score = _score(_line(place=0.3), place_profile=_place_profile(wide))
    assert score.place == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("mean", "sample", "expected"),
    [
        pytest.param(50.0, 62.0, 1.0, id="flat-12-ms-floor"),
        pytest.param(400.0, 448.0, 1.0, id="12-percent-of-the-mean-floor"),
    ],
)
def test_timing_keeps_the_keyboard_games_floors(
    mean: float, sample: float, expected: float
) -> None:
    score = _score(_line(timing=sample), profile=_timing_profile(mean))
    assert score.rhythm == pytest.approx(expected)
    assert score.place == 0.0


# ---------- the distance ----------


def test_distance_is_the_equal_weight_average_of_rhythm_and_place() -> None:
    # Rhythm: 3 floors off on each of 3 features. Place: dead on, on
    # each of 4.
    score = _score(_line(timing=136.0, place=0.0))
    assert score.rhythm == pytest.approx(3.0)
    assert score.place == 0.0
    # (3.0 + 0.0) / 2 -- not (3 * 3.0 + 4 * 0.0) / 7, which is what a
    # mean over all seven features would give.
    assert score.distance == pytest.approx(1.5)
    assert score.compared_features == 7
    assert score.decision is Decision.MATCH


def test_the_weight_does_not_depend_on_how_many_features_each_kind_has() -> None:
    # Twice as many timing features as position features, as on the
    # real line: place still counts for half.
    profile = {("hold", f"Key{c}"): _exact(100.0) for c in "ABCDEFGH"}
    line = TouchLine(
        timing=[Feature(key, 100.0) for key in profile],
        place=[PlaceFeature(key, 0.32) for key in PLACE_KEYS],  # 4 floors off
    )
    score = score_touch(line, profile, _place_profile(), phrase=TINY, threshold=1.65)
    assert score.rhythm == 0.0
    assert score.place == pytest.approx(4.0)
    assert score.distance == pytest.approx(2.0)
    assert score.decision is Decision.NO_MATCH


def test_a_distance_exactly_on_the_limit_matches() -> None:
    score = _score(_line(timing=136.0, place=0.0), threshold=1.5)
    assert score.distance == pytest.approx(1.5)
    assert _score(_line(timing=136.0), threshold=score.distance).decision is Decision.MATCH
    assert _score(_line(timing=136.0), threshold=score.distance - 1e-9).decision is (
        Decision.NO_MATCH
    )


def test_a_feature_the_profile_has_not_seen_twice_is_skipped_not_zero() -> None:
    profile = {**_timing_profile(), ("hold", "KeyZ"): from_values([5.0])}  # Z seen once
    place_profile = {**_place_profile(), ("tap_y", "KeyZ"): from_values([0.0])}
    line = TouchLine(
        timing=[*_line(timing=112.0).timing, Feature(("hold", "KeyZ"), 900.0)],
        place=[
            *_line(place=0.08).place,
            PlaceFeature(("tap_y", "KeyZ"), 0.9),  # seen once
            PlaceFeature(("tap_x", "KeyQ"), 0.9),  # never seen
        ],
    )
    score = score_touch(line, profile, place_profile, phrase=TINY, threshold=1.65)
    assert score.compared_features == 7
    assert score.rhythm == pytest.approx(1.0)
    assert score.place == pytest.approx(1.0)


# ---------- insufficient data ----------


def _assert_insufficient(score, compared: int) -> None:
    assert score.decision is Decision.INSUFFICIENT_DATA
    assert score.distance is None
    assert score.rhythm is None
    assert score.place is None
    assert score.compared_features == compared


def test_exactly_70_percent_of_each_kind_is_enough() -> None:
    line = _line()
    enough = TouchLine(timing=line.timing, place=line.place[:3])
    score = _score(enough)
    assert score.decision is Decision.MATCH
    assert score.compared_features == 6


def test_too_little_timing_is_insufficient_however_much_place_there_is() -> None:
    line = _line()
    # 2 of 3 timing features is under 70%; all 4 position features.
    short = TouchLine(timing=line.timing[:2], place=line.place)
    _assert_insufficient(_score(short), compared=6)


def test_too_little_place_is_insufficient_however_much_timing_there_is() -> None:
    line = _line()
    # All 3 timing features; 2 of 4 position features is under 70%.
    short = TouchLine(timing=line.timing, place=line.place[:2])
    _assert_insufficient(_score(short), compared=5)


def test_each_kind_is_checked_on_its_own_not_as_a_total() -> None:
    # 6 of 7 features overall is 86%, and either shortfall alone still
    # isn't enough.
    line = _line()
    for short in (
        TouchLine(timing=line.timing[:2], place=line.place),
        TouchLine(timing=[*line.timing, *line.timing], place=line.place[:2]),
    ):
        assert _score(short).decision is Decision.INSUFFICIENT_DATA


def test_a_line_with_no_place_at_all_is_insufficient_data() -> None:
    line = TouchLine(timing=_line().timing, place=[])
    _assert_insufficient(_score(line), compared=3)


def test_a_line_with_no_rhythm_at_all_is_insufficient_data() -> None:
    line = TouchLine(timing=[], place=_line().place)
    _assert_insufficient(_score(line), compared=4)


def test_an_empty_profile_is_insufficient_data() -> None:
    line = extract_touch_line(to_taps(tap_line()))
    _assert_insufficient(score_touch(line, {}, {}, phrase=TOUCH_PHRASE, threshold=1.65), compared=0)


def test_half_a_line_is_insufficient_data() -> None:
    profile, place_profile = build_touch_profiles(_lines())
    half = tap_line(line=9)[: len(TOUCH_PHRASE)]  # the first half of the keys
    score = score_touch(
        extract_touch_line(to_taps(half)),
        profile,
        place_profile,
        phrase=TOUCH_PHRASE,
        threshold=1.65,
    )
    assert score.decision is Decision.INSUFFICIENT_DATA
    assert score.compared_features > 0


@pytest.mark.parametrize(
    ("keys", "scorable"),
    [
        # 21 keys: 41 timing features (min 40), and 12 distinct keys
        # give 23 position features (min 19).
        pytest.param(21, True, id="just-enough-timing"),
        # 20 keys: 39 timing features, one short.
        pytest.param(20, False, id="one-timing-feature-short"),
    ],
)
def test_the_real_lines_timing_minimum_is_40(keys: int, scorable: bool) -> None:
    profile, place_profile = build_touch_profiles(_lines())
    part = tap_line(line=9)[: 2 * keys]
    line = extract_touch_line(to_taps(part))
    assert len(line.timing) == 2 * keys - 1
    assert len(line.place) >= min_compared_place_features(TOUCH_PHRASE)
    score = score_touch(line, profile, place_profile, phrase=TOUCH_PHRASE, threshold=1.65)
    assert (score.decision is not Decision.INSUFFICIENT_DATA) is scorable


# ---------- whole lines ----------


def test_a_typists_own_line_scores_well_under_someone_elses() -> None:
    lines = _lines("alice")
    profile, place_profile = build_touch_profiles(lines)
    threshold = calibrate_touch_threshold(lines, phrase=TOUCH_PHRASE)

    def score(typist: str):
        line = extract_touch_line(to_taps(tap_line(typist, line=9)))
        return score_touch(line, profile, place_profile, phrase=TOUCH_PHRASE, threshold=threshold)

    own, other = score("alice"), score("bob")
    assert own.decision is Decision.MATCH
    assert other.decision is Decision.NO_MATCH
    assert own.distance < other.distance
    assert own.compared_features == other.compared_features == 84


def test_own_rhythm_with_every_tap_shifted_0_35_of_a_key_fails() -> None:
    # The case that passed when distance was a mean over all features
    # (57 timing, 27 position): Alice's own rhythm, at her own pace,
    # with every tap 0.35 of a key off in both directions.
    lines = _lines("alice")
    profile, place_profile = build_touch_profiles(lines)
    threshold = calibrate_touch_threshold(lines, phrase=TOUCH_PHRASE)
    shifted = extract_touch_line(to_taps(tap_line("alice", line=9, shift=(0.35, -0.35))))
    score = score_touch(shifted, profile, place_profile, phrase=TOUCH_PHRASE, threshold=threshold)
    assert score.rhythm < 0.5  # the rhythm really is hers
    assert score.place > 3.0
    assert score.distance == pytest.approx((score.rhythm + score.place) / 2)
    assert score.distance > TOUCH_MAX_THRESHOLD >= threshold
    assert score.decision is Decision.NO_MATCH
    # The old feature-weighted mean, for the record, was under the limit.
    old = (57 * score.rhythm + 27 * score.place) / 84
    assert old < threshold


def test_the_same_rhythm_from_a_different_grip_moves_place_and_not_rhythm() -> None:
    lines = _lines("alice")
    profile, place_profile = build_touch_profiles(lines)

    def score(shift: tuple[float, float]):
        line = extract_touch_line(to_taps(tap_line("alice", line=9, shift=shift)))
        return score_touch(line, profile, place_profile, phrase=TOUCH_PHRASE, threshold=1.65)

    usual, shifted = score((0.0, 0.0)), score((0.3, -0.3))
    assert shifted.rhythm == pytest.approx(usual.rhythm)
    assert shifted.place > usual.place + 1.0


# ---------- the limit ----------


def test_the_touch_clamps_are_the_plans() -> None:
    assert TOUCH_MIN_THRESHOLD == 1.65
    assert TOUCH_MAX_THRESHOLD == GAME_MAX_THRESHOLD == 2.0


def test_identical_training_lines_get_the_minimum_limit() -> None:
    line = extract_touch_line(to_taps(tap_line()))
    assert calibrate_touch_threshold([line] * 4, phrase=TOUCH_PHRASE) == TOUCH_MIN_THRESHOLD


def test_one_stumbled_training_line_cannot_push_the_limit_past_the_maximum() -> None:
    # Three lines that agree and one tapped by someone else entirely:
    # held out, that one scores far above 2.0 against the other three.
    lines = [*_lines("alice", 3), extract_touch_line(to_taps(tap_line("bob", speed=2.0)))]
    profile, place_profile = build_touch_profiles(lines[:3])
    stumble = score_touch(lines[3], profile, place_profile, phrase=TOUCH_PHRASE, threshold=1.65)
    assert stumble.distance > TOUCH_MAX_THRESHOLD
    assert calibrate_touch_threshold(lines, phrase=TOUCH_PHRASE) == TOUCH_MAX_THRESHOLD


def test_training_lines_that_cannot_be_scored_get_the_minimum_limit() -> None:
    # Two lines: each held-out profile has seen every feature once,
    # below the minimum count, so nothing is compared.
    assert calibrate_touch_threshold(_lines(count=2), phrase=TOUCH_PHRASE) == TOUCH_MIN_THRESHOLD
    assert calibrate_touch_threshold([], phrase=TOUCH_PHRASE) == TOUCH_MIN_THRESHOLD


@pytest.mark.parametrize("wobble", [0.02, 0.1, 0.2, 0.4])
def test_the_limit_is_always_within_the_clamps(wobble: float) -> None:
    limit = calibrate_touch_threshold(_lines(wobble=wobble), phrase=TOUCH_PHRASE)
    assert TOUCH_MIN_THRESHOLD <= limit <= TOUCH_MAX_THRESHOLD
