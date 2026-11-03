import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from keystroke_dynamics.core.stats import RunningStats, combine, from_values, update

finite_floats = st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False)


def test_update_known_values() -> None:
    stats = from_values([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
    assert stats.count == 8
    assert stats.mean == pytest.approx(5.0)
    assert stats.variance == pytest.approx(32 / 7)


def test_running_stats_variance_undefined_below_two_samples() -> None:
    assert RunningStats().variance is None
    assert update(RunningStats(), 5.0).variance is None


def test_combine_with_empty_side_returns_the_other_unchanged() -> None:
    stats = from_values([1.0, 2.0, 3.0])
    assert combine(stats, RunningStats()) == stats
    assert combine(RunningStats(), stats) == stats


@given(st.lists(finite_floats, min_size=2, max_size=200))
def test_welford_matches_numpy_mean_and_variance(values: list[float]) -> None:
    stats = from_values(values)
    assert stats.mean == pytest.approx(float(np.mean(values)), abs=1e-6, rel=1e-6)
    assert stats.variance == pytest.approx(float(np.var(values, ddof=1)), abs=1e-6, rel=1e-6)


@given(
    st.lists(finite_floats, min_size=2, max_size=100),
    st.integers(min_value=1, max_value=99),
)
def test_batch_statistics_do_not_depend_on_arrival_order(values: list[float], split: int) -> None:
    split = min(split, len(values) - 1)
    first, second = values[:split], values[split:]

    combined_in_order = from_values(values)
    combined_from_batches = combine(from_values(first), from_values(second))
    combined_reversed_batches = combine(from_values(second), from_values(first))

    for combined in (combined_from_batches, combined_reversed_batches):
        assert combined.count == combined_in_order.count
        assert combined.mean == pytest.approx(combined_in_order.mean, abs=1e-6, rel=1e-6)
        assert combined.variance == pytest.approx(combined_in_order.variance, abs=1e-6, rel=1e-6)


def test_regression_mean_is_a_real_running_mean_not_old_formula() -> None:
    """Phase 0 bug: profile.py's mean used (mean + value) / count."""
    values = [10.0, 12.0, 11.0, 50.0, 9.0]
    stats = from_values(values)
    assert stats.mean == pytest.approx(float(np.mean(values)))

    old_mean = values[0]
    count = 1
    for value in values[1:]:
        count += 1
        old_mean = (old_mean + value) / count
    assert stats.mean != pytest.approx(old_mean)


def test_regression_variance_accumulates_not_overwritten_each_sample() -> None:
    """Phase 0 bug: profile.py's variance was recomputed from scratch
    using only the latest sample, discarding everything before it."""
    values = [10.0, 12.0, 11.0, 50.0, 9.0]
    stats = from_values(values)
    assert stats.variance == pytest.approx(float(np.var(values, ddof=1)))

    old_mean = values[0]
    old_variance = 0.0
    count = 1
    for value in values[1:]:
        count += 1
        old_mean = (old_mean + value) / count
        old_variance = (value - old_mean) ** 2 / (count - 1)
    assert stats.variance != pytest.approx(old_variance)
