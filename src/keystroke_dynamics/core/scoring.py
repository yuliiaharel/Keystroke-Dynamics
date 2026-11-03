"""Score a typing sample against a stored profile.

Fixes the old app's scoring bugs (see MODERNIZATION_PLAN.md Phase 0):
a feature missing from the profile is skipped, never treated as a
(0, 0) data point; the denominator is how many features were actually
compared, not the profile's total size; and there's no ambiguous
"Wait" zone between two thresholds -- once there's enough data, the
decision is always exactly MATCH or NO_MATCH.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from keystroke_dynamics.core.features import Feature, FeatureKey
from keystroke_dynamics.core.stats import RunningStats

DEFAULT_MIN_FEATURE_COUNT = 5
DEFAULT_MIN_STD_MS = 1.0
DEFAULT_MIN_COMPARED_FEATURES = 20
#: Provisional: the mean of each subject's own EER-crossover threshold
#: on the Phase 3 benchmark (evaluation/results.md), using this exact
#: scoring method. Not an independently-validated operating point --
#: see that file's Limitation section (one fixed password, not free
#: text) before trusting it as a real decision boundary.
DEFAULT_THRESHOLD = 1.0724
#: Provisional -- three_sigma_score isn't the method this app uses to
#: decide anything (see its docstring), so this is left uncalibrated.
DEFAULT_THREE_SIGMA_MATCH_RATIO = 0.5


class Decision(StrEnum):
    MATCH = "match"
    NO_MATCH = "no_match"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass(frozen=True)
class ScoreResult:
    """score and threshold are only meaningful together, and their
    units depend on which scoring function produced them: lower is
    more similar for scaled_manhattan_score's distance, higher is more
    similar for three_sigma_score's match ratio. score is None when
    decision is INSUFFICIENT_DATA.
    """

    decision: Decision
    score: float | None
    threshold: float
    compared_features: int


def _effective_std(stats: RunningStats, min_std_ms: float) -> float:
    """Never zero, so dividing by it is always safe."""
    return max(stats.std or 0.0, min_std_ms)


def scaled_manhattan_score(
    sample: list[Feature],
    profile: dict[FeatureKey, RunningStats],
    *,
    min_feature_count: int = DEFAULT_MIN_FEATURE_COUNT,
    min_std_ms: float = DEFAULT_MIN_STD_MS,
    min_compared_features: int = DEFAULT_MIN_COMPARED_FEATURES,
    threshold: float = DEFAULT_THRESHOLD,
) -> ScoreResult:
    """For each sample feature with a sufficiently-trained match in
    profile, computes abs(sample_value - profile_mean) / profile_std.
    The score is the average of those distances; lower means more
    similar. MATCH when score <= threshold.
    """
    distances: list[float] = []

    for feature in sample:
        stats = profile.get(feature.key)
        if stats is None or stats.count < min_feature_count:
            continue  # never treat a missing/undertrained feature as zero
        std = _effective_std(stats, min_std_ms)
        distances.append(abs(feature.value_ms - stats.mean) / std)

    if not distances or len(distances) < min_compared_features:
        return ScoreResult(
            decision=Decision.INSUFFICIENT_DATA,
            score=None,
            threshold=threshold,
            compared_features=len(distances),
        )

    score = sum(distances) / len(distances)
    decision = Decision.MATCH if score <= threshold else Decision.NO_MATCH
    return ScoreResult(
        decision=decision, score=score, threshold=threshold, compared_features=len(distances)
    )


def plain_manhattan_score(
    sample: list[Feature],
    profile: dict[FeatureKey, RunningStats],
    *,
    min_feature_count: int = DEFAULT_MIN_FEATURE_COUNT,
    min_compared_features: int = DEFAULT_MIN_COMPARED_FEATURES,
    threshold: float = DEFAULT_THRESHOLD,
) -> ScoreResult:
    """Unscaled Manhattan distance: abs(sample_value - profile_mean),
    not divided by profile_std. The score is the average across
    compared features; lower means more similar. MATCH when
    score <= threshold.

    For comparison against scaled_manhattan_score in Phase 3 only.
    Without scaling, a feature with naturally larger timings (e.g. a
    flight vs. a hold) dominates the average regardless of how
    variable it actually is for this profile -- exactly what scaling
    by profile_std corrects for.
    """
    distances: list[float] = []

    for feature in sample:
        stats = profile.get(feature.key)
        if stats is None or stats.count < min_feature_count:
            continue
        distances.append(abs(feature.value_ms - stats.mean))

    if not distances or len(distances) < min_compared_features:
        return ScoreResult(
            decision=Decision.INSUFFICIENT_DATA,
            score=None,
            threshold=threshold,
            compared_features=len(distances),
        )

    score = sum(distances) / len(distances)
    decision = Decision.MATCH if score <= threshold else Decision.NO_MATCH
    return ScoreResult(
        decision=decision, score=score, threshold=threshold, compared_features=len(distances)
    )


def three_sigma_score(
    sample: list[Feature],
    profile: dict[FeatureKey, RunningStats],
    *,
    min_feature_count: int = DEFAULT_MIN_FEATURE_COUNT,
    min_std_ms: float = DEFAULT_MIN_STD_MS,
    min_compared_features: int = DEFAULT_MIN_COMPARED_FEATURES,
    match_ratio: float = DEFAULT_THREE_SIGMA_MATCH_RATIO,
) -> ScoreResult:
    """A corrected version of the original app's 3-sigma matching
    rule: counts what fraction of compared features fall within 3
    standard deviations of their profile mean. MATCH when that
    fraction is >= match_ratio.

    For comparison against scaled_manhattan_score in Phase 3 only --
    not the method this app actually uses to decide anything.
    """
    within = 0
    compared = 0

    for feature in sample:
        stats = profile.get(feature.key)
        if stats is None or stats.count < min_feature_count:
            continue
        std = _effective_std(stats, min_std_ms)
        compared += 1
        if abs(feature.value_ms - stats.mean) <= 3 * std:
            within += 1

    if compared == 0 or compared < min_compared_features:
        return ScoreResult(
            decision=Decision.INSUFFICIENT_DATA,
            score=None,
            threshold=match_ratio,
            compared_features=compared,
        )

    score = within / compared
    decision = Decision.MATCH if score >= match_ratio else Decision.NO_MATCH
    return ScoreResult(
        decision=decision, score=score, threshold=match_ratio, compared_features=compared
    )
