import pytest

from evaluation.metrics import equal_error_rate


def test_perfectly_separable_scores_give_zero_eer() -> None:
    genuine = [0.0] * 5
    impostor = [10.0] * 5
    result = equal_error_rate(genuine, impostor)
    assert result.eer == pytest.approx(0.0)


def test_identical_distributions_give_half_eer() -> None:
    genuine = [5.0] * 5
    impostor = [5.0] * 5
    result = equal_error_rate(genuine, impostor)
    assert result.eer == pytest.approx(0.5)


def test_overlapping_but_distinguishable_distributions() -> None:
    # Genuine mostly low, impostor mostly high, with some overlap: EER
    # should land strictly between the two extremes above.
    genuine = [1.0, 2.0, 3.0, 8.0, 9.0]
    impostor = [2.0, 3.0, 7.0, 8.0, 9.0]
    result = equal_error_rate(genuine, impostor)
    assert 0.0 < result.eer < 0.5
