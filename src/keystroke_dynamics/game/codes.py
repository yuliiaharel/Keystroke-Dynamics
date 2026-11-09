"""Room codes: the only key to a room (docs/plans/active/ROOMS_PLAN.md,
"Decisions already made"), so they come from `secrets`, never
`random`. 8 characters from a 32-letter alphabet is 40 bits -- with
the join rate limit (api/game.py) that makes guessing a live room
impractical.
"""

from __future__ import annotations

import secrets

#: No I, O, 0, or 1 -- nothing that reads as something else when a
#: code is said aloud or copied by hand.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8


def generate_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(raw: str) -> str | None:
    """The canonical 8-character form of what someone typed or pasted
    -- any case, with or without the display dash (`abcd-efgh`) or
    stray spaces. None when it can't be a code at all; callers answer
    that exactly like a well-formed code that names no live room.
    """
    code = "".join(ch for ch in raw.upper() if ch not in "- \t")
    if len(code) != CODE_LENGTH or any(ch not in CODE_ALPHABET for ch in code):
        return None
    return code
