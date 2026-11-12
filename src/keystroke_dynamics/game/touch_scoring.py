"""Touch scoring: tap rhythm and tap position against a touch player's
profile (docs/plans/active/MOBILE_PLAN.md Phase 1 section 5).

Rhythm is scored exactly as the keyboard game scores it -- the same
features, the same floors -- and Place the same way with its own
floor, because a position isn't a time. Both go through
core.scoring.scaled_distance, the one copy of the scaled Manhattan
formula. Nothing here is called for a keyboard room, so keyboard
scores can't move (tests/game/test_keyboard_golden.py).

Every constant here is provisional game tuning, like game/scoring.py's.
Touch typing has no benchmark behind it: the 9.1% benchmark result is
for a physical keyboard and says nothing about this.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from keystroke_dynamics.core.events import pair_presses
from keystroke_dynamics.core.features import Feature, FeatureKey, extract_features
from keystroke_dynamics.core.scoring import Decision, scaled_distance
from keystroke_dynamics.core.stats import RunningStats, update
from keystroke_dynamics.game.place import PlaceFeature, PlaceKey, extract_place_features
from keystroke_dynamics.game.scoring import (
    GAME_MAX_THRESHOLD,
    GAME_MIN_COMPARED_FRACTION,
    GAME_MIN_FEATURE_COUNT,
    GAME_MIN_STD_MS,
    GAME_MIN_STD_RATIO,
    GAME_THRESHOLD_MULTIPLIER,
    build_profile,
)
from keystroke_dynamics.game.taps import TapEvent, to_key_events

#: Provisional: from one small phone test (design/typing-twin-touch.html).
#: Phase 4 of the mobile plan retests it.
TOUCH_MIN_THRESHOLD = 1.65
#: The keyboard game's maximum, until Phase 4 says whether it suits touch.
TOUCH_MAX_THRESHOLD = GAME_MAX_THRESHOLD
#: The floor on a position's standard deviation, in key widths or
#: heights. Without it, a key someone happened to hit in the same spot
#: on every training line would make any later tap look far away.
TOUCH_MIN_PLACE_STD = 0.08


@dataclass(frozen=True)
class TouchLine:
    """One typed line's features: timing as the keyboard game extracts
    it, and where the taps landed."""

    timing: list[Feature]
    place: list[PlaceFeature]


@dataclass(frozen=True)
class TouchScore:
    decision: Decision
    #: The mean over every compared feature, timing and position
    #: alike -- what the limit is applied to. None, with rhythm and
    #: place, when decision is INSUFFICIENT_DATA.
    distance: float | None
    #: The mean over the compared timing features only.
    rhythm: float | None
    #: The mean over the compared position features only.
    place: float | None
    threshold: float
    compared_features: int


def extract_touch_line(events: Sequence[TapEvent]) -> TouchLine:
    return TouchLine(
        timing=extract_features(pair_presses(to_key_events(events))),
        place=extract_place_features(events),
    )


def line_timing_feature_count(phrase: str) -> int:
    """How many timing features one correct typing of `phrase` gives
    the scorer: core.features emits a hold for every key press and a
    flight for every consecutive pair, repeats included."""
    return max(0, 2 * len(phrase) - 1)


def line_place_feature_count(phrase: str) -> int:
    """How many distinct position features one correct typing of
    `phrase` produces: a tap_y for every distinct key, and a tap_x for
    every one but the space bar."""
    keys = set(phrase)
    return len(keys) + len(keys - {" "})


def touch_min_compared_features(phrase: str) -> int:
    """GAME_MIN_COMPARED_FRACTION of everything a correct line gives
    the scorer, timing and position together. Deliberately without the
    keyboard game's cap of 20: the touch line produces more position
    features alone than that cap, so a capped minimum could be met
    with no rhythm at all.

    For the touch line this is more than either kind can supply on
    its own, so a scored line always compared some of each."""
    total = line_timing_feature_count(phrase) + line_place_feature_count(phrase)
    return max(1, int(total * GAME_MIN_COMPARED_FRACTION))


def build_place_profile(lines: Sequence[Sequence[PlaceFeature]]) -> dict[PlaceKey, RunningStats]:
    """One RunningStats per position feature, one value per training
    line -- extract_place_features already averaged repeats."""
    profile: dict[PlaceKey, RunningStats] = {}
    for features in lines:
        for feature in features:
            profile[feature.key] = update(profile.get(feature.key, RunningStats()), feature.value)
    return profile


def score_touch(
    line: TouchLine,
    profile: Mapping[FeatureKey, RunningStats],
    place_profile: Mapping[PlaceKey, RunningStats],
    *,
    phrase: str,
    threshold: float,
) -> TouchScore:
    """Scaled Manhattan distance over timing and position features.
    A feature the profile hasn't seen at least GAME_MIN_FEATURE_COUNT
    times is skipped, never treated as zero -- the keyboard game's rule.

    INSUFFICIENT_DATA when too few features could be compared, or when
    either kind is missing entirely: Rhythm and Place are each a mean,
    and there is no mean of nothing.
    """
    rhythm_parts = [
        scaled_distance(
            f.value_ms, stats, min_std=GAME_MIN_STD_MS, min_std_ratio=GAME_MIN_STD_RATIO
        )
        for f in line.timing
        if (stats := profile.get(f.key)) is not None and stats.count >= GAME_MIN_FEATURE_COUNT
    ]
    place_parts = [
        scaled_distance(f.value, stats, min_std=TOUCH_MIN_PLACE_STD)
        for f in line.place
        if (stats := place_profile.get(f.key)) is not None and stats.count >= GAME_MIN_FEATURE_COUNT
    ]
    compared = len(rhythm_parts) + len(place_parts)
    if not rhythm_parts or not place_parts or compared < touch_min_compared_features(phrase):
        return TouchScore(
            decision=Decision.INSUFFICIENT_DATA,
            distance=None,
            rhythm=None,
            place=None,
            threshold=threshold,
            compared_features=compared,
        )
    distance = (sum(rhythm_parts) + sum(place_parts)) / compared
    return TouchScore(
        decision=Decision.MATCH if distance <= threshold else Decision.NO_MATCH,
        distance=distance,
        rhythm=sum(rhythm_parts) / len(rhythm_parts),
        place=sum(place_parts) / len(place_parts),
        threshold=threshold,
        compared_features=compared,
    )


def build_touch_profiles(
    lines: Sequence[TouchLine],
) -> tuple[dict[FeatureKey, RunningStats], dict[PlaceKey, RunningStats]]:
    return (
        build_profile([line.timing for line in lines]),
        build_place_profile([line.place for line in lines]),
    )


def calibrate_touch_threshold(lines: Sequence[TouchLine], *, phrase: str) -> float:
    """game/scoring.py's leave-one-line-out calibration, with the
    touch scorer and the touch clamps: the worst held-out distance
    times GAME_THRESHOLD_MULTIPLIER, kept within
    [TOUCH_MIN_THRESHOLD, TOUCH_MAX_THRESHOLD]. The lower clamp when
    no line could be scored against the others."""
    held_out: list[float] = []
    for i, line in enumerate(lines):
        others = [other for j, other in enumerate(lines) if j != i]
        if not others:
            continue
        profile, place_profile = build_touch_profiles(others)
        # The threshold passed here is unused: only .distance is read.
        score = score_touch(
            line, profile, place_profile, phrase=phrase, threshold=TOUCH_MIN_THRESHOLD
        )
        if score.distance is not None:
            held_out.append(score.distance)
    if not held_out:
        return TOUCH_MIN_THRESHOLD
    raw = max(held_out) * GAME_THRESHOLD_MULTIPLIER
    return max(TOUCH_MIN_THRESHOLD, min(TOUCH_MAX_THRESHOLD, raw))
