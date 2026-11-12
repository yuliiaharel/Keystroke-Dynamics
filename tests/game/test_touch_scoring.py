"""game/touch_scoring.py: rhythm and place scored together, each with
its own floor, and the touch limit's clamps."""

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
    score_touch,
    touch_min_compared_features,
)
from tests.touch_lines import TOUCH_PHRASE, tap_line, tap_lines, to_taps

#: A two-key phrase whose minimum is small enough to build cases by
#: hand: 2 holds + 1 flight + 2 tap_x + 2 tap_y = 7 features, minimum 4.
#: (int(7 * 0.7) == 4.)
TINY = "ab"

HOLD_A: FeatureKey = ("hold", "KeyA")
HOLD_B: FeatureKey = ("hold", "KeyB")
X_A: PlaceKey = ("tap_x", "KeyA")
Y_A: PlaceKey = ("tap_y", "KeyA")
X_B: PlaceKey = ("tap_x", "KeyB")
Y_B: PlaceKey = ("tap_y", "KeyB")


def _lines(typist: str = "alice", count: int = 4, **kwargs: object) -> list[TouchLine]:
    return [extract_touch_line(to_taps(line)) for line in tap_lines(typist, count, **kwargs)]


def _exact(mean: float) -> RunningStats:
    """Seen three times at exactly `mean`: a standard deviation of 0,
    so only the floor stands between a sample and a huge distance."""
    return from_values([mean, mean, mean])


# ---------- what a line produces ----------


def test_the_touch_lines_feature_counts() -> None:
    # 29 keys: a hold each, and a flight between each consecutive pair.
    assert line_timing_feature_count(TOUCH_PHRASE) == 29 + 28
    # 13 distinct letters and the space bar.
    assert line_place_feature_count(TOUCH_PHRASE) == 13 + 14
    assert touch_min_compared_features(TOUCH_PHRASE) == 58  # int(84 * 0.7)
    # More than either kind alone can supply, so a scored line always
    # compared some rhythm and some place.
    assert touch_min_compared_features(TOUCH_PHRASE) > line_timing_feature_count(TOUCH_PHRASE)
    assert touch_min_compared_features(TOUCH_PHRASE) > line_place_feature_count(TOUCH_PHRASE)


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
    profile = {HOLD_A: _exact(100.0), HOLD_B: _exact(100.0)}
    place_profile = {X_A: _exact(0.0), Y_A: _exact(0.0), X_B: _exact(0.0), Y_B: _exact(0.0)}
    line = TouchLine(
        timing=[Feature(HOLD_A, 100.0), Feature(HOLD_B, 100.0)],
        # Each exactly one floor away from a spot hit identically
        # every training line.
        place=[
            PlaceFeature(X_A, TOUCH_MIN_PLACE_STD),
            PlaceFeature(Y_A, -TOUCH_MIN_PLACE_STD),
            PlaceFeature(X_B, TOUCH_MIN_PLACE_STD),
            PlaceFeature(Y_B, TOUCH_MIN_PLACE_STD),
        ],
    )
    score = score_touch(line, profile, place_profile, phrase=TINY, threshold=1.65)
    assert score.place == pytest.approx(1.0)
    # Had position gone through the timing floor of 12, a 0.08 offset
    # would have scored 0.08 / 12 -- next to nothing.
    assert score.place > 100 * (TOUCH_MIN_PLACE_STD / GAME_MIN_STD_MS)


def test_a_real_place_spread_above_the_floor_is_used_as_it_is() -> None:
    wide = from_values([-0.3, 0.0, 0.3])  # std 0.3
    profile = {HOLD_A: _exact(100.0), HOLD_B: _exact(100.0)}
    place_profile = {X_A: wide, Y_A: wide, X_B: wide, Y_B: wide}
    line = TouchLine(
        timing=[Feature(HOLD_A, 100.0), Feature(HOLD_B, 100.0)],
        place=[PlaceFeature(k, 0.3) for k in (X_A, Y_A, X_B, Y_B)],
    )
    score = score_touch(line, profile, place_profile, phrase=TINY, threshold=1.65)
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
    profile = {HOLD_A: _exact(mean), HOLD_B: _exact(mean)}
    place_profile = {X_A: _exact(0.0), Y_A: _exact(0.0)}
    line = TouchLine(
        timing=[Feature(HOLD_A, sample), Feature(HOLD_B, sample)],
        place=[PlaceFeature(X_A, 0.0), PlaceFeature(Y_A, 0.0)],
    )
    score = score_touch(line, profile, place_profile, phrase=TINY, threshold=1.65)
    assert score.rhythm == pytest.approx(expected)
    assert score.place == 0.0


# ---------- mixed scoring ----------


def test_distance_is_the_mean_over_every_compared_feature() -> None:
    profile = {HOLD_A: _exact(100.0), HOLD_B: _exact(100.0)}
    place_profile = {X_A: _exact(0.0), Y_A: _exact(0.0), X_B: _exact(0.0), Y_B: _exact(0.0)}
    line = TouchLine(
        # Rhythm: 3 floors off on each of 2 features.
        timing=[Feature(HOLD_A, 136.0), Feature(HOLD_B, 136.0)],
        # Place: dead on, on each of 4 features.
        place=[PlaceFeature(k, 0.0) for k in (X_A, Y_A, X_B, Y_B)],
    )
    score = score_touch(line, profile, place_profile, phrase=TINY, threshold=1.65)
    assert score.rhythm == pytest.approx(3.0)
    assert score.place == 0.0
    # (2 * 3.0 + 4 * 0.0) / 6: weighted by how many features each
    # kind had, not a plain average of the two scores.
    assert score.distance == pytest.approx(1.0)
    assert score.compared_features == 6
    assert score.decision is Decision.MATCH


def test_the_decision_uses_distance_not_rhythm_or_place_alone() -> None:
    profile = {HOLD_A: _exact(100.0), HOLD_B: _exact(100.0)}
    place_profile = {X_A: _exact(0.0), Y_A: _exact(0.0), X_B: _exact(0.0), Y_B: _exact(0.0)}
    line = TouchLine(
        timing=[Feature(HOLD_A, 100.0), Feature(HOLD_B, 100.0)],
        place=[PlaceFeature(k, 0.4) for k in (X_A, Y_A, X_B, Y_B)],  # 5 floors off
    )
    score = score_touch(line, profile, place_profile, phrase=TINY, threshold=1.65)
    assert score.rhythm == 0.0
    assert score.place == pytest.approx(5.0)
    assert score.distance == pytest.approx(20 / 6)
    assert score.decision is Decision.NO_MATCH


def test_a_feature_the_profile_has_not_seen_twice_is_skipped_not_zero() -> None:
    profile = {HOLD_A: _exact(100.0), HOLD_B: from_values([100.0])}  # B seen once
    place_profile = {X_A: _exact(0.0), Y_A: _exact(0.0), X_B: from_values([0.0])}
    line = TouchLine(
        timing=[Feature(HOLD_A, 112.0), Feature(HOLD_B, 900.0), Feature(("hold", "KeyZ"), 5.0)],
        place=[
            PlaceFeature(X_A, 0.08),
            PlaceFeature(Y_A, 0.08),
            PlaceFeature(X_B, 3.0),
            PlaceFeature(Y_B, 0.5),
        ],
    )
    score = score_touch(line, profile, place_profile, phrase="a", threshold=1.65)
    assert score.compared_features == 3
    assert score.rhythm == pytest.approx(1.0)
    assert score.place == pytest.approx(1.0)


# ---------- insufficient data ----------


def _scorable_tiny() -> tuple[dict, dict, TouchLine]:
    profile = {HOLD_A: _exact(100.0), HOLD_B: _exact(100.0)}
    place_profile = {X_A: _exact(0.0), Y_A: _exact(0.0), X_B: _exact(0.0), Y_B: _exact(0.0)}
    line = TouchLine(
        timing=[Feature(HOLD_A, 100.0), Feature(HOLD_B, 100.0)],
        place=[PlaceFeature(k, 0.0) for k in (X_A, Y_A, X_B, Y_B)],
    )
    return profile, place_profile, line


def _assert_insufficient(score, compared: int) -> None:
    assert score.decision is Decision.INSUFFICIENT_DATA
    assert score.distance is None
    assert score.rhythm is None
    assert score.place is None
    assert score.compared_features == compared


def test_too_few_compared_features_is_insufficient_data() -> None:
    profile, place_profile, line = _scorable_tiny()
    assert touch_min_compared_features(TINY) == 4
    short = TouchLine(timing=line.timing[:1], place=line.place[:2])
    _assert_insufficient(
        score_touch(short, profile, place_profile, phrase=TINY, threshold=1.65), compared=3
    )


def test_exactly_the_minimum_is_enough() -> None:
    profile, place_profile, line = _scorable_tiny()
    enough = TouchLine(timing=line.timing[:1], place=line.place[:3])
    score = score_touch(enough, profile, place_profile, phrase=TINY, threshold=1.65)
    assert score.decision is Decision.MATCH
    assert score.compared_features == 4


def test_a_line_with_no_place_at_all_is_insufficient_data() -> None:
    # Enough timing features to clear the minimum on their own.
    profile = {("hold", f"Key{c}"): _exact(100.0) for c in "ABCDE"}
    line = TouchLine(timing=[Feature(k, 100.0) for k in profile], place=[])
    _assert_insufficient(score_touch(line, profile, {}, phrase=TINY, threshold=1.65), compared=5)


def test_a_line_with_no_rhythm_at_all_is_insufficient_data() -> None:
    _, place_profile, line = _scorable_tiny()
    only_place = TouchLine(timing=[], place=line.place)
    _assert_insufficient(
        score_touch(only_place, {}, place_profile, phrase=TINY, threshold=1.65), compared=4
    )


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
    assert 0 < score.compared_features < touch_min_compared_features(TOUCH_PHRASE)


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
