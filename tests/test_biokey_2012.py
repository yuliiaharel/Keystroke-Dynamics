"""Required tests for evaluation/biokey_2012.py, per
MODERNIZATION_PLAN.md's BioKey 2012 section."""

import numpy as np
import pytest

from evaluation.biokey_2012 import (
    FeatureRange,
    haar_matrix,
    haar_transform,
    hamming_score,
    one_sided_multiplier,
    thesis_running_mean,
    thesis_running_variance,
)

SQRT2 = 2**0.5

#: The thesis's own H(3) matrix, transcribed from MODERNIZATION_PLAN.md.
THESIS_H3 = np.array(
    [
        [1, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, -1, -1, -1, -1],
        [SQRT2, SQRT2, -SQRT2, -SQRT2, 0, 0, 0, 0],
        [0, 0, 0, 0, SQRT2, SQRT2, -SQRT2, -SQRT2],
        [2, -2, 0, 0, 0, 0, 0, 0],
        [0, 0, 2, -2, 0, 0, 0, 0],
        [0, 0, 0, 0, 2, -2, 0, 0],
        [0, 0, 0, 0, 0, 0, 2, -2],
    ]
)


def test_h3_matches_the_thesis_matrix() -> None:
    assert np.allclose(haar_matrix(3), THESIS_H3)


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5])
def test_haar_matrix_is_orthogonal_and_invertible(n: int) -> None:
    N = 2**n
    H = haar_matrix(n)

    # H(n) * H(n)^T == N * I
    assert np.allclose(H @ H.T, N * np.eye(N))

    # Applying H(n)^T to V (= H(n) F / N, formula 4) recovers F.
    rng = np.random.default_rng(0)
    F = rng.uniform(1.0, 100.0, size=N)
    V = haar_transform(F)
    recovered = H.T @ V
    assert np.allclose(recovered, F)


def test_formula_7_matches_numpy_mean() -> None:
    values = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0]
    assert thesis_running_mean(values) == pytest.approx(float(np.mean(values)))


def test_exact_variance_matches_numpy_var_ddof1() -> None:
    from keystroke_dynamics.core.stats import from_values

    values = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0]
    exact = from_values(values).variance
    assert exact == pytest.approx(float(np.var(values, ddof=1)))


def test_formula_8_reproduces_the_hand_calculated_value() -> None:
    # [1, 3]: formula (8) gives 1, while the exact sample variance is
    # 2 -- a deliberate quirk of the thesis's own recursion, not a bug
    # in this reconstruction. See biokey_2012.py's module docstring.
    assert thesis_running_variance([1.0, 3.0]) == pytest.approx(1.0)
    assert np.var([1.0, 3.0], ddof=1) == pytest.approx(2.0)


@pytest.mark.parametrize(
    ("L", "P", "expected"),
    [
        (10, 0.1, 1.38),
        (5, 0.05, 2.13),
    ],
)
def test_one_sided_multiplier_matches_the_thesis_table(L: int, P: float, expected: float) -> None:
    assert one_sided_multiplier(L, P) == pytest.approx(expected, abs=0.005)


def test_hamming_score_all_in_range() -> None:
    ranges = [FeatureRange(0, 10), FeatureRange(0, 10), FeatureRange(0, 10)]
    assert hamming_score([1, 5, 9], ranges) == pytest.approx(0.0)


def test_hamming_score_all_out_of_range() -> None:
    ranges = [FeatureRange(0, 10), FeatureRange(0, 10), FeatureRange(0, 10)]
    assert hamming_score([-1, 11, 100], ranges) == pytest.approx(1.0)


def test_hamming_score_mixed() -> None:
    ranges = [FeatureRange(0, 10), FeatureRange(0, 10), FeatureRange(0, 10), FeatureRange(0, 10)]
    assert hamming_score([5, -1, 5, 11], ranges) == pytest.approx(0.5)


def test_hamming_score_exactly_on_boundary_counts_as_in_range() -> None:
    ranges = [FeatureRange(0, 10), FeatureRange(0, 10)]
    assert hamming_score([0, 10], ranges) == pytest.approx(0.0)
