"""Generated display names, and validation for custom ones.

Not a moderation system -- a basic, honestly-labeled starting list
(PARTY_LAUNCH_PLAN.md Part 1 section 3 calls for exactly that: "a
basic blocked-word list"). Treat NotGoodEnoughForScale as a given, not
a bug: expanding this list is cheap and expected over time.
"""

from __future__ import annotations

import secrets

_ADJECTIVES = [
    "Quiet",
    "Quick",
    "Steady",
    "Clever",
    "Bright",
    "Brisk",
    "Calm",
    "Daring",
    "Eager",
    "Gentle",
    "Jolly",
    "Nimble",
    "Plucky",
    "Sly",
    "Sunny",
    "Tidy",
    "Witty",
    "Zesty",
]
_NOUNS = [
    "Otter",
    "Falcon",
    "Badger",
    "Heron",
    "Lynx",
    "Marten",
    "Osprey",
    "Raven",
    "Swift",
    "Weasel",
    "Wren",
    "Fox",
    "Hare",
    "Mole",
    "Newt",
    "Vole",
]

MIN_LENGTH = 1
MAX_LENGTH = 24

#: A short, honest starting list -- see the module docstring. Checked
#: as whole words (case-insensitive) against a trimmed custom name,
#: not as a substring match, to avoid flagging innocuous names that
#: happen to contain one of these as part of a longer word.
_BLOCKED_WORDS = frozenset(
    {
        "admin",
        "administrator",
        "fuck",
        "shit",
        "bitch",
        "cunt",
        "nigger",
        "nigga",
        "faggot",
        "retard",
        "rape",
        "moderator",
        "root",
        "null",
        "undefined",
    }
)


def generate_name(rng: secrets.SystemRandom | None = None) -> str:
    """A fresh "Quiet Otter"-style name. Not guaranteed unique against
    a party's existing names -- callers that need uniqueness within a
    party should retry (see game/store.py)."""
    r = rng or secrets.SystemRandom()
    return f"{r.choice(_ADJECTIVES)} {r.choice(_NOUNS)}"


class InvalidNameError(ValueError):
    """Raised by validate_custom_name; .reason is user-facing."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def validate_custom_name(raw: str, *, existing_names: set[str]) -> str:
    """Trims `raw` and returns it if it's an acceptable custom player
    name within a party: MIN_LENGTH-MAX_LENGTH characters after
    trimming, no blocked word as a whole word, and no duplicate
    (case-insensitive) of an existing name in the same party.

    Raises InvalidNameError otherwise. `existing_names` should already
    be lowercased by the caller, or pass raw names -- comparison here
    lowercases both sides.
    """
    name = raw.strip()
    if not (MIN_LENGTH <= len(name) <= MAX_LENGTH):
        raise InvalidNameError(f"Name must be {MIN_LENGTH}-{MAX_LENGTH} characters.")

    words = {w.strip(".,!?'\"").lower() for w in name.split()}
    if words & _BLOCKED_WORDS:
        raise InvalidNameError("That name isn't allowed. Try something else.")

    if name.lower() in {existing.lower() for existing in existing_names}:
        raise InvalidNameError("Someone in this party already has that name.")

    return name
