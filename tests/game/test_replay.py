"""game/replay.py: reconstructing a run from median notes, and that
the reconstruction actually scores within the target's own threshold
(the replay attack's whole point)."""

from __future__ import annotations

from keystroke_dynamics.core.events import KeyEvent, pair_presses
from keystroke_dynamics.core.features import extract_features
from keystroke_dynamics.game.enroll import build_profile_and_threshold, char_to_code, median_notes
from keystroke_dynamics.game.judge import judge
from keystroke_dynamics.game.replay import notes_to_events
from keystroke_dynamics.game.store import Player

PHRASE = "nukiae"


def _run(hold_ms: float, gap_ms: float) -> list[KeyEvent]:
    events: list[KeyEvent] = []
    t = 0.0
    for i, ch in enumerate(PHRASE):
        if i > 0:
            t += gap_ms
        code = char_to_code(ch)
        events.append(KeyEvent(code=code, action="down", t_ms=t))
        events.append(KeyEvent(code=code, action="up", t_ms=t + hold_ms))
    return events


def make_target() -> Player:
    runs = [_run(hold_ms=80.0 + i, gap_ms=150.0 + i) for i in range(5)]
    profile, threshold = build_profile_and_threshold(PHRASE, runs)
    notes = median_notes(PHRASE, runs)
    return Player(
        id="p1", name="Target", color=0, profile=profile, threshold=threshold, notes=notes
    )


def test_notes_to_events_preserves_key_order_and_timing() -> None:
    target = make_target()
    events = notes_to_events(target.notes)
    assert len(events) == 2 * len(target.notes)  # one down + one up per note
    for note, (down, up) in zip(
        target.notes, zip(events[0::2], events[1::2], strict=True), strict=True
    ):
        assert down.action == "down"
        assert up.action == "up"
        assert down.t_ms == note.start_ms
        assert up.t_ms == note.start_ms + note.dur_ms


def test_replayed_run_scores_within_the_targets_own_threshold() -> None:
    target = make_target()
    events = notes_to_events(target.notes)
    sample = extract_features(pair_presses(events))
    verdict = judge(
        sample,
        typist_name="Replay bot",
        target=target,
        mode="replay",
        phrase=PHRASE,
        run_duration_ms=events[-1].t_ms,
    )
    assert verdict.word == "Replay wins"
    assert verdict.passed is True
