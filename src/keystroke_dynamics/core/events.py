"""Validate raw keystroke events and pair keydown/keyup into completed
key presses.

See MODERNIZATION_PLAN.md Phase 2 for the input event format and the
rules this module implements.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Action = Literal["down", "up"]

#: Editing/navigation and modifier keys don't reflect typing rhythm.
#: A flight time must never span across one of these -- see
#: extract_features in features.py, which relies on these presses
#: staying in the sequence (not being dropped here) so that two
#: ordinary keys on either side of one are never treated as adjacent.
EXCLUDED_CODES = frozenset(
    {
        "Backspace",
        "Delete",
        "ArrowLeft",
        "ArrowRight",
        "ArrowUp",
        "ArrowDown",
        "ShiftLeft",
        "ShiftRight",
        "ControlLeft",
        "ControlRight",
        "AltLeft",
        "AltRight",
        "MetaLeft",
        "MetaRight",
        "Tab",
        "CapsLock",
        "Escape",
        "Enter",
    }
)


@dataclass(frozen=True)
class KeyEvent:
    code: str  # KeyboardEvent.code, e.g. "KeyA"
    action: Action
    t_ms: float  # Milliseconds, relative to the start of the sample


@dataclass(frozen=True)
class KeyPress:
    """One completed keydown-to-keyup pair for a single key."""

    code: str
    down_t_ms: float
    up_t_ms: float


class InvalidSampleError(ValueError):
    """Raised when a raw event sample fails validation."""


def validate(events: list[KeyEvent], *, max_events: int = 2000) -> None:
    """Raises InvalidSampleError if events exceeds max_events, contains
    an action other than "down"/"up", or has a t_ms that goes backward
    relative to the previous event in the list."""
    if len(events) > max_events:
        raise InvalidSampleError(f"sample has {len(events)} events, exceeds limit of {max_events}")

    last_t = float("-inf")
    for event in events:
        if event.action not in ("down", "up"):
            raise InvalidSampleError(f"unknown action: {event.action!r}")
        if event.t_ms < last_t:
            raise InvalidSampleError("event times go backward")
        last_t = event.t_ms


def pair_presses(events: list[KeyEvent]) -> list[KeyPress]:
    """Pairs each keydown with its next keyup for the same code.

    Handles overlapping presses (e.g. A down, B down, A up, B up) by
    tracking one open press per code, so two different keys held down
    at once don't get confused with each other. Drops unmatched events
    (a keyup with no open keydown for that code, or a keydown never
    followed by a keyup before the sample ends) and ignores a repeated
    keydown for a key that's already held (only the first keydown of
    an open press counts; a browser's key-repeat keydowns are the
    usual source of these).

    Returns presses ordered by down_t_ms -- the order a flight-time
    feature needs ("key A down to next key B down"), which is not
    necessarily the order presses complete (closed by their keyup),
    since presses can overlap.
    """
    open_downs: dict[str, float] = {}
    presses: list[KeyPress] = []

    for event in events:
        if event.action == "down":
            if event.code in open_downs:
                continue  # repeated keydown while already held
            open_downs[event.code] = event.t_ms
        else:  # "up"
            down_t = open_downs.pop(event.code, None)
            if down_t is None:
                continue  # unmatched keyup
            presses.append(KeyPress(code=event.code, down_t_ms=down_t, up_t_ms=event.t_ms))

    presses.sort(key=lambda p: p.down_t_ms)
    return presses
