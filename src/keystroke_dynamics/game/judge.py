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
#: even happens -- matches the approved mockup's rule exactly. Also
#: the "right speed" band _clue() uses below, so the two never
#: disagree about what counts as fast or slow.
DISGUISE_PACE_TOLERANCE = 0.15


def _clue(*, distance: float, threshold: float, pace: float) -> str:
    """One-line, honest diagnosis of why a result landed where it
    did -- design/typing-twin-touch.html's own result screen shows
    this alongside pace, per PARTY_LAUNCH_PLAN.md section 8. Derived
    only from the real numbers, never from which mode this is or
    which side a given outcome favors, so it can never claim a good
    fit on a result the distance itself contradicts (the plan's "never
    say everything fits on a failed attempt").

    This game has no touch-position ("place") dimension -- a physical
    keyboard has no tap coordinates (core/features.py extracts only
    hold and flight timings) -- so unlike the touch mockup's three-way
    clue, rhythm is the only thing besides pace worth naming here.
    """
    fast = pace < 1 - DISGUISE_PACE_TOLERANCE
    slow = pace > 1 + DISGUISE_PACE_TOLERANCE
    off = distance > threshold
    if not fast and not slow:
        return "Right speed, wrong rhythm" if off else "Right speed, and the rhythm fits"
    speed = "Too fast" if fast else "Too slow"
    return f"{speed}, and the rhythm is off too" if off else f"{speed}, but the rhythm fits"


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
    #: This attempt's duration over the target's own usual duration
    #: for the line, where 1.0 is the same pace. None exactly when
    #: distance is None (see _clue's docstring -- nothing scoreable to
    #: show pace alongside). This is the UI's own display rule, not
    #: shared with game/scores's pace column -- see pace_ratio() below.
    pace: float | None
    #: One-line diagnosis from _clue(), or None alongside distance.
    clue: str | None
    #: How many features were actually compared -- game/scoring.py's
    #: ScoreResult.compared_features, surfaced here for
    #: PARTY_LAUNCH_PLAN.md section 10's score_attempts.compared_features.
    #: Meaningful even when distance is None (it's exactly why: fewer
    #: than game/scoring.py's own minimum).
    compared_features: int


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


def pace_ratio(run_duration_ms: float, target: Player) -> float | None:
    """This attempt's duration over target's own usual duration, or
    None if the target has no notes to compare against (shouldn't
    normally happen).

    Used directly by game/scores's own pace column, which -- unlike
    Verdict.pace above -- is recorded even for an attempt whose
    distance couldn't be scored: pace is independently useful research
    data (e.g. pace-bucketed false-accept/-reject rates,
    PARTY_LAUNCH_PLAN.md section 10's own analysis requirements) that
    has nothing to do with whether the rhythm itself was usable.
    """
    usual = usual_duration_ms(target)
    return run_duration_ms / usual if usual else None


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

    # Every mode's result shows pace and a clue alongside the score
    # (PARTY_LAUNCH_PLAN.md section 8) -- computed once here, not
    # reconstructed per mode. A None raw pace (target has no notes)
    # defaults to 1.0 ("on pace") rather than leaving it undefined,
    # matching the disguise gate's own long-standing fallback below;
    # it's never shown either way (Verdict.pace is None alongside
    # distance=None, the only case left unhandled here).
    raw_pace = pace_ratio(run_duration_ms, target)
    pace = raw_pace if raw_pace is not None else 1.0

    if distance is None:
        return Verdict(
            "Too messy",
            "Too many wrong keys broke up the rhythm. Try the line again.",
            counted=False,
            passed=None,
            distance=None,
            ratio=None,
            pace=None,
            clue=None,
            compared_features=result.compared_features,
        )
    clue = _clue(distance=distance, threshold=target.threshold, pace=pace)

    if mode == "self":
        if distance <= target.threshold:
            return Verdict(
                "That's you",
                "This line sits inside your own rhythm range.",
                counted=True,
                passed=True,
                distance=distance,
                ratio=ratio,
                pace=pace,
                clue=clue,
                compared_features=result.compared_features,
            )
        return Verdict(
            "Who are you?",
            "It didn't recognize its own typist. That's a false rejection.",
            counted=True,
            passed=False,
            distance=distance,
            ratio=ratio,
            pace=pace,
            clue=clue,
            compared_features=result.compared_features,
        )

    if mode == "disguise":
        pace_ok = (1 - DISGUISE_PACE_TOLERANCE) <= pace <= (1 + DISGUISE_PACE_TOLERANCE)
        if not pace_ok:
            word = "Too fast" if pace < 1 else "Too slow"
            pct = abs(round((pace - 1) * 100))
            return Verdict(
                word,
                f"Your pace was {pct}% off. Disguises must stay within 15% of your usual pace.",
                counted=False,
                passed=None,
                distance=distance,
                ratio=ratio,
                pace=pace,
                clue=clue,
                compared_features=result.compared_features,
            )
        if distance > target.threshold:
            return Verdict(
                "Disguised!",
                "You kept your pace and still fooled it.",
                counted=True,
                passed=False,
                distance=distance,
                ratio=ratio,
                pace=pace,
                clue=clue,
                compared_features=result.compared_features,
            )
        return Verdict(
            "Still you",
            "It saw through the disguise. Try changing which keys you linger on.",
            counted=True,
            passed=True,
            distance=distance,
            ratio=ratio,
            pace=pace,
            clue=clue,
            compared_features=result.compared_features,
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
                pace=pace,
                clue=clue,
                compared_features=result.compared_features,
            )
        return Verdict(
            "Replay failed",
            "This replay fell outside the limit.",
            counted=True,
            passed=False,
            distance=distance,
            ratio=ratio,
            pace=pace,
            clue=clue,
            compared_features=result.compared_features,
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
            pace=pace,
            clue=clue,
            compared_features=result.compared_features,
        )
    return Verdict(
        "Caught!",
        f"It could tell {typist_name} isn't {target.name}.",
        counted=True,
        passed=False,
        distance=distance,
        ratio=ratio,
        pace=pace,
        clue=clue,
        compared_features=result.compared_features,
    )
