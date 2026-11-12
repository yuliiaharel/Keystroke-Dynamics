"""Place features: where on each key a typist's taps land
(docs/plans/active/MOBILE_PLAN.md Phase 1 section 4). Pure -- no web,
no database, no scoring.

Values are in letter-key widths (tap_x) and heights (tap_y) from the
key's center, never milliseconds, which is why they have their own
feature type instead of riding core.features.Feature's value_ms.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from keystroke_dynamics.core.stats import RunningStats
from keystroke_dynamics.game.taps import TapEvent

PlaceKey = tuple[Literal["tap_x", "tap_y"], str]

SPACE_CODE = "Space"


@dataclass(frozen=True)
class PlaceFeature:
    key: PlaceKey
    value: float


def extract_place_features(events: Sequence[TapEvent]) -> list[PlaceFeature]:
    """One ("tap_y", code) per key tapped in the line, and one
    ("tap_x", code) per key except the space bar, whose width makes
    side-to-side position too noisy to be a habit. A key tapped more
    than once in the line contributes the average of its taps, so a
    repeated letter counts once per line, like every other key.

    Reads every down event that has a position. Up events and
    position-less events (which game/taps.py's validation rejects for
    a touch room anyway) are skipped.
    """
    values: dict[PlaceKey, list[float]] = {}
    for event in events:
        if event.action != "down" or event.dx is None or event.dy is None:
            continue
        if event.code != SPACE_CODE:
            values.setdefault(("tap_x", event.code), []).append(event.dx)
        values.setdefault(("tap_y", event.code), []).append(event.dy)
    return [PlaceFeature(key=key, value=sum(v) / len(v)) for key, v in values.items()]


@dataclass(frozen=True)
class TapPoint:
    """One key of a player's tap map: where their taps usually land on
    it, and how much that varies. x is None for the space bar."""

    code: str
    x: float | None
    x_spread: float | None
    y: float
    y_spread: float


def tap_map(place_profile: Mapping[PlaceKey, RunningStats]) -> list[TapPoint]:
    """The average and spread per key that a room shows as a player's
    tap map. Position only -- nothing here is derived from timing."""
    points = []
    for (axis, code), y_stats in place_profile.items():
        if axis != "tap_y":
            continue
        x_stats = place_profile.get(("tap_x", code))
        points.append(
            TapPoint(
                code=code,
                x=x_stats.mean if x_stats is not None else None,
                x_spread=(x_stats.std or 0.0) if x_stats is not None else None,
                y=y_stats.mean,
                y_spread=y_stats.std or 0.0,
            )
        )
    return points
