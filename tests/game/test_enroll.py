"""game/enroll.py: the shared raw-runs-to-derived-shape pipeline every
player-shaped entity (real players, sample bots, the permanent
target) goes through."""

from __future__ import annotations

from keystroke_dynamics.core.events import KeyEvent
from keystroke_dynamics.game.enroll import (
    build_profile_and_threshold,
    char_to_code,
    median_notes,
    phrase_from_run,
)
from keystroke_dynamics.game.scoring import GAME_MAX_THRESHOLD, GAME_MIN_THRESHOLD


def test_char_to_code_round_trips_through_space() -> None:
    assert char_to_code(" ") == "Space"
    assert char_to_code("a") == "KeyA"


def _run(phrase: str, hold_ms: float, gap_ms: float) -> list[KeyEvent]:
    events: list[KeyEvent] = []
    t = 0.0
    for i, ch in enumerate(phrase):
        if i > 0:
            t += gap_ms
        code = char_to_code(ch)
        events.append(KeyEvent(code=code, action="down", t_ms=t))
        events.append(KeyEvent(code=code, action="up", t_ms=t + hold_ms))
    return events


def test_phrase_from_run_recovers_the_typed_characters() -> None:
    run = _run("ab c", hold_ms=80.0, gap_ms=150.0)
    assert phrase_from_run(run) == "ab c"


def test_median_notes_picks_the_middle_value_not_the_mean() -> None:
    runs = [_run("ab", hold_ms=h, gap_ms=100.0) for h in (10.0, 20.0, 90.0)]
    notes = median_notes("ab", runs)
    assert [n.dur_ms for n in notes] == [20.0, 20.0]  # median of 10/20/90, not the mean (40)


def test_median_notes_first_key_starts_at_zero() -> None:
    notes = median_notes("ab", [_run("ab", hold_ms=50.0, gap_ms=123.0)])
    assert notes[0].start_ms == 0.0
    assert notes[1].start_ms == 123.0


def test_build_profile_and_threshold_is_within_the_configured_clamp() -> None:
    runs = [_run("nukiae", hold_ms=80.0 + i, gap_ms=150.0 + i) for i in range(5)]
    _profile, threshold = build_profile_and_threshold("nukiae", runs)
    assert GAME_MIN_THRESHOLD <= threshold <= GAME_MAX_THRESHOLD
