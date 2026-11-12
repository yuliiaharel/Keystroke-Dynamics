"""The replay attack: reconstructs a synthetic run from a target's
*median* timing (never one of their raw recorded runs -- none are
kept past enrollment, see game/store.py) and scores it the same way
any other attempt is scored.

docs/plans/done/PARTY_LAUNCH_PLAN.md Part 1 section 6: "Run the replay on the server
using the target's median timing, then score it. The browser receives
only what it needs to animate the replay." The browser gets back the
same Note list it already gets for drawing any player's signature
ring -- aggregated median timing, not a secret -- never anything
target-specific beyond that.
"""

from __future__ import annotations

from collections.abc import Mapping

from keystroke_dynamics.core.events import KeyEvent
from keystroke_dynamics.core.stats import RunningStats
from keystroke_dynamics.game.enroll import char_to_code
from keystroke_dynamics.game.place import PlaceKey
from keystroke_dynamics.game.store import Note
from keystroke_dynamics.game.taps import TapEvent


def notes_to_events(notes: list[Note]) -> list[KeyEvent]:
    """The target's typical timing, replayed as a run: each note's
    start_ms/dur_ms becomes one key's down/up pair."""
    events: list[KeyEvent] = []
    for note in notes:
        code = char_to_code(note.ch)
        events.append(KeyEvent(code=code, action="down", t_ms=note.start_ms))
        events.append(KeyEvent(code=code, action="up", t_ms=note.start_ms + note.dur_ms))
    return events


def notes_to_taps(
    notes: list[Note], place_profile: Mapping[PlaceKey, RunningStats]
) -> list[TapEvent]:
    """The touch replay (docs/plans/active/MOBILE_PLAN.md Phase 1
    section 8): the target's median timing, with each tap landing on
    the target's own average spot for that key. A key with no recorded
    position lands dead center -- only the space bar's dx, which is
    never scored."""
    taps: list[TapEvent] = []
    for event in notes_to_events(notes):
        if event.action == "up":
            taps.append(TapEvent(code=event.code, action="up", t_ms=event.t_ms))
            continue
        x = place_profile.get(("tap_x", event.code))
        y = place_profile.get(("tap_y", event.code))
        taps.append(
            TapEvent(
                code=event.code,
                action="down",
                t_ms=event.t_ms,
                dx=x.mean if x is not None else 0.0,
                dy=y.mean if y is not None else 0.0,
            )
        )
    return taps
