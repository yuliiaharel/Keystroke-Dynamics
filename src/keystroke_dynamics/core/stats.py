"""Welford's online algorithm for mean and variance.

Fixes the old app's statistics bugs (see docs/plans/done/MODERNIZATION_PLAN.md Phase 0):
the running mean here is a real running mean, not `(mean + value) /
count`, and variance accumulates across every sample instead of being
overwritten by the latest one.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RunningStats:
    count: int = 0
    mean: float = 0.0
    m2: float = 0.0

    @property
    def variance(self) -> float | None:
        """Sample variance (ddof=1). None when count < 2 -- undefined,
        not zero (the old app's bug: a digraph seen once got variance
        0, collapsing its match window to a single exact point)."""
        if self.count < 2:
            return None
        return self.m2 / (self.count - 1)

    @property
    def std(self) -> float | None:
        variance = self.variance
        return None if variance is None else variance**0.5


def update(stats: RunningStats, value: float) -> RunningStats:
    """Returns new stats incorporating value. Does not mutate stats."""
    count = stats.count + 1
    delta = value - stats.mean
    mean = stats.mean + delta / count
    delta2 = value - mean
    m2 = stats.m2 + delta * delta2
    return RunningStats(count=count, mean=mean, m2=m2)


def from_values(values: list[float]) -> RunningStats:
    """Folds update() over values, starting from empty stats."""
    stats = RunningStats()
    for value in values:
        stats = update(stats, value)
    return stats


def combine(a: RunningStats, b: RunningStats) -> RunningStats:
    """Merges two independently accumulated RunningStats -- e.g. from
    different enrollment batches, accumulated in any order -- into
    one, via the parallel/batch variant of Welford's algorithm.

    combine(a, b) == combine(b, a), and combining is associative, so
    the result never depends on how the input values were split into
    batches or in what order those batches arrived.
    """
    if a.count == 0:
        return b
    if b.count == 0:
        return a
    count = a.count + b.count
    delta = b.mean - a.mean
    mean = a.mean + delta * b.count / count
    m2 = a.m2 + b.m2 + delta * delta * a.count * b.count / count
    return RunningStats(count=count, mean=mean, m2=m2)
