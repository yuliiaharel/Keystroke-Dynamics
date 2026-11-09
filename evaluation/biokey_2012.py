"""BioKey 2012 keystroke-timing authentication method, reconstructed
from the thesis "Біометричний контроль доступу на базі динамічного
клавіатурного паролю" (2012) for comparison against this app's actual
scoring method (core/scoring.py) in the Phase 3 benchmark.

Evaluation only. Never imported by the app -- keep it that way.

The formulas below are transcribed as written in the thesis, with two
corrections noted inline (half-open Haar intervals, r stopping at
n-1) that docs/plans/done/MODERNIZATION_PLAN.md calls out as matching the thesis's own
flowchart despite a slip in its text. Everything under "Reconstruction"
is this module's own choice, since the thesis doesn't specify it and
the original code no longer exists -- treat those numbers as an
approximation of the method, not a reproduction of the thesis's exact
pipeline.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache

import numpy as np
from scipy import stats as scipy_stats

from keystroke_dynamics.core.stats import from_values

DEFAULT_P = 0.1
#: The thesis's own reported decision threshold (Hamming score, lower
#: is more genuine-like) -- taken from the thesis, never tuned here.
THESIS_THRESHOLD = 0.30


# --------------------------------------------------------------------
# Formula (1): the Haar matrix, and formula (4): the Haar transform.
# --------------------------------------------------------------------


@cache
def haar_matrix(n: int) -> np.ndarray:
    """H(n), an N x N matrix with N = 2**n, per formula (1):

        har(0, 0, t) = 1
        har(r, m, t) =  2**(r/2)  if (m-1)/2**r   <= t < (m-1/2)/2**r
                       -2**(r/2)  if (m-1/2)/2**r <= t < m/2**r
                        0         otherwise
        with 0 <= r <= n-1, 1 <= m <= 2**r

    t ranges over N evenly spaced samples in [0, 1) (t_idx / N).

    Two corrections to the thesis's text, per docs/plans/done/MODERNIZATION_PLAN.md
    (matching the thesis's own flowchart): the intervals above are
    half-open as shown (not closed), and r stops at n-1, not n.
    """
    N = 2**n
    H = np.zeros((N, N))
    H[0, :] = 1.0

    row = 1
    for r in range(n):  # 0 <= r <= n-1
        scale = 2 ** (r / 2)
        levels = 2**r
        for m in range(1, levels + 1):
            lo = (m - 1) / levels
            mid = (m - 0.5) / levels
            hi = m / levels
            for t_idx in range(N):
                t = t_idx / N
                if lo <= t < mid:
                    H[row, t_idx] = scale
                elif mid <= t < hi:
                    H[row, t_idx] = -scale
            row += 1

    assert row == N, f"expected to fill {N} rows, filled {row}"
    return H


def haar_transform(signal: np.ndarray) -> np.ndarray:
    """Formula (4): V = (1/N) * H(n) * F."""
    n = int(round(math.log2(len(signal))))
    if 2**n != len(signal):
        raise ValueError(f"signal length {len(signal)} is not a power of 2")
    H = haar_matrix(n)
    return (H @ signal) / len(signal)


# --------------------------------------------------------------------
# Reconstruction: raw dataset row -> a fixed-length timing signal.
# Not specified by the thesis -- see the module docstring.
# --------------------------------------------------------------------


def build_timing_signal(row: dict[str, str], keys: Sequence[str]) -> list[float]:
    """The alternating H, UD, H, UD, ..., H sequence (milliseconds)
    for `keys`, from one CSV row of the CMU dataset.

    `keys` should already exclude "Return": its hold and the UD
    leading into it reflect ending the trial (releasing a key to stop
    typing), not an ongoing typing rhythm -- core/events.py already
    excludes Enter/Return from this app's own hold/flight features
    for the same reason, and that choice is reused here.
    """
    signal: list[float] = [float(row[f"H.{keys[0]}"]) * 1000.0]
    for a, b in zip(keys, keys[1:], strict=False):
        signal.append(float(row[f"UD.{a}.{b}"]) * 1000.0)
        signal.append(float(row[f"H.{b}"]) * 1000.0)
    return signal


def resample(signal: Sequence[float], n: int) -> np.ndarray:
    """Linearly interpolates `signal` (any length >= 2) to exactly `n`
    evenly spaced samples over the same span."""
    signal_arr = np.asarray(signal, dtype=float)
    original_x = np.linspace(0.0, 1.0, num=len(signal_arr))
    target_x = np.linspace(0.0, 1.0, num=n)
    return np.interp(target_x, original_x, signal_arr)


def normalize_by_sum(signal: np.ndarray) -> np.ndarray:
    """Step 3 of the reconstruction: divide by the resampled signal's
    own sum, so it has a common scale independent of typing speed."""
    total = signal.sum()
    return signal / total


def build_feature_vector(row: dict[str, str], keys: Sequence[str], n: int) -> np.ndarray:
    """Raw dataset row -> the length-n normalized signal (steps 1-3 of
    the reconstruction), ready for haar_transform (Haar variants) or
    direct use (raw_corrected)."""
    raw = build_timing_signal(row, keys)
    return normalize_by_sum(resample(raw, n))


# --------------------------------------------------------------------
# Formulas (7) and (8): the thesis's own running mean and variance.
#
# Formula (7) is algebraically the standard online mean -- it matches
# numpy.mean exactly (see tests/test_biokey_2012.py). Formula (8) is
# NOT the standard online variance (Welford's): it's a different,
# simpler recursion that the thesis states as written, and it is
# measurably biased -- e.g. for [1, 3], formula (8) gives 1.0 where
# the exact sample variance (ddof=1) is 2.0. biokey_as_written uses
# this formula deliberately, to measure the thesis's method as
# written; biokey_corrected and raw_corrected use exact (Welford)
# variance instead, via core.stats.from_values.
# --------------------------------------------------------------------


def thesis_running_mean(values: Sequence[float]) -> float:
    mean = 0.0
    for j, v in enumerate(values, start=1):
        mean = ((j - 1) / j) * mean + (1 / j) * v
    return mean


def thesis_running_variance(values: Sequence[float]) -> float:
    mean = 0.0
    variance = 0.0
    for j, v in enumerate(values, start=1):
        mean = ((j - 1) / j) * mean + (1 / j) * v
        if j >= 2:
            variance = ((j - 2) / (j - 1)) * variance + (1 / (j - 1)) * (v - mean) ** 2
    return variance


# --------------------------------------------------------------------
# Formula (6): the per-feature acceptance range, and its two range
# multipliers.
# --------------------------------------------------------------------


def one_sided_multiplier(L: int, P: float) -> float:
    """t[L, 1-P] as written in the thesis: a one-sided Student's t
    critical value with L-1 degrees of freedom."""
    return float(scipy_stats.t.ppf(1 - P, df=L - 1))


def two_sided_corrected_multiplier(L: int, P: float) -> float:
    """biokey_corrected / raw_corrected's multiplier: a two-sided
    critical value plus the sqrt(1 + 1/L) prediction-interval
    correction for finite-sample mean/variance uncertainty."""
    return float(scipy_stats.t.ppf(1 - P / 2, df=L - 1)) * math.sqrt(1 + 1 / L)


@dataclass(frozen=True)
class FeatureRange:
    low: float
    high: float

    def contains(self, value: float) -> bool:
        return self.low <= value <= self.high


# --------------------------------------------------------------------
# Decision score: normalized Hamming distance.
# --------------------------------------------------------------------


def hamming_score(values: Sequence[float], ranges: Sequence[FeatureRange]) -> float:
    """e_i = 0 if values[i] is inside ranges[i], else 1. Returns
    sum(e_i) / N -- the share of features that fell outside their
    trained range. Lower means more genuine-like."""
    if len(values) != len(ranges):
        raise ValueError(f"{len(values)} values but {len(ranges)} ranges")
    misses = sum(0 if r.contains(v) else 1 for v, r in zip(values, ranges, strict=True))
    return misses / len(values)


# --------------------------------------------------------------------
# The three variants.
# --------------------------------------------------------------------


@dataclass(frozen=True)
class BioKeyProfile:
    ranges: list[FeatureRange]


def _ranges_as_written(training_vectors: list[np.ndarray], P: float) -> list[FeatureRange]:
    L = len(training_vectors)
    multiplier = one_sided_multiplier(L, P)
    n_features = len(training_vectors[0])
    ranges = []
    for i in range(n_features):
        values = [v[i] for v in training_vectors]
        mean = thesis_running_mean(values)
        sigma = math.sqrt(thesis_running_variance(values))
        ranges.append(FeatureRange(mean - multiplier * sigma, mean + multiplier * sigma))
    return ranges


def _ranges_corrected(training_vectors: list[np.ndarray], P: float) -> list[FeatureRange]:
    L = len(training_vectors)
    multiplier = two_sided_corrected_multiplier(L, P)
    n_features = len(training_vectors[0])
    ranges = []
    for i in range(n_features):
        values = [v[i] for v in training_vectors]
        stats = from_values(values)
        sigma = stats.std or 0.0
        ranges.append(
            FeatureRange(stats.mean - multiplier * sigma, stats.mean + multiplier * sigma)
        )
    return ranges


def enroll_biokey_as_written(
    training_rows: Sequence[dict[str, str]], keys: Sequence[str], n: int, P: float = DEFAULT_P
) -> BioKeyProfile:
    """Haar features; formula (8) variance; one-sided multiplier --
    the thesis's method as written."""
    vectors = [haar_transform(build_feature_vector(row, keys, n)) for row in training_rows]
    return BioKeyProfile(_ranges_as_written(vectors, P))


def enroll_biokey_corrected(
    training_rows: Sequence[dict[str, str]], keys: Sequence[str], n: int, P: float = DEFAULT_P
) -> BioKeyProfile:
    """Haar features; exact (Welford) variance; two-sided corrected
    multiplier."""
    vectors = [haar_transform(build_feature_vector(row, keys, n)) for row in training_rows]
    return BioKeyProfile(_ranges_corrected(vectors, P))


def enroll_raw_corrected(
    training_rows: Sequence[dict[str, str]], keys: Sequence[str], n: int, P: float = DEFAULT_P
) -> BioKeyProfile:
    """Raw (non-Haar) resampled, normalized timing signal; exact
    (Welford) variance; two-sided corrected multiplier."""
    vectors = [build_feature_vector(row, keys, n) for row in training_rows]
    return BioKeyProfile(_ranges_corrected(vectors, P))


def score_as_written(
    row: dict[str, str], keys: Sequence[str], n: int, profile: BioKeyProfile
) -> float:
    vector = haar_transform(build_feature_vector(row, keys, n))
    return hamming_score(vector, profile.ranges)


def score_corrected(
    row: dict[str, str], keys: Sequence[str], n: int, profile: BioKeyProfile
) -> float:
    vector = haar_transform(build_feature_vector(row, keys, n))
    return hamming_score(vector, profile.ranges)


def score_raw_corrected(
    row: dict[str, str], keys: Sequence[str], n: int, profile: BioKeyProfile
) -> float:
    vector = build_feature_vector(row, keys, n)
    return hamming_score(vector, profile.ranges)
