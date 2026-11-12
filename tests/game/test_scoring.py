"""Game scoring: line_feature_count/min_compared_features_for sizing,
calibrate_threshold's leave-one-line-out logic, and -- the plan's own
required check -- that a real game can actually complete (reach a
scorable MATCH/NO_MATCH, not INSUFFICIENT_DATA) on both lines with a
realistic, small number of training lines."""

from __future__ import annotations

import random

import pytest

from keystroke_dynamics.core.events import KeyEvent, pair_presses
from keystroke_dynamics.core.features import Feature, extract_features
from keystroke_dynamics.core.scoring import Decision
from keystroke_dynamics.game.scoring import (
    GAME_MAX_THRESHOLD,
    GAME_MIN_THRESHOLD,
    SCORING_VERSION,
    build_profile,
    calibrate_threshold,
    line_feature_count,
    min_compared_features_for,
    score_sample,
)

LEVEL_PHRASES = {
    "sentence": "quiet rhythm hides in every small habit of your hands",
    "long": (
        "every keyboard keeps a quiet record of the hands that use it "
        "and those records are surprisingly hard to fake"
    ),
}

#: Not a game level -- just a short phrase to exercise
#: line_feature_count/min_compared_features_for/calibrate_threshold's
#: behavior at the small end of the size range they have to handle.
SHORT_PHRASE = "bridge"


def _char_to_code(ch: str) -> str:
    return "Space" if ch == " " else f"Key{ch.upper()}"


def _synthetic_line(phrase: str, rng: random.Random) -> list[Feature]:
    """A plausible-looking typed line: each key held ~60-140ms, each
    gap to the next key ~80-220ms, with a little per-line jitter --
    built through the real core.events/core.features pipeline, the
    same one api/game.py will feed real captured events through.
    """
    events: list[KeyEvent] = []
    t = 0.0
    for ch in phrase:
        code = _char_to_code(ch)
        events.append(KeyEvent(code=code, action="down", t_ms=t))
        hold = rng.uniform(60, 140)
        events.append(KeyEvent(code=code, action="up", t_ms=t + hold))
        t += hold + rng.uniform(80, 220)
    return extract_features(pair_presses(events))


def _synthetic_lines(phrase: str, count: int, seed: int) -> list[list[Feature]]:
    rng = random.Random(seed)
    return [_synthetic_line(phrase, rng) for _ in range(count)]


# ---------- line_feature_count / min_compared_features_for ----------


def test_line_feature_count_matches_the_plans_example() -> None:
    # "about 11 features" for a 6-distinct-letter line, per the plan.
    assert line_feature_count(SHORT_PHRASE) == 11


def test_min_compared_features_is_a_fraction_of_the_lines_own_size() -> None:
    short = min_compared_features_for(SHORT_PHRASE)
    sentence = min_compared_features_for(LEVEL_PHRASES["sentence"])
    assert short < sentence  # the short line can't demand as many features
    assert sentence <= 20  # capped


def test_min_compared_features_is_never_zero() -> None:
    assert min_compared_features_for("ab") >= 1


# ---------- calibrate_threshold ----------


def test_calibrate_threshold_is_within_the_configured_clamp() -> None:
    for phrase in LEVEL_PHRASES.values():
        lines = _synthetic_lines(phrase, count=5, seed=1)
        threshold = calibrate_threshold(lines, phrase=phrase)
        assert GAME_MIN_THRESHOLD <= threshold <= GAME_MAX_THRESHOLD


def test_the_upper_clamp_is_2_and_the_scoring_version_moved_with_it() -> None:
    # Pinned on purpose: changing either without the other makes saved
    # scores look comparable when they aren't.
    assert GAME_MAX_THRESHOLD == 2.0
    # "3" added touch rooms and left keyboard scoring as it was at "2"
    # (test_keyboard_golden.py), so the clamp still goes with it.
    assert SCORING_VERSION == "3"


@pytest.mark.parametrize("phrase", LEVEL_PHRASES.values())
def test_one_stumbled_training_line_cannot_push_the_limit_past_the_cap(phrase: str) -> None:
    lines = _synthetic_lines(phrase, count=4, seed=3)
    without_stumble = calibrate_threshold(lines, phrase=phrase)
    # One line typed four times slower than the rest: its held-out
    # score alone would set a limit far above the cap.
    lines[2] = [Feature(f.key, f.value_ms * 4) for f in lines[2]]
    assert calibrate_threshold(lines, phrase=phrase) == GAME_MAX_THRESHOLD
    assert without_stumble <= GAME_MAX_THRESHOLD


def test_calibrate_threshold_falls_back_to_the_minimum_with_too_few_lines() -> None:
    # A single training line has no "other lines" to hold it out
    # against for any iteration.
    lines = _synthetic_lines(SHORT_PHRASE, count=1, seed=2)
    assert calibrate_threshold(lines, phrase=SHORT_PHRASE) == GAME_MIN_THRESHOLD


# ---------- a real game can complete on every line ----------


@pytest.mark.parametrize("level", ["sentence", "long"])
def test_a_real_game_can_complete_on_every_line(level: str) -> None:
    phrase = LEVEL_PHRASES[level]
    training = _synthetic_lines(phrase, count=5, seed=42)
    profile = build_profile(training)
    threshold = calibrate_threshold(training, phrase=phrase)

    # A fresh, similarly-typed line from the same (synthetic) typist
    # must be scorable -- not INSUFFICIENT_DATA -- on every line
    # length.
    genuine = _synthetic_lines(phrase, count=1, seed=43)[0]
    result = score_sample(genuine, profile, phrase=phrase, threshold=threshold)
    assert result.decision in (Decision.MATCH, Decision.NO_MATCH)
    assert result.score is not None
    assert result.compared_features >= min_compared_features_for(phrase)
