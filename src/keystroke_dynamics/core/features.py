"""Extract hold and flight timing features from paired key presses."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

from keystroke_dynamics.core.events import EXCLUDED_CODES, KeyPress

HoldKey = tuple[Literal["hold"], str]
FlightKey = tuple[Literal["flight"], str, str]
FeatureKey = HoldKey | FlightKey

#: Flights longer than this are pauses, not typing rhythm, and are
#: discarded rather than scored.
DEFAULT_MAX_PAUSE_MS = 2000.0


@dataclass(frozen=True)
class Feature:
    key: FeatureKey
    value_ms: float


def extract_features(
    presses: list[KeyPress], *, max_pause_ms: float = DEFAULT_MAX_PAUSE_MS
) -> list[Feature]:
    """presses must be ordered by down_t_ms, as events.pair_presses
    returns them.

    Hold: key A down to key A up, keyed ("hold", "KeyA"). Skipped for
    excluded (editing/modifier) keys.

    Flight: key A down to the chronologically next key B down, keyed
    ("flight", "KeyA", "KeyB"). Skipped if either key is excluded --
    since excluded presses are never removed from `presses`, this
    naturally stops a flight from spanning across one: if A, Shift,
    B are consecutive, the pairs considered are (A, Shift) and
    (Shift, B), never (A, B). Also skipped if the gap exceeds
    max_pause_ms (a pause, not typing rhythm).
    """
    features: list[Feature] = []

    for press in presses:
        if press.code not in EXCLUDED_CODES:
            features.append(
                Feature(key=("hold", press.code), value_ms=press.up_t_ms - press.down_t_ms)
            )

    for a, b in pairwise(presses):
        if a.code in EXCLUDED_CODES or b.code in EXCLUDED_CODES:
            continue
        flight_ms = b.down_t_ms - a.down_t_ms
        if flight_ms > max_pause_ms:
            continue
        features.append(Feature(key=("flight", a.code, b.code), value_ms=flight_ms))

    return features
