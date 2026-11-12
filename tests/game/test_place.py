"""game/place.py: position features and the tap map."""

from __future__ import annotations

import pytest

from keystroke_dynamics.core.stats import from_values
from keystroke_dynamics.game.place import PlaceFeature, extract_place_features, tap_map
from keystroke_dynamics.game.taps import TapEvent
from tests.touch_lines import TOUCH_PHRASE, tap_line, to_taps


def _down(code: str, dx: float, dy: float, t: float = 0.0) -> TapEvent:
    return TapEvent(code=code, action="down", t_ms=t, dx=dx, dy=dy)


def _up(code: str, t: float = 50.0) -> TapEvent:
    return TapEvent(code=code, action="up", t_ms=t)


def test_each_key_gets_a_tap_x_and_a_tap_y() -> None:
    features = extract_place_features([_down("KeyA", 0.2, -0.1), _up("KeyA")])
    assert features == [
        PlaceFeature(key=("tap_x", "KeyA"), value=0.2),
        PlaceFeature(key=("tap_y", "KeyA"), value=-0.1),
    ]


def test_the_space_bar_gets_a_tap_y_and_no_tap_x() -> None:
    features = extract_place_features([_down("Space", 2.5, 0.3), _up("Space")])
    assert features == [PlaceFeature(key=("tap_y", "Space"), value=0.3)]


def test_a_key_tapped_more_than_once_is_averaged_within_the_line() -> None:
    events = [
        _down("KeyT", 0.1, 0.4, 0),
        _up("KeyT", 50),
        _down("KeyH", -0.2, 0.0, 100),
        _up("KeyH", 150),
        _down("KeyT", 0.3, -0.2, 200),
        _up("KeyT", 250),
    ]
    by_key = {f.key: f.value for f in extract_place_features(events)}
    assert by_key[("tap_x", "KeyT")] == pytest.approx(0.2)
    assert by_key[("tap_y", "KeyT")] == pytest.approx(0.1)
    assert by_key[("tap_x", "KeyH")] == -0.2
    assert len(by_key) == 4


def test_up_events_and_positionless_events_contribute_nothing() -> None:
    events = [
        TapEvent(code="KeyA", action="down", t_ms=0),
        TapEvent(code="KeyA", action="up", t_ms=50),
    ]
    assert extract_place_features(events) == []


def test_the_touch_line_produces_one_feature_per_key_and_axis() -> None:
    features = extract_place_features(to_taps(tap_line()))
    keys = [f.key for f in features]
    assert len(keys) == len(set(keys))
    letters = set(TOUCH_PHRASE) - {" "}
    assert sum(1 for axis, _ in keys if axis == "tap_x") == len(letters)
    assert sum(1 for axis, _ in keys if axis == "tap_y") == len(letters) + 1
    assert ("tap_x", "Space") not in keys


def test_tap_map_gives_each_keys_average_and_spread() -> None:
    profile = {
        ("tap_x", "KeyA"): from_values([0.1, 0.3]),
        ("tap_y", "KeyA"): from_values([-0.2, -0.2]),
        ("tap_y", "Space"): from_values([0.0, 0.4]),
    }
    points = {p.code: p for p in tap_map(profile)}
    assert set(points) == {"KeyA", "Space"}
    assert points["KeyA"].x == pytest.approx(0.2)
    assert points["KeyA"].x_spread == pytest.approx(0.1414, abs=1e-4)
    assert points["KeyA"].y == pytest.approx(-0.2)
    assert points["KeyA"].y_spread == 0.0
    # The space bar has no sideways position at all.
    assert points["Space"].x is None
    assert points["Space"].x_spread is None
    assert points["Space"].y == pytest.approx(0.2)


def test_tap_map_of_a_keyboard_player_is_empty() -> None:
    assert tap_map({}) == []
