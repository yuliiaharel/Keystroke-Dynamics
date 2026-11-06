import pytest

from keystroke_dynamics.core.features import Feature, FeatureKey
from keystroke_dynamics.core.scoring import (
    Decision,
    plain_manhattan_score,
    scaled_manhattan_score,
    three_sigma_score,
)
from keystroke_dynamics.core.stats import RunningStats, from_values

HOLD_A: FeatureKey = ("hold", "KeyA")
HOLD_B: FeatureKey = ("hold", "KeyB")


def make_profile(items: dict[FeatureKey, list[float]]) -> dict[FeatureKey, RunningStats]:
    return {key: from_values(values) for key, values in items.items()}


# --- Required behaviors -----------------------------------------------


def test_missing_feature_excluded_from_scoring() -> None:
    profile = make_profile({HOLD_A: [50.0] * 10})
    sample = [Feature(HOLD_A, 50.0), Feature(HOLD_B, 999.0)]  # HOLD_B not in profile
    result = scaled_manhattan_score(sample, profile, min_compared_features=1)
    assert result.compared_features == 1


def test_undertrained_feature_excluded_from_scoring() -> None:
    profile = make_profile({HOLD_A: [50.0, 51.0]})  # count=2, below default min of 5
    result = scaled_manhattan_score([Feature(HOLD_A, 50.0)], profile, min_compared_features=1)
    assert result.decision == Decision.INSUFFICIENT_DATA
    assert result.compared_features == 0


def test_too_few_compared_features_returns_insufficient_data() -> None:
    profile = make_profile({HOLD_A: [50.0] * 10})
    result = scaled_manhattan_score([Feature(HOLD_A, 50.0)], profile, min_compared_features=5)
    assert result.decision == Decision.INSUFFICIENT_DATA
    assert result.score is None


def test_identical_means_score_zero() -> None:
    profile = make_profile({HOLD_A: [50.0] * 10, HOLD_B: [80.0] * 10})
    sample = [Feature(HOLD_A, 50.0), Feature(HOLD_B, 80.0)]
    result = scaled_manhattan_score(sample, profile, min_compared_features=2)
    assert result.score == pytest.approx(0.0)
    assert result.decision == Decision.MATCH


def test_shifted_sample_scores_higher_as_shift_grows() -> None:
    profile = make_profile({HOLD_A: [50.0] * 10})  # zero variance -> std clamps to the 1ms floor
    baseline = scaled_manhattan_score([Feature(HOLD_A, 50.0)], profile, min_compared_features=1)
    small_shift = scaled_manhattan_score([Feature(HOLD_A, 55.0)], profile, min_compared_features=1)
    big_shift = scaled_manhattan_score([Feature(HOLD_A, 70.0)], profile, min_compared_features=1)

    assert baseline.score == pytest.approx(0.0)
    assert baseline.score is not None
    assert small_shift.score is not None
    assert big_shift.score is not None
    assert baseline.score < small_shift.score < big_shift.score


def test_effective_std_uses_actual_std_when_above_the_floor() -> None:
    low_spread = make_profile({HOLD_A: [49.0, 50.0, 51.0]})  # std = 1.0
    high_spread = make_profile({HOLD_A: [0.0, 50.0, 100.0]})  # std = 50.0

    low = scaled_manhattan_score(
        [Feature(HOLD_A, 60.0)], low_spread, min_feature_count=1, min_compared_features=1
    )
    high = scaled_manhattan_score(
        [Feature(HOLD_A, 60.0)], high_spread, min_feature_count=1, min_compared_features=1
    )

    assert low.score is not None
    assert high.score is not None
    # Same sample value, but the high-spread profile finds it far less
    # surprising (smaller distance) than the low-spread one.
    assert high.score < low.score


def test_min_std_ratio_defaults_to_zero_and_never_changes_existing_behavior() -> None:
    # Every existing caller gets min_std_ratio's default (0.0); confirm
    # it's a true no-op by comparing against a call that doesn't pass
    # the parameter at all.
    profile = make_profile({HOLD_A: [49.0, 50.0, 51.0]})
    with_default = scaled_manhattan_score(
        [Feature(HOLD_A, 60.0)], profile, min_feature_count=1, min_compared_features=1
    )
    explicit_zero = scaled_manhattan_score(
        [Feature(HOLD_A, 60.0)],
        profile,
        min_feature_count=1,
        min_compared_features=1,
        min_std_ratio=0.0,
    )
    assert with_default.score == explicit_zero.score


def test_min_std_ratio_floors_std_as_a_fraction_of_the_mean() -> None:
    # Mean 1000, std 1.0 -- min_std_ms (1.0) and plain std (1.0) both
    # floor at 1.0, but 12% of the mean (120.0) is far larger and must
    # win, pulling the score down a lot relative to not using it.
    profile = make_profile({HOLD_A: [999.0, 1000.0, 1001.0]})
    without_ratio = scaled_manhattan_score(
        [Feature(HOLD_A, 1100.0)], profile, min_feature_count=1, min_compared_features=1
    )
    with_ratio = scaled_manhattan_score(
        [Feature(HOLD_A, 1100.0)],
        profile,
        min_feature_count=1,
        min_compared_features=1,
        min_std_ratio=0.12,
    )
    assert without_ratio.score is not None
    assert with_ratio.score is not None
    assert with_ratio.score == pytest.approx(100.0 / 120.0)
    assert with_ratio.score < without_ratio.score


def test_scaled_manhattan_zero_compared_features_returns_insufficient_data() -> None:
    result = scaled_manhattan_score([Feature(HOLD_A, 50.0)], {}, min_compared_features=0)
    assert result.decision == Decision.INSUFFICIENT_DATA
    assert result.compared_features == 0


def test_plain_manhattan_does_not_scale_by_std() -> None:
    # Unlike scaled_manhattan_score, a wide-spread profile must not
    # shrink the distance here: the raw difference is all that matters.
    low_spread = make_profile({HOLD_A: [49.0, 50.0, 51.0]})  # std = 1.0
    high_spread = make_profile({HOLD_A: [0.0, 50.0, 100.0]})  # std = 50.0

    low = plain_manhattan_score(
        [Feature(HOLD_A, 60.0)], low_spread, min_feature_count=1, min_compared_features=1
    )
    high = plain_manhattan_score(
        [Feature(HOLD_A, 60.0)], high_spread, min_feature_count=1, min_compared_features=1
    )

    assert low.score == pytest.approx(10.0)
    assert high.score == pytest.approx(10.0)  # same raw distance, unlike the scaled version


def test_plain_manhattan_zero_compared_features_returns_insufficient_data() -> None:
    result = plain_manhattan_score([Feature(HOLD_A, 50.0)], {}, min_compared_features=0)
    assert result.decision == Decision.INSUFFICIENT_DATA
    assert result.compared_features == 0


def test_three_sigma_score_match_and_no_match() -> None:
    spread_profile = make_profile({HOLD_A: [50.0, 51.0, 49.0, 50.0, 52.0, 48.0]})
    close = three_sigma_score([Feature(HOLD_A, 50.0)], spread_profile, min_compared_features=1)
    assert close.decision == Decision.MATCH

    tight_profile = make_profile({HOLD_A: [50.0] * 10})  # std clamps to the 1ms floor
    far = three_sigma_score([Feature(HOLD_A, 100.0)], tight_profile, min_compared_features=1)
    assert far.decision == Decision.NO_MATCH


def test_three_sigma_score_insufficient_data() -> None:
    profile = make_profile({HOLD_A: [50.0] * 10})
    result = three_sigma_score([Feature(HOLD_A, 50.0)], profile, min_compared_features=5)
    assert result.decision == Decision.INSUFFICIENT_DATA
    assert result.score is None


def test_three_sigma_score_zero_compared_features_returns_insufficient_data() -> None:
    result = three_sigma_score([Feature(HOLD_A, 50.0)], {}, min_compared_features=0)
    assert result.decision == Decision.INSUFFICIENT_DATA
    assert result.compared_features == 0


# --- Regression tests for Phase 0's scoring bugs -----------------------


def test_regression_missing_feature_is_skipped_not_treated_as_zero() -> None:
    """Phase 0 bug: the old code's get_from_sql returned (0, 0) for an
    unseen digraph, and bioauth.py compared against that as if it were
    real data. A feature entirely absent from the profile must never
    contribute to the score."""
    profile = make_profile({HOLD_A: [50.0] * 10})
    sample = [Feature(HOLD_A, 50.0), Feature(("hold", "KeyZ"), 999.0)]  # KeyZ never in profile
    result = scaled_manhattan_score(sample, profile, min_compared_features=1)
    assert result.compared_features == 1
    assert result.score == pytest.approx(0.0)


def test_regression_denominator_is_compared_features_not_profile_size() -> None:
    """Phase 0 bug: bioauth.py divided by storage.count_digraphs(user)
    -- the user's entire stored profile size -- not how many digraphs
    this specific request actually compared."""
    profile = make_profile(
        {
            HOLD_A: [50.0] * 10,
            ("hold", "KeyC"): [10.0] * 10,
            ("hold", "KeyD"): [10.0] * 10,
            ("hold", "KeyE"): [10.0] * 10,
        }
    )  # profile has 4 trained features; the sample only exercises 1
    result = scaled_manhattan_score([Feature(HOLD_A, 50.0)], profile, min_compared_features=1)
    assert result.compared_features == 1


def test_regression_single_sample_feature_is_excluded_not_zero_width() -> None:
    """Phase 0 bug: a digraph seen exactly once got variance 0 in the
    old code, collapsing its match window to a single exact point.
    The default min_feature_count (5) excludes it from comparison
    entirely instead."""
    profile = make_profile({HOLD_A: [50.0]})  # seen exactly once
    result = scaled_manhattan_score([Feature(HOLD_A, 50.001)], profile, min_compared_features=1)
    assert result.decision == Decision.INSUFFICIENT_DATA
    assert result.compared_features == 0


def test_regression_decision_has_no_ambiguous_middle_zone() -> None:
    """Phase 0 bug: the old code's match ratio in [0.5, 0.6) returned
    "Wait" -- neither allowed nor denied. Once there's enough data,
    the decision here is always exactly MATCH or NO_MATCH, with a
    deterministic tie-break right at the threshold -- no dead zone."""
    profile = make_profile({HOLD_A: [50.0] * 10})  # std clamps to the 1ms floor

    at_threshold = scaled_manhattan_score(
        [Feature(HOLD_A, 51.0)], profile, min_compared_features=1, threshold=1.0
    )
    assert at_threshold.score == pytest.approx(1.0)
    assert at_threshold.decision == Decision.MATCH  # score <= threshold, deterministically

    just_over = scaled_manhattan_score(
        [Feature(HOLD_A, 52.0)], profile, min_compared_features=1, threshold=1.0
    )
    assert just_over.decision == Decision.NO_MATCH
