"""Replays the CMU Keystroke Dynamics Benchmark Data Set (Killourhy &
Maxion, 2009) at the party game's size, to compare rules for the
per-player limit (game/scoring.py's calibrate_threshold).

Where evaluation/run_benchmark.py trains on 200 repetitions with
core/scoring.py's defaults, this trains the way the game enrolls: one
warm-up repetition is thrown away, the next 4 build the profile, and
the limit is calibrated from those same 4 lines. Profiles and scores
come from game/scoring.py's own functions and constants -- nothing
here is a second copy of the game's scoring -- and so does the limit
of the rule the game uses now (game_limit).

The comparison starts from the game's rule under scoring version 1
(upper clamp 3.5, V1_MAX_THRESHOLD), which is what was live when it
was run. Its outcome was lowering that clamp to 2.0, scoring version
2. The version 1 rule stays the baseline here so the results keep
showing what the change was chosen against.

For each target subject:
  - Train: repetitions 2-5 (repetition 1 is the warm-up).
  - Genuine attempts: that subject's later repetitions, reported
    twice -- the rest of the first session (6-50), which is the
    closest thing in this data to a game played in one sitting, and
    every later repetition (6-400), which adds 7 more sessions on
    other days.
  - Impostor attempts: the first 5 repetitions of each other
    subject, as run_benchmark.py does.

Tuned values (a multiplier, a fixed limit, a blend weight) are chosen
on one half of the subjects and every rule is then reported on the
other half, with impostors drawn from that same half only. The split
is a seeded shuffle (SEED); nothing else here is random. Each tuned
rule is tuned twice (tune_matched, tune_balanced), because one
objective alone would either hide how strict a rule can get or
compare rules at different false-rejection rates.

NOT the game's accuracy. This is one password typed by people who
were not trying to imitate each other, on one lab keyboard -- see
"What these numbers are not" in evaluation/game_size_results.md,
which this script writes.

See evaluation/README.md to download the dataset first. Run:
    uv run python -m evaluation.game_size_benchmark
"""

from __future__ import annotations

import random
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from evaluation.run_benchmark import IMPOSTOR_REPS_PER_SUBJECT, load_rows, row_to_features
from keystroke_dynamics.core.features import Feature, FeatureKey
from keystroke_dynamics.core.stats import RunningStats
from keystroke_dynamics.game.scoring import (
    GAME_MAX_THRESHOLD,
    GAME_MIN_THRESHOLD,
    GAME_THRESHOLD_MULTIPLIER,
    build_profile,
    calibrate_threshold,
    line_feature_count,
    score_sample,
)

RESULTS_MD_PATH = Path(__file__).parent / "game_size_results.md"

#: Seeds the one random step: which subjects tune and which report.
SEED = 2009

WARMUP_REPS = 1
TRAIN_REPS = 4
#: Each subject's first session is repetitions 1-50.
FIRST_SESSION_REPS = 50

#: game/scoring.py sizes min_compared_features from the line's text.
#: One repetition of `.tie5Roanl` + Return is 11 key events, all
#: distinct, so any 11 distinct characters stand in for it: 11 holds
#: + 10 flights = the 21 features run_benchmark.row_to_features
#: produces.
CMU_PHRASE = ".tie5Roanl\n"
assert line_feature_count(CMU_PHRASE) == 21

#: The game's upper clamp under scoring version 1, the baseline every
#: rule here is compared with. game/scoring.py's GAME_MAX_THRESHOLD
#: has since been lowered (see the module docstring).
V1_MAX_THRESHOLD = 3.5
assert GAME_MAX_THRESHOLD < V1_MAX_THRESHOLD

#: Lower caps tried besides the one the game now uses
#: (GAME_MAX_THRESHOLD, which gets its own row from game_limit).
LOWER_CAPS = [3.0, 2.5]
MEDIAN_MULTIPLIER_GRID = [round(1.0 + 0.1 * i, 1) for i in range(31)]  # 1.0 .. 4.0
FIXED_LIMIT_GRID = [round(1.0 + 0.1 * i, 1) for i in range(31)]  # 1.0 .. 4.0
BLEND_WEIGHT_GRID = [0.25, 0.5, 0.75, 1.0]

Profile = dict[FeatureKey, RunningStats]
Line = list[Feature]


def clamp_limit(raw: float, upper: float = V1_MAX_THRESHOLD) -> float:
    return max(GAME_MIN_THRESHOLD, min(upper, raw))


def split_subjects(subjects: Sequence[str], seed: int = SEED) -> tuple[list[str], list[str]]:
    """(tuning half, report half): a seeded shuffle of the sorted
    subject ids, cut in the middle. Disjoint, and together every
    subject."""
    shuffled = sorted(subjects)
    random.Random(seed).shuffle(shuffled)
    half = len(shuffled) // 2
    return sorted(shuffled[:half]), sorted(shuffled[half:])


def training_lines(lines: list[Line]) -> list[Line]:
    return lines[WARMUP_REPS : WARMUP_REPS + TRAIN_REPS]


def average_spreads(training_by_subject: dict[str, list[Line]]) -> dict[FeatureKey, float]:
    """Per feature, the mean across subjects of that subject's own
    standard deviation over their training lines -- "the average
    spread across typists" that blend_profile pulls toward."""
    per_key: dict[FeatureKey, list[float]] = {}
    for lines in training_by_subject.values():
        for key, stats in build_profile(lines).items():
            if stats.std is not None:
                per_key.setdefault(key, []).append(stats.std)
    return {key: statistics.mean(stds) for key, stds in per_key.items()}


def blend_profile(profile: Profile, spreads: dict[FeatureKey, float], weight: float) -> Profile:
    """Each feature's standard deviation moved `weight` of the way
    from the typist's own to the average across typists:
    (1 - weight) * own + weight * average. Means and counts are
    untouched, so game/scoring.py's own floors and minimum counts
    still apply on top when the result is scored."""
    blended: Profile = {}
    for key, stats in profile.items():
        own = stats.std
        if own is None or key not in spreads:
            blended[key] = stats
            continue
        std = (1.0 - weight) * own + weight * spreads[key]
        blended[key] = RunningStats(
            count=stats.count, mean=stats.mean, m2=std * std * (stats.count - 1)
        )
    return blended


def blender(spreads: dict[FeatureKey, float], weight: float) -> Callable[[Profile], Profile]:
    return lambda profile: blend_profile(profile, spreads, weight)


def score(sample: Line, profile: Profile) -> float:
    """game/scoring.py's score for one line. The limit passed in is
    irrelevant to .score; decisions are made in evaluate() as
    score <= limit, the same comparison scaled_manhattan_score makes
    (checked in tests/evaluation/test_game_size_benchmark.py)."""
    result = score_sample(sample, profile, phrase=CMU_PHRASE, threshold=GAME_MIN_THRESHOLD)
    # Every CMU repetition has all 21 features, so nothing here can
    # come back INSUFFICIENT_DATA; if it does, the replay is wrong.
    assert result.score is not None
    return result.score


def held_out_scores(
    lines: list[Line], transform: Callable[[Profile], Profile] | None = None
) -> list[float]:
    """The scores calibrate_threshold takes its maximum of: each
    training line against a profile of the others. calibrate_threshold
    doesn't return them, and the alternative rules need the median
    and blended profiles, so the loop is repeated here around the
    game's own build_profile and score_sample -- and checked against
    calibrate_threshold in the tests."""
    scores = []
    for i, line in enumerate(lines):
        profile = build_profile([other for j, other in enumerate(lines) if j != i])
        scores.append(score(line, transform(profile) if transform else profile))
    return scores


@dataclass(frozen=True)
class TargetScores:
    """Everything a rule needs about one target, for one way of
    building profiles (the game's, or blended at one weight)."""

    training: list[Line]
    held_out: list[float]
    genuine_first_session: list[float]
    genuine_later_sessions: list[float]
    #: impostor subject -> that subject's scores against this target
    impostor: dict[str, list[float]]


def score_target(
    subject: str,
    lines_by_subject: dict[str, list[Line]],
    transform: Callable[[Profile], Profile] | None = None,
) -> TargetScores:
    lines = lines_by_subject[subject]
    training = training_lines(lines)
    profile = build_profile(training)
    if transform:
        profile = transform(profile)
    after_training = WARMUP_REPS + TRAIN_REPS
    return TargetScores(
        training=training,
        held_out=held_out_scores(training, transform),
        genuine_first_session=[
            score(line, profile) for line in lines[after_training:FIRST_SESSION_REPS]
        ],
        genuine_later_sessions=[score(line, profile) for line in lines[FIRST_SESSION_REPS:]],
        impostor={
            other: [score(line, profile) for line in other_lines[:IMPOSTOR_REPS_PER_SUBJECT]]
            for other, other_lines in lines_by_subject.items()
            if other != subject
        },
    )


# ---------- limit rules ----------


def version_1_limit(t: TargetScores) -> float:
    """The rule under scoring version 1: highest held-out score times
    GAME_THRESHOLD_MULTIPLIER, clamped to [GAME_MIN_THRESHOLD,
    V1_MAX_THRESHOLD]. The game's formula, written out because
    calibrate_threshold now clamps lower -- and because blended
    held-out scores are something calibrate_threshold can't produce."""
    return clamp_limit(max(t.held_out) * GAME_THRESHOLD_MULTIPLIER)


def game_limit(t: TargetScores) -> float:
    """The rule the game uses now, from the game's own function: the
    version 1 rule with the upper clamp at GAME_MAX_THRESHOLD."""
    return calibrate_threshold(t.training, phrase=CMU_PHRASE)


def capped_limit(cap: float) -> Callable[[TargetScores], float]:
    """The version 1 rule with a lower upper clamp. Capping its result
    is the same as clamping to [GAME_MIN_THRESHOLD, cap]."""
    return lambda t: min(cap, version_1_limit(t))


def median_limit(multiplier: float) -> Callable[[TargetScores], float]:
    """Median held-out score (of 4, so the mean of the middle two)
    times a multiplier, inside the version 1 clamps."""
    return lambda t: clamp_limit(statistics.median(t.held_out) * multiplier)


def fixed_limit(limit: float) -> Callable[[TargetScores], float]:
    return lambda t: limit


def drop_worst_limit(t: TargetScores) -> float:
    """Removes the training line with the highest held-out score,
    then applies the version 1 rule to the 3 that remain. Only the
    limit changes: the profile attempts are scored against still has
    all 4 lines."""
    worst = max(range(len(t.held_out)), key=t.held_out.__getitem__)
    kept = [line for i, line in enumerate(t.training) if i != worst]
    return clamp_limit(max(held_out_scores(kept)) * GAME_THRESHOLD_MULTIPLIER)


# ---------- evaluation ----------


def _mean(values: Sequence[float]) -> float:
    return statistics.mean(values)


def _standard_error(values: Sequence[float]) -> float:
    return statistics.stdev(values) / len(values) ** 0.5 if len(values) > 1 else 0.0


@dataclass(frozen=True)
class RuleResult:
    """One rule on one set of targets. Each list has one entry per
    target, in the same target order for every rule, so two results
    over the same targets can be compared target by target. The
    reported rate is the mean over targets of each target's own rate,
    as run_benchmark.py averages per-subject EERs."""

    limits: list[float]
    fars: list[float]
    frrs_first_session: list[float]
    frrs_all_later: list[float]

    @property
    def far(self) -> float:
        return _mean(self.fars)

    @property
    def frr_first_session(self) -> float:
        return _mean(self.frrs_first_session)

    @property
    def frr_all_later(self) -> float:
        return _mean(self.frrs_all_later)

    @property
    def share_at_lower_clamp(self) -> float:
        return _mean([v <= GAME_MIN_THRESHOLD for v in self.limits])

    @property
    def share_at_upper_clamp(self) -> float:
        return _mean([v >= V1_MAX_THRESHOLD for v in self.limits])


def evaluate(
    scores: dict[str, TargetScores],
    targets: Sequence[str],
    impostors: Sequence[str],
    limit_rule: Callable[[TargetScores], float],
) -> RuleResult:
    """Applies limit_rule to each target, then accepts every attempt
    whose score is at or under that target's limit."""
    limits, fars, frrs_first, frrs_all = [], [], [], []
    for subject in targets:
        t = scores[subject]
        limit = limit_rule(t)
        limits.append(limit)
        impostor_scores = [s for other in impostors if other != subject for s in t.impostor[other]]
        fars.append(_mean([s <= limit for s in impostor_scores]))
        frrs_first.append(_mean([s > limit for s in t.genuine_first_session]))
        all_later = t.genuine_first_session + t.genuine_later_sessions
        frrs_all.append(_mean([s > limit for s in all_later]))
    return RuleResult(limits, fars, frrs_first, frrs_all)


def tune_matched[T](
    grid: Sequence[T], result_for: Callable[[T], RuleResult], frr_ceiling: float
) -> T:
    """The grid value with the lowest false acceptance among those
    whose first-session false rejection is no higher than
    frr_ceiling (the version 1 rule's, on the same tuning subjects) --
    so the tuned rule answers "at the false rejection players get
    today, does this rule let fewer impostors through?". If no value
    meets the ceiling, the one with the lowest false rejection. Ties
    go to the earliest grid value.

    First-session false rejection, not all later repetitions: a game
    is one sitting, and a limit tuned to accept the same person days
    later would be far looser than the game needs."""
    results = [(value, result_for(value)) for value in grid]
    meeting = [(value, r) for value, r in results if r.frr_first_session <= frr_ceiling]
    if meeting:
        return min(meeting, key=lambda pair: pair[1].far)[0]
    return min(results, key=lambda pair: pair[1].frr_first_session)[0]


def tune_balanced[T](grid: Sequence[T], result_for: Callable[[T], RuleResult]) -> T:
    """The grid value with the lowest false acceptance plus
    first-session false rejection, weighted equally; the earliest
    such value on a tie."""

    def objective(value: T) -> float:
        result = result_for(value)
        return result.far + result.frr_first_session

    return min(grid, key=objective)


@dataclass(frozen=True)
class Rule:
    name: str
    #: Which profiles the rule scores against: the game's own, or
    #: blended ones.
    scores: dict[str, TargetScores]
    limit_rule: Callable[[TargetScores], float]


@dataclass(frozen=True)
class Results:
    subjects: list[str]
    tuning_half: list[str]
    report_half: list[str]
    #: The game's profiles and scores, every subject.
    base: dict[str, TargetScores]
    #: The version 1 rule on all subjects, impostors from all others.
    baseline_all: RuleResult
    rules: list[Rule]
    on_tuning_half: dict[str, RuleResult]
    on_report_half: dict[str, RuleResult]


BASELINE = f"version 1 (cap {V1_MAX_THRESHOLD})"
ADOPTED = f"cap {GAME_MAX_THRESHOLD} (the game's rule now)"


def run(lines_by_subject: dict[str, list[Line]]) -> Results:
    subjects = sorted(lines_by_subject)
    tuning_half, report_half = split_subjects(subjects)
    base = {s: score_target(s, lines_by_subject) for s in subjects}

    def on_tuning(
        limit_rule: Callable[[TargetScores], float],
        scores: dict[str, TargetScores] = base,
    ) -> RuleResult:
        return evaluate(scores, tuning_half, tuning_half, limit_rule)

    frr_ceiling = on_tuning(version_1_limit).frr_first_session

    # Average spreads come from the tuning half only, so the report
    # half's own typists never shape the profiles they are scored on.
    spreads = average_spreads({s: training_lines(lines_by_subject[s]) for s in tuning_half})
    blended = {
        weight: {s: score_target(s, lines_by_subject, blender(spreads, weight)) for s in subjects}
        for weight in BLEND_WEIGHT_GRID
    }

    def tuned[T](grid: Sequence[T], result_for: Callable[[T], RuleResult]) -> list[tuple[T, str]]:
        """(value, how it was chosen) -- one entry when both ways of
        tuning pick the same value, else one for each."""
        matched = tune_matched(grid, result_for, frr_ceiling)
        balanced = tune_balanced(grid, result_for)
        if matched == balanced:
            return [(matched, "matched and balanced")]
        return [(matched, "matched"), (balanced, "balanced")]

    rules = [
        Rule(BASELINE, base, version_1_limit),
        *(
            Rule(f"median x {m} ({how})", base, median_limit(m))
            for m, how in tuned(MEDIAN_MULTIPLIER_GRID, lambda m: on_tuning(median_limit(m)))
        ),
        *(Rule(f"cap {cap}", base, capped_limit(cap)) for cap in LOWER_CAPS),
        Rule(ADOPTED, base, game_limit),
        *(
            Rule(f"fixed {v} ({how})", base, fixed_limit(v))
            for v, how in tuned(FIXED_LIMIT_GRID, lambda v: on_tuning(fixed_limit(v)))
        ),
        *(
            Rule(f"version 1, spreads blended {w} ({how})", blended[w], version_1_limit)
            for w, how in tuned(BLEND_WEIGHT_GRID, lambda w: on_tuning(version_1_limit, blended[w]))
        ),
        Rule("version 1, worst line dropped", base, drop_worst_limit),
    ]
    return Results(
        subjects=subjects,
        tuning_half=tuning_half,
        report_half=report_half,
        base=base,
        baseline_all=evaluate(base, subjects, subjects, version_1_limit),
        rules=rules,
        on_tuning_half={r.name: on_tuning(r.limit_rule, r.scores) for r in rules},
        on_report_half={
            r.name: evaluate(r.scores, report_half, report_half, r.limit_rule) for r in rules
        },
    )


# ---------- results file ----------

PERCENTILES = [10, 25, 50, 75, 90]


def _percentiles(values: Sequence[float]) -> list[float]:
    return [float(v) for v in np.percentile(np.asarray(values, dtype=float), PERCENTILES)]


def _pct(rate: float) -> str:
    return f"{rate:.1%}"


def _pct_se(values: Sequence[float]) -> str:
    return f"{_mean(values):.1%} ± {_standard_error(values) * 100:.1f}"


def _points(values: Sequence[float]) -> str:
    """A mean difference in percentage points, with its standard
    error across targets."""
    return f"{_mean(values) * 100:+.1f} ± {_standard_error(values) * 100:.1f}"


def _rule_rows(results: dict[str, RuleResult]) -> list[str]:
    rows = [
        "| Rule | False acceptance | False rejection, same session "
        "| False rejection, all later | Median limit "
        f"| At {GAME_MIN_THRESHOLD} | At {V1_MAX_THRESHOLD} |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, r in results.items():
        rows.append(
            f"| {name} | {_pct_se(r.fars)} | {_pct_se(r.frrs_first_session)} "
            f"| {_pct_se(r.frrs_all_later)} | {statistics.median(r.limits):.2f} "
            f"| {_pct(r.share_at_lower_clamp)} | {_pct(r.share_at_upper_clamp)} |"
        )
    return rows


def _difference_rows(results: dict[str, RuleResult]) -> list[str]:
    baseline = results[BASELINE]
    rows = [
        "| Rule | False acceptance, change | False rejection (same session), change |",
        "|---|---|---|",
    ]
    for name, r in results.items():
        if name == BASELINE:
            continue
        far_diffs = [a - b for a, b in zip(r.fars, baseline.fars, strict=True)]
        frr_diffs = [
            a - b for a, b in zip(r.frrs_first_session, baseline.frrs_first_session, strict=True)
        ]
        rows.append(f"| {name} | {_points(far_diffs)} | {_points(frr_diffs)} |")
    return rows


#: A judgement about one run, not something computed: written for the
#: tables this script produces from the dataset pinned in
#: evaluation/README.md with SEED = 2009, and quoting their numbers.
#: If a change to this script or to game/scoring.py moves any number
#: in those tables, reread and rewrite this before committing the
#: regenerated results.
RECOMMENDATION = """\
## Recommendation

**Keep the version 1 rule and lower its upper clamp from 3.5 to 2.0.**

**Adopted.** `GAME_MAX_THRESHOLD` in `game/scoring.py` is now 2.0 and
`SCORING_VERSION` is "2". The cap 2.0 row above is that rule, computed by the
game's own `calibrate_threshold`.

On the report half that takes false acceptance from 39.8% to 31.8% (-8.0 ± 2.4
points, target by target) and same-session false rejection from 8.9% to 9.8%
(+0.9 ± 0.3 points).

Why this rule and not the others:

- **It buys the most false acceptance per point of false rejection.** The matched
  median rule cuts false acceptance further (-12.8 ± 4.1) but costs +3.5 ± 1.9
  points of false rejection: more than twice the price per point. It also did not
  hold the false rejection it was tuned to match (6.3% on the tuning half, 12.4% on
  the report half).
- **Its one number can be checked against real scores.** A cap is in score units,
  and `evaluation/analyze_scores.py` already shows what a limit of 2.0 does to real
  self and attack attempts. A multiplier or a blend weight tuned on a password says
  little about the game's lines, where scores are on a different footing.
- **The balanced rules are too strict for a party game.** They reach 11-15% false
  acceptance only by rejecting the real player 21-22% of the time in the same
  sitting.
- **Caps of 3.0 and 2.5 change almost nothing here** (-0.5 ± 0.5 and -1.4 ± 0.9
  points of false acceptance): before clamping, only 6 and 11 of 51 limits are that
  high.
- **Dropping the worst line** lands near the 2.0 cap on false acceptance
  (-6.6 ± 5.7) for more false rejection (+2.0 ± 1.9), and neither change is
  distinguishable from none.
- **A fixed limit of 1.9** is lower on both errors, but not distinguishably
  (-4.8 ± 4.1 and -4.4 ± 3.2). What it does show is that calibrating per player from
  4 lines does no better here than not calibrating at all: 4 lines say little
  about a player's own spread, which is why the highest of 4 held-out scores is a
  noisy thing to scale a limit by, and why capping it costs so little.
- **Blending spreads** is the only rule lower on both errors with a false
  acceptance change above twice its ± (-6.2 ± 2.8 and -2.5 ± 1.8). It is not
  recommended from this replay because it works largely by shrinking scores until
  the 1.3 floor sets the limit (46% of report-half targets), it changes scores as
  well as limits -- so stored scores and the on-screen clues would shift -- and the
  game would need an average spread for every key and key pair of its own lines,
  which this password cannot supply. It is worth a separate look.

The trade-off: with a cap of 2.0, about half the targets here (25 of 51) get a
limit set by the cap instead of by their own typing. The rule moves most of the way
to one limit for everyone, with calibration able only to tighten it. Players whose
typing really does vary a lot will fail as themselves more often; in exchange,
nobody is given a limit that most attackers pass. It does nothing about the larger
problem in the score table above -- genuine and impostor scores overlap at 4
training lines -- which no limit rule fixes.

What this replay could not settle, and what to watch in real scores now:

- Only 1 of 51 limits reaches 3.5 here, so the replay barely exercises what the
  real scores show (attacks passing at limits of 3.0 and above). How much a cap
  helps the game depends on how many real players are given a limit above it.
  `evaluation/analyze_scores.py` now prints that distribution, and the real pass
  rate at each attempt's own limit.
- The real cost is in the real self attempts. For `scoring_version` 1 rows, the
  false rejection at limit 2.0 in `analyze_scores.py`'s table of hypothetical
  limits is a lower bound on what the cap does (a capped limit is never above
  2.0), and the false acceptance at 2.0 is an upper bound. For `scoring_version` 2
  rows, the real pass rate table shows it directly. If real players fail as
  themselves more than the game should accept, 2.5 is the fallback: nearly free
  here, and worth as much as the number of real limits above 2.5.
"""


def write_results_md(results: Results) -> None:
    n = len(results.subjects)
    n_tune, n_report = len(results.tuning_half), len(results.report_half)
    baseline_all = results.baseline_all
    report = results.on_report_half
    raw = [max(results.base[s].held_out) * GAME_THRESHOLD_MULTIPLIER for s in results.subjects]
    below = sum(v <= GAME_MIN_THRESHOLD for v in raw)
    above = sum(v >= V1_MAX_THRESHOLD for v in raw)
    over_30, over_25, over_20 = (sum(v > cap for v in raw) for cap in (3.0, 2.5, 2.0))

    same_session_label = (
        f"Genuine, same session (repetitions {WARMUP_REPS + TRAIN_REPS + 1}-{FIRST_SESSION_REPS})"
    )
    score_groups = {
        "Held-out training lines (what calibration sees)": [
            s for t in results.base.values() for s in t.held_out
        ],
        same_session_label: [s for t in results.base.values() for s in t.genuine_first_session],
        f"Genuine, later sessions (repetitions {FIRST_SESSION_REPS + 1}-400)": [
            s for t in results.base.values() for s in t.genuine_later_sessions
        ],
        "Impostor": [
            s for t in results.base.values() for scores in t.impostor.values() for s in scores
        ],
    }
    percentile_header = " | ".join(f"p{p}" for p in PERCENTILES)

    lines = [
        "# Limit rules at the game's size, on the CMU data",
        "",
        "Written by `evaluation/game_size_benchmark.py`. It replays the CMU Keystroke",
        "Dynamics Benchmark Data Set the way the party game enrolls a player -- 1 warm-up",
        f"line thrown away, {TRAIN_REPS} lines of training, a limit calibrated from those same",
        f"{TRAIN_REPS} lines -- and compares rules for that limit.",
        "",
        "## What these numbers are not",
        "",
        "**None of this is the game's accuracy, or an estimate of it.** The CMU data is one",
        "10-character password typed by 51 people in a lab. The game is different in ways",
        "that move every rate below:",
        "",
        '- **Impostors here are not trying.** Each "impostor" simply typed the same password',
        "  in their own rhythm. A player attacking in the game has seen the target's rhythm",
        "  and is imitating it, so false acceptance in the game should be expected to be",
        "  higher than here at the same limit.",
        "- **Genuine typists here are still learning.** `.tie5Roanl` was new to every",
        "  subject, and repetitions 2-5 are the very start of learning it. An English",
        "  sentence is typed with settled habits. False rejection in the game should be",
        "  expected to be lower than here, and the later-session column (other days) has no",
        "  counterpart in a game played in one sitting.",
        "- **The line is different.** 21 features here, each seen once per repetition. A",
        "  game line has more features, and repeated letters give some of them several",
        "  values per line. The scores, and so the limits a rule hands out, are",
        "  on a different footing: do not read the distribution of limits below as the",
        "  game's. `evaluation/analyze_scores.py` prints the real one.",
        "- **One keyboard, one device type.** No phones, no second keyboard.",
        "",
        "What the replay can do is rank rules against each other under one fixed set of",
        "conditions, and show where a rule's cost falls. Read it as that.",
        "",
        "## Method",
        "",
        f"For each of the {n} subjects, using `game/scoring.py`'s own `build_profile`,",
        "`score_sample` and `calibrate_threshold` with the game's constants:",
        "",
        f"- **Train**: repetitions 2-{WARMUP_REPS + TRAIN_REPS}. Repetition 1 is the warm-up",
        "  and is not used.",
        "- **Genuine attempts**: that subject's later repetitions, reported two ways. *Same",
        f"  session* is repetitions {WARMUP_REPS + TRAIN_REPS + 1}-{FIRST_SESSION_REPS}, the rest"
        " of the sitting the training came from,",
        "  and the closer of the two to a game. *All later* is repetitions "
        f"{WARMUP_REPS + TRAIN_REPS + 1}-400, which",
        "  adds 7 sessions on other days.",
        f"- **Impostor attempts**: the first {IMPOSTOR_REPS_PER_SUBJECT} repetitions of each"
        " other subject, as",
        "  `evaluation/run_benchmark.py` does.",
        "- An attempt is accepted when its score is at or under the target's limit.",
        "",
        "Rates are the mean over targets of each target's own rate. Where a table shows",
        "`±`, it is the standard error of that mean across targets, in percentage points.",
        "",
        "## The version 1 rule, all subjects",
        "",
        "Limit = highest held-out score x "
        f"{GAME_THRESHOLD_MULTIPLIER}, clamped to {GAME_MIN_THRESHOLD}-{V1_MAX_THRESHOLD}."
        f" {n} targets, {(n - 1) * IMPOSTOR_REPS_PER_SUBJECT}",
        "impostor attempts each.",
        "",
        "| | Rate |",
        "|---|---|",
        f"| False acceptance | {_pct_se(baseline_all.fars)} |",
        f"| False rejection, same session | {_pct_se(baseline_all.frrs_first_session)} |",
        f"| False rejection, all later | {_pct_se(baseline_all.frrs_all_later)} |",
        "",
        "### Calibrated limits",
        "",
        f"| | Min | {percentile_header} | Max |",
        "|---|---|---|---|---|---|---|---|",
        "| Limit given | "
        + " | ".join(
            f"{v:.2f}"
            for v in [
                min(baseline_all.limits),
                *_percentiles(baseline_all.limits),
                max(baseline_all.limits),
            ]
        )
        + " |",
        "| Before clamping | "
        + " | ".join(f"{v:.2f}" for v in [min(raw), *_percentiles(raw), max(raw)])
        + " |",
        "",
        "### How often each clamp is reached",
        "",
        "| Clamp | Targets | Share |",
        "|---|---|---|",
        f"| Lower, {GAME_MIN_THRESHOLD} (raised to it) | {below} of {n} | {_pct(below / n)} |",
        f"| Upper, {V1_MAX_THRESHOLD} (cut down to it) | {above} of {n} | {_pct(above / n)} |",
        "",
        f"Before clamping, {over_30} of {n} limits are above 3.0, {over_25} above 2.5 and"
        f" {over_20} above 2.0 --",
        "the targets a lower cap would actually change.",
        "",
        "### Scores behind those rates",
        "",
        f"| Scores | n | {percentile_header} |",
        "|---|---|---|---|---|---|---|",
        *(
            f"| {label} | {len(values)} | "
            + " | ".join(f"{v:.2f}" for v in _percentiles(values))
            + " |"
            for label, values in score_groups.items()
        ),
        "",
        "The two populations overlap heavily at this size: the lowest-scoring quarter of",
        f"impostor attempts is under {_percentiles(score_groups['Impostor'])[1]:.2f}, and the"
        " highest-scoring tenth of same-session",
        f"genuine attempts is over {_percentiles(score_groups[same_session_label])[4]:.2f}."
        " No limit rule can separate what the",
        "scores don't; a rule can only choose where to cut.",
        "",
        "## Limit rules compared",
        "",
        f"The {n} subjects are split by a seeded shuffle (seed {SEED}) into a tuning half",
        f"({n_tune}) and a report half ({n_report}). Tuned values are chosen on the tuning half."
        " Every",
        "number in the first two tables is from the report half, with impostors drawn",
        f"from the report half only ({(n_report - 1) * IMPOSTOR_REPS_PER_SUBJECT} attempts per"
        " target).",
        "",
        "The rules:",
        "",
        f"- **version 1**: highest held-out score x {GAME_THRESHOLD_MULTIPLIER}, clamped to"
        f" {GAME_MIN_THRESHOLD}-{V1_MAX_THRESHOLD}. The game's rule when this comparison was run.",
        "- **median x m**: median held-out score (of 4, so the mean of the middle two) times",
        f"  m, inside the same {GAME_MIN_THRESHOLD}-{V1_MAX_THRESHOLD} clamps.",
        "- **cap c**: the version 1 rule with the upper clamp lowered to c. Nothing tuned.",
        f"  The {GAME_MAX_THRESHOLD} row is the rule the game uses now, computed by"
        " `calibrate_threshold` itself.",
        "- **fixed v**: the same limit v for every target; no calibration.",
        "- **version 1, spreads blended w**: before scoring, each feature's standard deviation",
        "  is replaced by (1 - w) x the typist's own + w x the average of that feature's",
        "  standard deviation across the tuning half's typists (each measured over their own",
        f"  {TRAIN_REPS} training lines). The same blend is applied inside calibration. The game's",
        "  spread floors still apply on top. The weight w is tuned.",
        "- **version 1, worst line dropped**: the training line with the highest held-out",
        "  score is removed, and the version 1 rule calibrates on the remaining 3. The profile",
        f"  attempts are scored against still uses all {TRAIN_REPS} lines. Nothing tuned.",
        "",
        "Tuned values are chosen two ways, because one alone would mislead:",
        "",
        "- **matched**: the lowest false acceptance among values whose same-session false",
        "  rejection on the tuning half is no higher than the version 1 rule's there",
        f"  ({_pct(results.on_tuning_half[BASELINE].frr_first_session)}). This asks whether a"
        " rule is *better* than version 1 at",
        "  the false rejection players already get.",
        "- **balanced**: the lowest false acceptance plus same-session false rejection.",
        "  This shows how strict a rule gets when both errors count equally.",
        "",
        "A rule has one row, marked *matched and balanced*, where both pick the same value.",
        "",
        f"### Report half ({n_report} targets)",
        "",
        *_rule_rows(report),
        "",
        "### Change from the version 1 rule, target by target (report half)",
        "",
        "Each rule's rate minus the version 1 rule's on the same target, averaged, in",
        "percentage points. A change smaller than about twice its `±` is not",
        "distinguishable from no change on this many targets.",
        "",
        *_difference_rows(report),
        "",
        f"### Tuning half ({n_tune} targets), where the tuned values were chosen",
        "",
        "For reference only: tuned rules look better here than they are.",
        "",
        *_rule_rows(results.on_tuning_half),
        "",
        *RECOMMENDATION.splitlines(),
        "",
        "## Reproduce",
        "",
        "```bash",
        "uv run python -m evaluation.game_size_benchmark",
        "```",
        "",
    ]
    RESULTS_MD_PATH.write_text("\n".join(lines))


def main() -> None:
    by_subject = load_rows()
    for subject, rows in by_subject.items():
        assert len(rows) == 400, f"{subject} has {len(rows)} rows, expected 400"
    lines_by_subject = {
        subject: [row_to_features(row) for row in rows] for subject, rows in by_subject.items()
    }
    results = run(lines_by_subject)
    write_results_md(results)
    print(f"Wrote {RESULTS_MD_PATH}")


if __name__ == "__main__":
    main()
