"""Game-tuned scoring: core/scoring.py's real scaled_manhattan_score,
reused unmodified in behavior for every other caller (see its
min_std_ratio parameter's docstring), just called with different
constants sized for 3-8 training lines instead of that module's own
benchmark-sized defaults. No second implementation of scoring lives
here -- see PARTY_LAUNCH_PLAN.md Part 1 section 5, whose mockup rules
these constants come from directly.
"""

from __future__ import annotations

from keystroke_dynamics.core.features import Feature, FeatureKey
from keystroke_dynamics.core.scoring import DEFAULT_THRESHOLD, ScoreResult, scaled_manhattan_score
from keystroke_dynamics.core.stats import RunningStats, update

#: Game tuning -- NOT core/scoring.py's defaults, which stay exactly
#: as they are for every other caller. Labeled "game tuning" here and
#: again in How It Works, per the plan: the 9.1% benchmark EER is
#: never this game's accuracy number.
GAME_MIN_FEATURE_COUNT = 2
GAME_MIN_STD_MS = 12.0
GAME_MIN_STD_RATIO = 0.12
GAME_MAX_COMPARED_FEATURES = 20
GAME_MIN_COMPARED_FRACTION = 0.7
GAME_MIN_THRESHOLD = 1.3
GAME_MAX_THRESHOLD = 3.5
GAME_THRESHOLD_MULTIPLIER = 1.2


def line_feature_count(phrase: str) -> int:
    """How many distinct (hold + flight) features one correct typing
    of `phrase` produces -- e.g. 11 for "nukiae" (6 distinct letters,
    5 distinct consecutive pairs), matching the plan's own "about 11
    features" for the one-word line. Used to size
    min_compared_features as a fraction of what a given line can
    actually produce, not a flat number every line must clear
    regardless of length.
    """
    chars = list(phrase)
    holds = set(chars)
    flights = {(a, b) for a, b in zip(chars, chars[1:], strict=False)}
    return len(holds) + len(flights)


def min_compared_features_for(phrase: str) -> int:
    """At least GAME_MIN_COMPARED_FRACTION of the line's features,
    capped at GAME_MAX_COMPARED_FEATURES -- never less than 1, so a
    profile with zero trained features is still correctly
    INSUFFICIENT_DATA rather than trivially satisfied."""
    n = line_feature_count(phrase)
    return max(1, min(GAME_MAX_COMPARED_FEATURES, int(n * GAME_MIN_COMPARED_FRACTION)))


def build_profile(training_lines: list[list[Feature]]) -> dict[FeatureKey, RunningStats]:
    """One RunningStats per distinct feature key, folding every
    training line's features into it via Welford's algorithm
    (core.stats.update) -- the same incremental update the account
    system's db/repository.py uses, just accumulated here in memory
    instead of a database row.
    """
    profile: dict[FeatureKey, RunningStats] = {}
    for features in training_lines:
        for feature in features:
            prior = profile.get(feature.key, RunningStats())
            profile[feature.key] = update(prior, feature.value_ms)
    return profile


def score_sample(
    sample: list[Feature],
    profile: dict[FeatureKey, RunningStats],
    *,
    phrase: str,
    threshold: float = DEFAULT_THRESHOLD,
) -> ScoreResult:
    return scaled_manhattan_score(
        sample,
        profile,
        min_feature_count=GAME_MIN_FEATURE_COUNT,
        min_std_ms=GAME_MIN_STD_MS,
        min_std_ratio=GAME_MIN_STD_RATIO,
        min_compared_features=min_compared_features_for(phrase),
        threshold=threshold,
    )


def calibrate_threshold(training_lines: list[list[Feature]], *, phrase: str) -> float:
    """Leave-one-line-out calibration: score each training line
    against a profile built from every OTHER training line, take the
    worst (highest) held-out score, and set the limit at
    GAME_THRESHOLD_MULTIPLIER times that -- clamped to
    [GAME_MIN_THRESHOLD, GAME_MAX_THRESHOLD]. Falls back to the clamp's
    lower bound if no line produced a scorable held-out result (e.g.
    too few training lines, or a line too messy to compare).
    """
    held_out_scores: list[float] = []
    for i in range(len(training_lines)):
        other_lines = [lines for j, lines in enumerate(training_lines) if j != i]
        if not other_lines:
            continue
        profile = build_profile(other_lines)
        # threshold doesn't matter here -- only .score is used, never
        # .decision -- but score_sample needs one to construct a result.
        result = score_sample(
            training_lines[i], profile, phrase=phrase, threshold=GAME_MIN_THRESHOLD
        )
        if result.score is not None:
            held_out_scores.append(result.score)

    if not held_out_scores:
        return GAME_MIN_THRESHOLD
    raw = max(held_out_scores) * GAME_THRESHOLD_MULTIPLIER
    return max(GAME_MIN_THRESHOLD, min(GAME_MAX_THRESHOLD, raw))
