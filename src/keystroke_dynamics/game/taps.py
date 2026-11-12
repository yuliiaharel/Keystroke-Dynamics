"""Touch input for the party game: one event per finger landing on or
lifting from a key of the on-page keyboard (docs/plans/active/MOBILE_PLAN.md
Phase 1 section 2). A tap is a key event plus where on the key the
finger landed.

Game-only. The account API's event format (api/schemas.py's
KeyEventSchema, core.events.KeyEvent) is untouched: timing still goes
through core.events' own validation and pairing, via to_key_events.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from string import ascii_uppercase

from keystroke_dynamics.core.events import Action, InvalidSampleError, KeyEvent, validate

#: Every key the on-page keyboard has (design/typing-twin-touch.html):
#: the letters and the space bar.
TOUCH_CODES = frozenset({*(f"Key{letter}" for letter in ascii_uppercase), "Space"})

#: How far from a key's center a tap may claim to be, in letter-key
#: widths and heights. A tap that lands on a key is within half a key
#: of its center, except sideways on the space bar, which is several
#: letter keys wide. Anything past these didn't come from the on-page
#: keyboard.
MAX_TAP_DX = 4.0
MAX_TAP_DY = 1.0


@dataclass(frozen=True)
class TapEvent:
    code: str
    action: Action
    t_ms: float
    #: Down events only: offset from the key's center, in letter-key
    #: widths (dx) and heights (dy), so it doesn't depend on screen size.
    dx: float | None = None
    dy: float | None = None


def to_key_events(events: Sequence[TapEvent]) -> list[KeyEvent]:
    return [KeyEvent(code=e.code, action=e.action, t_ms=e.t_ms) for e in events]


def validate_keyboard_events(events: Sequence[TapEvent], *, max_events: int) -> None:
    """A physical keyboard has no tap position, so a sample from a
    keyboard room must not carry one. Then core.events' own checks.

    Messages never include a submitted value: they end up in a 400
    response, and raw input must not be echoed or logged."""
    if any(e.dx is not None or e.dy is not None for e in events):
        raise InvalidSampleError("tap positions are only accepted in touch rooms")
    validate(to_key_events(events), max_events=max_events)


def validate_taps(events: Sequence[TapEvent], *, max_events: int) -> None:
    """core.events' size and timing checks, then the touch-only rules:
    every key is on the on-page keyboard, every down event says where
    it landed, and no up event does."""
    validate(to_key_events(events), max_events=max_events)
    for event in events:
        if event.code not in TOUCH_CODES:
            raise InvalidSampleError("a key that isn't on the on-page keyboard")
        if event.action == "up":
            if event.dx is not None or event.dy is not None:
                raise InvalidSampleError("an up event can't carry a tap position")
            continue
        if event.dx is None or event.dy is None:
            raise InvalidSampleError("a down event is missing its tap position")
        if not (math.isfinite(event.dx) and math.isfinite(event.dy)):
            raise InvalidSampleError("non-finite tap position")
        if abs(event.dx) > MAX_TAP_DX or abs(event.dy) > MAX_TAP_DY:
            raise InvalidSampleError("tap position is too far from its key")
