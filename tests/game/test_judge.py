"""game/judge.py: the pass/fail verdict for each mode, matching the
approved mockup's judge() rules -- self/disguise/attack/replay, the
disguise pace gate, and the "too messy" (INSUFFICIENT_DATA) case."""

from __future__ import annotations

from keystroke_dynamics.core.events import KeyEvent, pair_presses
from keystroke_dynamics.core.features import extract_features
from keystroke_dynamics.game.enroll import build_profile_and_threshold, char_to_code, median_notes
from keystroke_dynamics.game.judge import judge, usual_duration_ms
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


def _sample_from(run: list[KeyEvent]) -> list:
    return extract_features(pair_presses(run))


def _duration_ms(run: list[KeyEvent]) -> float:
    presses = pair_presses(run)
    last = presses[-1]
    return last.down_t_ms - presses[0].down_t_ms + (last.up_t_ms - last.down_t_ms)


def make_target(name: str = "Target") -> Player:
    runs = [_run(hold_ms=80.0 + i, gap_ms=150.0 + i) for i in range(5)]
    profile, threshold = build_profile_and_threshold(PHRASE, runs)
    notes = median_notes(PHRASE, runs)
    return Player(id="p1", name=name, color=0, profile=profile, threshold=threshold, notes=notes)


def test_too_messy_when_score_is_insufficient_data() -> None:
    target = make_target()
    verdict = judge(
        [], typist_name="Guest", target=target, mode="attack", phrase=PHRASE, run_duration_ms=500.0
    )
    assert verdict.word == "Too messy"
    assert verdict.counted is False
    assert verdict.passed is None


def test_self_mode_within_own_range_passes() -> None:
    target = make_target()
    own_run = _run(hold_ms=82.0, gap_ms=152.0)  # right in the middle of the training spread
    verdict = judge(
        _sample_from(own_run),
        typist_name=target.name,
        target=target,
        mode="self",
        phrase=PHRASE,
        run_duration_ms=_duration_ms(own_run),
    )
    assert verdict.word == "That's you"
    assert verdict.counted is True
    assert verdict.passed is True


def test_self_mode_far_outside_own_range_is_rejected() -> None:
    target = make_target()
    foreign_run = _run(hold_ms=400.0, gap_ms=900.0)
    verdict = judge(
        _sample_from(foreign_run),
        typist_name=target.name,
        target=target,
        mode="self",
        phrase=PHRASE,
        run_duration_ms=_duration_ms(foreign_run),
    )
    assert verdict.word == "Who are you?"
    assert verdict.passed is False


def test_attack_mode_matching_the_targets_rhythm_fools_it() -> None:
    target = make_target()
    matching_run = _run(hold_ms=82.0, gap_ms=152.0)
    verdict = judge(
        _sample_from(matching_run),
        typist_name="Guest",
        target=target,
        mode="attack",
        phrase=PHRASE,
        run_duration_ms=_duration_ms(matching_run),
    )
    assert verdict.word == "Fooled it!"
    assert verdict.passed is True
    assert "Guest" in verdict.text
    assert target.name in verdict.text


def test_attack_mode_mismatched_rhythm_is_caught() -> None:
    target = make_target()
    off_run = _run(hold_ms=400.0, gap_ms=900.0)
    verdict = judge(
        _sample_from(off_run),
        typist_name="Mallory",
        target=target,
        mode="attack",
        phrase=PHRASE,
        run_duration_ms=_duration_ms(off_run),
    )
    assert verdict.word == "Caught!"
    assert verdict.passed is False


def test_disguise_mode_rejects_a_pace_outside_the_tolerance_before_scoring() -> None:
    target = make_target()
    much_faster_run = _run(hold_ms=20.0, gap_ms=30.0)  # far under 85% of usual pace
    verdict = judge(
        _sample_from(much_faster_run),
        typist_name=target.name,
        target=target,
        mode="disguise",
        phrase=PHRASE,
        run_duration_ms=_duration_ms(much_faster_run),
    )
    assert verdict.word == "Too fast"
    assert verdict.counted is False
    assert verdict.passed is None


def test_disguise_mode_at_normal_pace_but_still_matching_rhythm_fails() -> None:
    target = make_target()
    matching_run = _run(hold_ms=82.0, gap_ms=152.0)
    verdict = judge(
        _sample_from(matching_run),
        typist_name=target.name,
        target=target,
        mode="disguise",
        phrase=PHRASE,
        run_duration_ms=_duration_ms(matching_run),
    )
    assert verdict.word == "Still you"
    assert verdict.counted is True
    assert verdict.passed is True


def test_replay_mode_within_threshold_wins() -> None:
    target = make_target()
    # The target's own median notes converted back into a run must
    # replay cleanly within its own threshold -- that's the whole
    # point of the replay-attack demonstration.
    on_target_run = _run(hold_ms=82.0, gap_ms=152.0)
    verdict = judge(
        _sample_from(on_target_run),
        typist_name="Replay bot",
        target=target,
        mode="replay",
        phrase=PHRASE,
        run_duration_ms=_duration_ms(on_target_run),
    )
    assert verdict.word == "Replay wins"
    assert verdict.passed is True


def test_usual_duration_ms_sums_the_last_notes_start_and_duration() -> None:
    target = make_target()
    last = target.notes[-1]
    assert usual_duration_ms(target) == last.start_ms + last.dur_ms


def test_usual_duration_ms_is_zero_with_no_notes() -> None:
    empty = Player(id="p2", name="Empty", color=0, profile={}, threshold=1.5, notes=[])
    assert usual_duration_ms(empty) == 0.0
