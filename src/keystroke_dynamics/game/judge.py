"""Server-side judging: scores one typed sample against a target and
produces the same pass/fail verdict shape the approved mockup's
judge() computes, working only from a stored Player (profile +
threshold + notes) -- never raw training runs, since none are kept
past enrollment (see game/store.py).
"""

from __future__ import annotations

from dataclasses import dataclass

from keystroke_dynamics.core.features import Feature
from keystroke_dynamics.game.scoring import score_sample
from keystroke_dynamics.game.store import Mode, Player

#: A disguise attempt's typing pace must stay within this fraction of
#: the typist's own usual pace, or it's disqualified before scoring
#: even happens -- matches the approved mockup's rule exactly.
DISGUISE_PACE_TOLERANCE = 0.15


@dataclass(frozen=True)
class Verdict:
    word: str
    text: str
    counted: bool
    #: None when not counted (score was INSUFFICIENT_DATA, or a
    #: disguise attempt broke the pace rule before scoring mattered).
    passed: bool | None
    distance: float | None
    ratio: float | None


def usual_duration_ms(player: Player) -> float:
    """Total time to type the line at this player's own median pace,
    derived from their stored notes -- the only timing record kept
    past enrollment. 0.0 for a player with no notes (shouldn't
    normally happen; callers divide by this, so 0.0 rather than
    raising lets a caller decide how to handle it)."""
    if not player.notes:
        return 0.0
    last = player.notes[-1]
    return last.start_ms + last.dur_ms


def judge(
    sample: list[Feature],
    *,
    typist_name: str,
    target: Player,
    mode: Mode,
    phrase: str,
    run_duration_ms: float,
) -> Verdict:
    result = score_sample(sample, target.profile, phrase=phrase, threshold=target.threshold)
    distance = result.score
    ratio = distance / target.threshold if distance is not None else None

    if distance is None:
        return Verdict(
            "Too messy",
            "Too many wrong keys broke up the rhythm. Try the line again.",
            counted=False,
            passed=None,
            distance=None,
            ratio=None,
        )

    if mode == "self":
        if distance <= target.threshold:
            return Verdict(
                "That's you",
                "This line sits inside your own rhythm range.",
                counted=True,
                passed=True,
                distance=distance,
                ratio=ratio,
            )
        return Verdict(
            "Who are you?",
            "It didn't recognize its own typist. That's a false rejection.",
            counted=True,
            passed=False,
            distance=distance,
            ratio=ratio,
        )

    if mode == "disguise":
        usual = usual_duration_ms(target)
        pace_ratio = run_duration_ms / usual if usual else 1.0
        pace_ok = (1 - DISGUISE_PACE_TOLERANCE) <= pace_ratio <= (1 + DISGUISE_PACE_TOLERANCE)
        if not pace_ok:
            word = "Too fast" if pace_ratio < 1 else "Too slow"
            pct = abs(round((pace_ratio - 1) * 100))
            return Verdict(
                word,
                f"Your pace was {pct}% off. Disguises must stay within 15% of your usual pace.",
                counted=False,
                passed=None,
                distance=distance,
                ratio=ratio,
            )
        if distance > target.threshold:
            return Verdict(
                "Disguised!",
                "You kept your pace and still fooled it.",
                counted=True,
                passed=False,
                distance=distance,
                ratio=ratio,
            )
        return Verdict(
            "Still you",
            "It saw through the disguise. Try changing which keys you linger on.",
            counted=True,
            passed=True,
            distance=distance,
            ratio=ratio,
        )

    if mode == "replay":
        if distance <= target.threshold:
            return Verdict(
                "Replay wins",
                "A recording of real timing passes, because the rhythm really is "
                "theirs. That's why typing rhythm can't be the only thing "
                "protecting a login.",
                counted=True,
                passed=True,
                distance=distance,
                ratio=ratio,
            )
        return Verdict(
            "Replay failed",
            "This replay fell outside the limit.",
            counted=True,
            passed=False,
            distance=distance,
            ratio=ratio,
        )

    # mode == "attack"
    if distance <= target.threshold:
        return Verdict(
            "Fooled it!",
            f"{typist_name} passed as {target.name}. That's a false acceptance.",
            counted=True,
            passed=True,
            distance=distance,
            ratio=ratio,
        )
    return Verdict(
        "Caught!",
        f"It could tell {typist_name} isn't {target.name}.",
        counted=True,
        passed=False,
        distance=distance,
        ratio=ratio,
    )
