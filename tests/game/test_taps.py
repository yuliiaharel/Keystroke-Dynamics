"""game/taps.py: what a touch room accepts as a line, and what a
keyboard room refuses."""

from __future__ import annotations

import pytest

from keystroke_dynamics.core.events import InvalidSampleError, KeyEvent
from keystroke_dynamics.game.taps import (
    MAX_TAP_DX,
    MAX_TAP_DY,
    TapEvent,
    to_key_events,
    validate_keyboard_events,
    validate_taps,
)


def _tap(code: str = "KeyA", t: float = 0.0, dx: float | None = 0.1, dy: float | None = -0.1):
    return [
        TapEvent(code=code, action="down", t_ms=t, dx=dx, dy=dy),
        TapEvent(code=code, action="up", t_ms=t + 80),
    ]


def test_a_clean_tap_line_is_accepted() -> None:
    validate_taps(_tap("KeyT") + _tap("Space", 200, dx=3.0), max_events=100)


def test_to_key_events_keeps_timing_and_drops_position() -> None:
    assert to_key_events(_tap("KeyA", 5.0)) == [
        KeyEvent(code="KeyA", action="down", t_ms=5.0),
        KeyEvent(code="KeyA", action="up", t_ms=85.0),
    ]


@pytest.mark.parametrize(
    ("events", "message"),
    [
        pytest.param(_tap(dx=None), "missing its tap position", id="down-without-dx"),
        pytest.param(_tap(dy=None), "missing its tap position", id="down-without-dy"),
        pytest.param(
            [
                TapEvent(code="KeyA", action="down", t_ms=0, dx=0, dy=0),
                TapEvent(code="KeyA", action="up", t_ms=80, dx=0.1),
            ],
            "up event can't carry",
            id="dx-on-up",
        ),
        pytest.param(
            [
                TapEvent(code="KeyA", action="down", t_ms=0, dx=0, dy=0),
                TapEvent(code="KeyA", action="up", t_ms=80, dy=0.0),
            ],
            "up event can't carry",
            id="dy-on-up",
        ),
        pytest.param(_tap(dx=float("nan")), "non-finite tap position", id="nan-dx"),
        pytest.param(_tap(dy=float("inf")), "non-finite tap position", id="inf-dy"),
        pytest.param(_tap(dx=-float("inf")), "non-finite tap position", id="neg-inf-dx"),
        pytest.param(_tap(dx=MAX_TAP_DX + 0.01), "too far from its key", id="dx-too-far"),
        pytest.param(_tap(dx=-MAX_TAP_DX - 0.01), "too far from its key", id="dx-too-far-left"),
        pytest.param(_tap(dy=MAX_TAP_DY + 0.01), "too far from its key", id="dy-too-far"),
        pytest.param(_tap(dy=-MAX_TAP_DY - 0.01), "too far from its key", id="dy-too-far-up"),
        pytest.param(_tap("Backspace"), "isn't on the on-page keyboard", id="key-not-on-keyboard"),
        pytest.param(_tap("Digit1"), "isn't on the on-page keyboard", id="digit"),
        pytest.param(_tap(t=float("nan")), "non-finite t_ms", id="nan-time"),
        pytest.param(_tap("KeyA", 100) + _tap("KeyB", 50), "go backward", id="time-goes-backward"),
    ],
)
def test_each_invalid_tap_line_is_refused(events: list[TapEvent], message: str) -> None:
    with pytest.raises(InvalidSampleError, match=message):
        validate_taps(events, max_events=100)


def test_offsets_exactly_at_the_limit_are_accepted() -> None:
    validate_taps(_tap("Space", dx=MAX_TAP_DX, dy=-MAX_TAP_DY), max_events=100)


def test_an_oversized_sample_is_refused() -> None:
    events = [e for i in range(6) for e in _tap("KeyA", i * 100.0)]
    with pytest.raises(InvalidSampleError, match="exceeds limit"):
        validate_taps(events, max_events=10)


def test_position_errors_never_quote_the_submitted_value() -> None:
    # The message goes into a 400 response, so it must not echo input.
    with pytest.raises(InvalidSampleError) as excinfo:
        validate_taps(_tap(dx=3.987654, dy=5.123456), max_events=100)
    assert "3.98" not in str(excinfo.value)
    assert "5.12" not in str(excinfo.value)


def test_a_keyboard_line_with_no_positions_is_accepted() -> None:
    validate_keyboard_events(_tap(dx=None, dy=None), max_events=100)


@pytest.mark.parametrize(
    "events",
    [
        pytest.param(_tap(dx=0.1, dy=None), id="dx-only"),
        pytest.param(_tap(dx=None, dy=0.1), id="dy-only"),
        pytest.param(_tap(dx=0.0, dy=0.0), id="zeros-are-still-positions"),
    ],
)
def test_a_keyboard_line_with_any_position_is_refused(events: list[TapEvent]) -> None:
    with pytest.raises(InvalidSampleError, match="only accepted in touch rooms"):
        validate_keyboard_events(events, max_events=100)


def test_a_keyboard_line_still_gets_the_core_checks() -> None:
    events = [e for i in range(6) for e in _tap("KeyA", i * 100.0, dx=None, dy=None)]
    with pytest.raises(InvalidSampleError, match="exceeds limit"):
        validate_keyboard_events(events, max_events=10)
    # A physical keyboard has keys the on-page one doesn't.
    validate_keyboard_events(_tap("Comma", dx=None, dy=None), max_events=100)
