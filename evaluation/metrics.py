"""Equal error rate (EER): the point on a genuine/impostor score
distribution where the false accept rate (FAR) equals the false
reject rate (FRR).

This is a benchmark-only concern -- it has no place in core/, which
never needs to know how its scores perform in aggregate, only how to
produce one.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class EERResult:
    eer: float
    #: The anomaly-score threshold at the FAR/FRR crossover (accept
    #: when score <= threshold). Not the app's configured threshold --
    #: this is specific to what's being measured here.
    threshold: float


def equal_error_rate(genuine_scores: list[float], impostor_scores: list[float]) -> EERResult:
    """genuine_scores and impostor_scores must be "anomaly" scores
    (lower means more likely genuine) from the same scoring method and
    profile -- callers using a method where higher is more similar
    (e.g. three_sigma_score's match ratio) must invert first.

    Sweeps every candidate threshold spanning both score lists and
    linearly interpolates the point where FAR (rising as the threshold
    relaxes) crosses FRR (falling as it relaxes).
    """
    genuine = np.asarray(genuine_scores, dtype=float)
    impostor = np.asarray(impostor_scores, dtype=float)

    candidates = np.unique(np.concatenate([genuine, impostor]))
    thresholds = np.concatenate([[candidates[0] - 1.0], candidates, [candidates[-1] + 1.0]])

    far = np.array([(impostor <= t).mean() for t in thresholds])  # rises with t
    frr = np.array([(genuine > t).mean() for t in thresholds])  # falls with t
    diff = far - frr

    sign_changes = np.where(np.diff(np.sign(diff)) != 0)[0]
    if len(sign_changes) == 0:
        # No crossing (fully separable, or far/frr identical throughout):
        # report the closest point instead of failing.
        i = int(np.argmin(np.abs(diff)))
        return EERResult(eer=float((far[i] + frr[i]) / 2), threshold=float(thresholds[i]))

    i = int(sign_changes[0])
    x0, x1 = thresholds[i], thresholds[i + 1]
    d0, d1 = diff[i], diff[i + 1]
    frac = 0.0 if d1 == d0 else -d0 / (d1 - d0)

    far_at_cross = far[i] + frac * (far[i + 1] - far[i])
    frr_at_cross = frr[i] + frac * (frr[i + 1] - frr[i])
    threshold_at_cross = x0 + frac * (x1 - x0)

    eer = float((far_at_cross + frr_at_cross) / 2)
    return EERResult(eer=eer, threshold=float(threshold_at_cross))
