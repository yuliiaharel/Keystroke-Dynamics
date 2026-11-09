"""Canonical level/phrase definitions -- the one source of truth for
what each level's line actually is, taken directly from the approved
mockup's own LEVELS object (design/typing-twin-party.html) per
PARTY_LAUNCH_PLAN.md's rule to keep its copy unless told otherwise.

The backend needs the phrase to extract and score features against;
the API exposes it in party state (game/schemas.py) so the frontend
never needs its own copy to drift out of sync with this one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Level = Literal["sentence", "long"]


@dataclass(frozen=True)
class LevelInfo:
    name: str
    blurb: str
    phrase: str
    rounds: int


LEVELS: dict[Level, LevelInfo] = {
    "sentence": LevelInfo(
        name="A sentence",
        blurb="The best party mode. About a minute each.",
        phrase="quiet rhythm hides in every small habit of your hands",
        rounds=5,
    ),
    "long": LevelInfo(
        name="A long line",
        blurb="More to measure, more to fake. About 2 minutes each.",
        phrase=(
            "every keyboard keeps a quiet record of the hands that use it "
            "and those records are surprisingly hard to fake"
        ),
        rounds=4,
    ),
}
