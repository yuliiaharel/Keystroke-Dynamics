"""Keyboard scores and limits, pinned to the values the game produced
before touch scoring existed (docs/plans/active/MOBILE_PLAN.md Phase 1
section 5: "a golden test that confirms keyboard scores and limits are
identical before and after this change").

golden/keyboard_scores.json was written by this module's own
compute_golden() at the commit that merged master into the mobile
branch, before any Phase 1 change. The comparison is exact -- no
tolerance -- because the keyboard path must do the same arithmetic in
the same order, not merely land close.

Never regenerate the file to make this test pass. Regenerating is
only right when a task deliberately changes keyboard scoring, and
then SCORING_VERSION changes with it:

    uv run python -m tests.game.test_keyboard_golden
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from keystroke_dynamics.core.events import KeyEvent, pair_presses
from keystroke_dynamics.core.features import extract_features
from keystroke_dynamics.game.enroll import build_profile_and_threshold, char_to_code, median_notes
from keystroke_dynamics.game.judge import judge
from keystroke_dynamics.game.levels import LEVELS
from keystroke_dynamics.game.scoring import score_sample
from keystroke_dynamics.game.store import Player
from keystroke_dynamics.game.targets import sample_targets

GOLDEN_PATH = Path(__file__).parent / "golden" / "keyboard_scores.json"

KEYBOARD_LEVELS = ("sentence", "long")

#: (name, speed, jitter): how fast a typist is, and how much each line
#: of theirs varies from their own habit.
TYPISTS = [("steady", 1.0, 0.05), ("quick", 0.7, 0.45), ("slow", 1.5, 0.6), ("erratic", 1.1, 0.9)]

TRAINING_LINES = 4
ATTEMPTS_PER_TYPIST = 2


def _run(phrase: str, habit: random.Random, noise: random.Random, speed: float, jitter: float):
    """One typing of `phrase`. `habit` is reseeded identically for
    every line of one typist, so each key keeps its own usual timing;
    `noise` moves on, so lines differ by `jitter`."""
    events: list[KeyEvent] = []
    t = 0.0
    for i, ch in enumerate(phrase):
        wobble = 1 + noise.uniform(-jitter, jitter)
        if i > 0:
            t += speed * habit.uniform(90, 260) * wobble
        hold = speed * habit.uniform(50, 120) * wobble
        code = char_to_code(ch)
        events.append(KeyEvent(code=code, action="down", t_ms=t))
        events.append(KeyEvent(code=code, action="up", t_ms=t + hold))
    return events


def _runs(level: str, phrase: str, name: str, speed: float, jitter: float, count: int):
    noise = random.Random(f"noise:{level}:{name}")
    return [
        _run(phrase, random.Random(f"habit:{level}:{name}"), noise, speed, jitter)
        for _ in range(count)
    ]


def compute_golden() -> dict[str, object]:
    out: dict[str, object] = {}
    for level in KEYBOARD_LEVELS:
        phrase = LEVELS[level].phrase  # type: ignore[index]
        players: dict[str, Player] = {}
        attempts: dict[str, list[list[KeyEvent]]] = {}
        for name, speed, jitter in TYPISTS:
            runs = _runs(level, phrase, name, speed, jitter, TRAINING_LINES + ATTEMPTS_PER_TYPIST)
            training, attempts[name] = runs[:TRAINING_LINES], runs[TRAINING_LINES:]
            profile, threshold = build_profile_and_threshold(phrase, training)
            players[name] = Player(
                id=name,
                name=name,
                color=0,
                profile=profile,
                threshold=threshold,
                notes=median_notes(phrase, training),
            )

        level_out: dict[str, object] = {
            "limits": {name: p.threshold for name, p in players.items()},
            "sample_bot_limits": {b.id: b.threshold for b in sample_targets(level, phrase)},
        }
        scores: dict[str, object] = {}
        for target_name, target in players.items():
            for typist_name, lines in attempts.items():
                for i, line in enumerate(lines):
                    sample = extract_features(pair_presses(line))
                    result = score_sample(
                        sample, target.profile, phrase=phrase, threshold=target.threshold
                    )
                    verdict = judge(
                        sample,
                        typist_name=typist_name,
                        target=target,
                        mode="self" if typist_name == target_name else "attack",
                        phrase=phrase,
                        run_duration_ms=line[-1].t_ms,
                    )
                    scores[f"{typist_name}->{target_name}#{i}"] = {
                        "score": result.score,
                        "decision": result.decision.value,
                        "compared_features": result.compared_features,
                        "word": verdict.word,
                        "passed": verdict.passed,
                        "pace": verdict.pace,
                        "clue": verdict.clue,
                    }
            # Six keys of a line: too few features to score at all.
            short = attempts[target_name][0][:12]
            result = score_sample(
                extract_features(pair_presses(short)),
                target.profile,
                phrase=phrase,
                threshold=target.threshold,
            )
            scores[f"short->{target_name}"] = {
                "score": result.score,
                "decision": result.decision.value,
                "compared_features": result.compared_features,
            }
        level_out["scores"] = scores
        out[level] = level_out
    return out


def test_keyboard_scores_and_limits_match_the_golden_file() -> None:
    golden = json.loads(GOLDEN_PATH.read_text())
    # Through JSON and back, so both sides are compared in the same
    # shape. A float survives that round trip exactly.
    assert json.loads(json.dumps(compute_golden())) == golden


def test_the_golden_file_covers_passes_fails_and_unscorable_lines() -> None:
    # Guards the fixture itself: a golden file where everything fails,
    # or every limit sits on a clamp, would pin very little.
    golden = json.loads(GOLDEN_PATH.read_text())
    decisions = {
        s["decision"] for level in KEYBOARD_LEVELS for s in golden[level]["scores"].values()
    }
    assert decisions == {"match", "no_match", "insufficient_data"}
    limits = [v for level in KEYBOARD_LEVELS for v in golden[level]["limits"].values()]
    assert any(1.3 < v < 2.0 for v in limits)


if __name__ == "__main__":
    GOLDEN_PATH.parent.mkdir(exist_ok=True)
    GOLDEN_PATH.write_text(json.dumps(compute_golden(), indent=1) + "\n")
    print(f"wrote {GOLDEN_PATH}")
