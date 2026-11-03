import pytest

from keystroke_dynamics.core.events import (
    InvalidSampleError,
    KeyEvent,
    KeyPress,
    pair_presses,
    validate,
)


def test_validate_accepts_a_well_formed_sample() -> None:
    events = [
        KeyEvent(code="KeyA", action="down", t_ms=0),
        KeyEvent(code="KeyA", action="up", t_ms=10),
    ]
    validate(events)  # does not raise


def test_validate_rejects_too_many_events() -> None:
    events = [KeyEvent(code="KeyA", action="down", t_ms=float(i)) for i in range(5)]
    with pytest.raises(InvalidSampleError):
        validate(events, max_events=4)


def test_validate_rejects_unknown_action() -> None:
    events = [KeyEvent(code="KeyA", action="press", t_ms=0)]  # type: ignore[arg-type]
    with pytest.raises(InvalidSampleError):
        validate(events)


def test_validate_rejects_backward_time() -> None:
    events = [
        KeyEvent(code="KeyA", action="down", t_ms=10),
        KeyEvent(code="KeyA", action="up", t_ms=5),
    ]
    with pytest.raises(InvalidSampleError):
        validate(events)


def test_pair_presses_simple_pair() -> None:
    events = [
        KeyEvent(code="KeyA", action="down", t_ms=0),
        KeyEvent(code="KeyA", action="up", t_ms=50),
    ]
    assert pair_presses(events) == [KeyPress(code="KeyA", down_t_ms=0, up_t_ms=50)]


def test_pair_presses_handles_overlapping_presses() -> None:
    # A down, B down, A up, B up: A and B overlap; each key's own
    # down/up must pair correctly despite the interleaving.
    events = [
        KeyEvent(code="KeyA", action="down", t_ms=0),
        KeyEvent(code="KeyB", action="down", t_ms=10),
        KeyEvent(code="KeyA", action="up", t_ms=20),
        KeyEvent(code="KeyB", action="up", t_ms=30),
    ]
    assert pair_presses(events) == [
        KeyPress(code="KeyA", down_t_ms=0, up_t_ms=20),
        KeyPress(code="KeyB", down_t_ms=10, up_t_ms=30),
    ]


def test_pair_presses_orders_by_down_time_not_completion_time() -> None:
    # A is pressed first but released second (B's up comes before A's
    # up). The result must still be ordered by down_t_ms, since
    # flight-time features need "key A down to next key B down".
    events = [
        KeyEvent(code="KeyA", action="down", t_ms=0),
        KeyEvent(code="KeyB", action="down", t_ms=10),
        KeyEvent(code="KeyB", action="up", t_ms=20),
        KeyEvent(code="KeyA", action="up", t_ms=30),
    ]
    presses = pair_presses(events)
    assert [p.code for p in presses] == ["KeyA", "KeyB"]


def test_pair_presses_ignores_repeated_keydown_while_held() -> None:
    # A browser key-repeat: keydown fires again before the key is
    # released. The repeat must not reset the press's start time.
    events = [
        KeyEvent(code="KeyA", action="down", t_ms=0),
        KeyEvent(code="KeyA", action="down", t_ms=5),  # repeat, ignored
        KeyEvent(code="KeyA", action="down", t_ms=10),  # repeat, ignored
        KeyEvent(code="KeyA", action="up", t_ms=50),
    ]
    assert pair_presses(events) == [KeyPress(code="KeyA", down_t_ms=0, up_t_ms=50)]


def test_pair_presses_drops_unmatched_keyup() -> None:
    # A keyup with no corresponding open keydown (e.g. the keydown
    # happened before the sample started recording).
    events = [
        KeyEvent(code="KeyA", action="up", t_ms=10),
        KeyEvent(code="KeyB", action="down", t_ms=20),
        KeyEvent(code="KeyB", action="up", t_ms=30),
    ]
    assert pair_presses(events) == [KeyPress(code="KeyB", down_t_ms=20, up_t_ms=30)]


def test_pair_presses_drops_unmatched_keydown() -> None:
    # A keydown with no following keyup before the sample ends.
    events = [
        KeyEvent(code="KeyA", action="down", t_ms=0),
        KeyEvent(code="KeyB", action="down", t_ms=10),
        KeyEvent(code="KeyB", action="up", t_ms=20),
    ]
    assert pair_presses(events) == [KeyPress(code="KeyB", down_t_ms=10, up_t_ms=20)]


def test_pair_presses_keeps_excluded_keys_in_the_sequence() -> None:
    # pair_presses itself does not know about exclusion -- it pairs
    # every code, including editing/modifier keys. Whether to use them
    # as features is features.py's job (see test_features.py).
    events = [
        KeyEvent(code="ShiftLeft", action="down", t_ms=0),
        KeyEvent(code="ShiftLeft", action="up", t_ms=10),
    ]
    assert pair_presses(events) == [KeyPress(code="ShiftLeft", down_t_ms=0, up_t_ms=10)]
