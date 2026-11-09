"""game/judge.py: the pass/fail verdict for each mode, matching the
approved mockup's judge() rules -- self/disguise/attack/replay, the
disguise pace gate, and the "too messy" (INSUFFICIENT_DATA) case."""

from __future__ import annotations

import pytest

from keystroke_dynamics.core.events import KeyEvent, pair_presses
from keystroke_dynamics.core.features import extract_features
from keystroke_dynamics.game.enroll import build_profile_and_threshold, char_to_code, median_notes
from keystroke_dynamics.game.judge import _clue, judge, pace_ratio, usual_duration_ms
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


# ---------- pace and clue (PARTY_LAUNCH_PLAN.md section 8) ----------


def test_too_messy_has_no_pace_or_clue() -> None:
    target = make_target()
    verdict = judge(
        [], typist_name="Guest", target=target, mode="attack", phrase=PHRASE, run_duration_ms=500.0
    )
    assert verdict.pace is None
    assert verdict.clue is None
    # compared_features is still meaningful on a "too messy" result --
    # it's exactly why: fewer than game/scoring.py's own minimum. Zero
    # here since the sample itself is empty.
    assert verdict.compared_features == 0


def test_pace_ratio_is_none_with_no_notes() -> None:
    empty = Player(id="p2", name="Empty", color=0, profile={}, threshold=1.5, notes=[])
    assert pace_ratio(500.0, empty) is None


def test_pace_ratio_is_always_available_even_on_a_too_messy_result() -> None:
    # Unlike Verdict.pace (the UI's own display rule, None alongside
    # distance=None), game/scores's own pace column uses pace_ratio()
    # directly -- it's independently meaningful research data even
    # when the rhythm itself couldn't be scored at all.
    target = make_target()
    assert pace_ratio(usual_duration_ms(target), target) == pytest.approx(1.0)


def test_matching_rhythm_at_the_right_pace_gives_a_fitting_clue() -> None:
    target = make_target()
    matching_run = _run(hold_ms=82.0, gap_ms=152.0)
    verdict = judge(
        _sample_from(matching_run),
        typist_name=target.name,
        target=target,
        mode="self",
        phrase=PHRASE,
        run_duration_ms=_duration_ms(matching_run),
    )
    assert verdict.pace == pytest.approx(1.0, abs=0.1)
    assert verdict.clue == "Right speed, and the rhythm fits"


def test_mismatched_rhythm_at_the_right_pace_names_the_rhythm() -> None:
    target = make_target()
    off_run = _run(hold_ms=400.0, gap_ms=900.0)
    # Deliberately NOT a proportional speed-up of the whole line (that
    # would also move pace out of the "right speed" band) -- just a
    # much bigger hold/gap that still starts and ends close to the
    # target's own usual duration, isolating "rhythm is off" from
    # "pace is off".
    usual = usual_duration_ms(target)
    verdict = judge(
        _sample_from(off_run),
        typist_name="Mallory",
        target=target,
        mode="attack",
        phrase=PHRASE,
        run_duration_ms=usual,
    )
    assert verdict.pace == pytest.approx(1.0, abs=0.01)
    assert verdict.clue == "Right speed, wrong rhythm"


def test_a_much_faster_run_names_the_pace() -> None:
    target = make_target()
    fast_run = _run(hold_ms=20.0, gap_ms=30.0)
    verdict = judge(
        _sample_from(fast_run),
        typist_name="Mallory",
        target=target,
        mode="attack",
        phrase=PHRASE,
        run_duration_ms=_duration_ms(fast_run),
    )
    assert verdict.pace is not None
    assert verdict.pace < 0.85
    assert verdict.clue == "Too fast, and the rhythm is off too"


def test_clue_never_claims_everything_fits_when_the_rhythm_is_off() -> None:
    # The one invariant PARTY_LAUNCH_PLAN.md section 8 names
    # explicitly: a clue must never say the rhythm fits when the
    # distance that produced it didn't. Swept across a range of
    # paces and rhythms rather than one example, since _clue() is a
    # pure function of (distance, threshold, pace).
    for pace in (0.5, 0.8, 0.9, 1.0, 1.1, 1.2, 1.5):
        clue = _clue(distance=2.0, threshold=1.0, pace=pace)
        assert "fits" not in clue, (pace, clue)
