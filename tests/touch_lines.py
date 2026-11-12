"""Simulated tap lines for the touch tests. Not a pytest module.

Each typist has their own habit for every key (how long they hold it,
where on it they land) and every key pair (the gap between them), all
fixed by the typist's name, plus a per-line wobble. Enough structure
that two typists really differ, and one typist's lines really agree.
"""

from __future__ import annotations

import random

from keystroke_dynamics.game.levels import LEVELS, TOUCH_LEVEL
from keystroke_dynamics.game.taps import TapEvent

TOUCH_PHRASE = LEVELS[TOUCH_LEVEL].phrase


def _code(ch: str) -> str:
    return "Space" if ch == " " else f"Key{ch.upper()}"


def tap_line(
    typist: str = "alice",
    *,
    line: int = 0,
    speed: float = 1.0,
    wobble: float = 0.04,
    shift: tuple[float, float] = (0.0, 0.0),
    phrase: str = TOUCH_PHRASE,
) -> list[dict]:
    """One tapping of `phrase` as the JSON the API takes. `line` picks
    which of this typist's lines it is; `shift` moves every tap, as a
    different grip would."""

    def habit(what: str) -> float:
        return random.Random(f"{typist}|{what}").random()

    noise = random.Random(f"{typist}|line:{line}")
    events: list[dict] = []
    t = 0.0
    for i, ch in enumerate(phrase):
        if i > 0:
            gap = 120 + 220 * habit(f"gap:{phrase[i - 1]}{ch}")
            t += speed * gap * (1 + noise.uniform(-wobble, wobble))
        hold = (55 + 60 * habit(f"hold:{ch}")) * (1 + noise.uniform(-wobble, wobble))
        code = _code(ch)
        dx = shift[0] + (habit(f"x:{ch}") - 0.5) * 0.5 + noise.uniform(-wobble, wobble)
        dy = shift[1] + (habit(f"y:{ch}") - 0.5) * 0.5 + noise.uniform(-wobble, wobble)
        events.append({"code": code, "action": "down", "t_ms": t, "dx": dx, "dy": dy})
        events.append({"code": code, "action": "up", "t_ms": t + hold})
    return events


def tap_lines(typist: str = "alice", count: int = 4, **kwargs: object) -> list[list[dict]]:
    """`count` training lines for one typist: lines 0 to count-1."""
    return [tap_line(typist, line=i, **kwargs) for i in range(count)]  # type: ignore[arg-type]


def to_taps(events: list[dict]) -> list[TapEvent]:
    return [TapEvent(**e) for e in events]
