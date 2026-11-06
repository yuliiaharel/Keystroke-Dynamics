"""Turns raw training runs into the derived shape a Player needs.

Every player-shaped entity in the game -- a real party player
(api/game.py), a sample bot, or the permanent target (game/targets.py)
-- goes through this same pipeline: a profile (Welford stats, game-
tuned scoring), a calibrated threshold, and median notes for the
ring/roll. None of them retain the raw runs past this call -- that's
the module boundary that makes "no raw training lines kept after
enrollment" (PARTY_LAUNCH_PLAN.md Part 1 section 2) true everywhere at
once, rather than something each caller has to remember to do.
"""

from __future__ import annotations

from keystroke_dynamics.core.events import KeyEvent, pair_presses
from keystroke_dynamics.core.features import FeatureKey, extract_features
from keystroke_dynamics.core.stats import RunningStats
from keystroke_dynamics.game.scoring import build_profile, calibrate_threshold
from keystroke_dynamics.game.store import Note


def char_to_code(ch: str) -> str:
    return "Space" if ch == " " else f"Key{ch.upper()}"


def phrase_from_run(run: list[KeyEvent]) -> str:
    """Recovers the typed characters straight from one run's own key
    codes (in down order) -- callers that already know the target
    phrase don't need this, but save_permanent_target's input doesn't
    carry the phrase as a separate field."""
    codes = (p.code for p in pair_presses(run))
    return "".join(" " if code == "Space" else code.removeprefix("Key").lower() for code in codes)


def median_notes(phrase: str, runs: list[list[KeyEvent]]) -> list[Note]:
    """The median down-to-down gap and hold duration at each position
    across runs -- never one run's raw timing on its own."""
    presses_per_run = [pair_presses(run) for run in runs]
    t = 0.0
    notes: list[Note] = []
    for i, ch in enumerate(phrase):
        if i > 0:
            gaps = sorted(
                presses[i].down_t_ms - presses[i - 1].down_t_ms for presses in presses_per_run
            )
            t += gaps[len(gaps) // 2]
        durations = sorted(presses[i].up_t_ms - presses[i].down_t_ms for presses in presses_per_run)
        notes.append(Note(ch=ch, start_ms=t, dur_ms=durations[len(durations) // 2]))
    return notes


def build_profile_and_threshold(
    phrase: str, runs: list[list[KeyEvent]]
) -> tuple[dict[FeatureKey, RunningStats], float]:
    """Folds every run's features into one profile (game/scoring.py's
    constants, sized for a handful of training lines) and calibrates
    a per-player limit via leave-one-line-out scoring."""
    training_features = [extract_features(pair_presses(run)) for run in runs]
    profile = build_profile(training_features)
    threshold = calibrate_threshold(training_features, phrase=phrase)
    return profile, threshold
