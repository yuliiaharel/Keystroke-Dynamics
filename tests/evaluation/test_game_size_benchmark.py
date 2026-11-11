"""evaluation/game_size_benchmark.py against small synthetic data --
the CMU dataset itself isn't committed (evaluation/README.md), so
nothing here needs it. What matters most is checked first: that the
benchmark's rules are built on the game's own calibrate_threshold, and
that its accept/reject decision is the game's own.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from evaluation import game_size_benchmark as bench
from evaluation.game_size_benchmark import (
    CMU_PHRASE,
    FIRST_SESSION_REPS,
    V1_MAX_THRESHOLD,
    RuleResult,
    TargetScores,
    average_spreads,
    blend_profile,
    capped_limit,
    drop_worst_limit,
    evaluate,
    fixed_limit,
    game_limit,
    held_out_scores,
    median_limit,
    score,
    score_target,
    split_subjects,
    training_lines,
    tune_balanced,
    tune_matched,
    version_1_limit,
)
from evaluation.run_benchmark import KEYS, flight_key, hold_key
from keystroke_dynamics.core.features import Feature
from keystroke_dynamics.core.scoring import Decision
from keystroke_dynamics.core.stats import RunningStats
from keystroke_dynamics.game.scoring import (
    GAME_MAX_THRESHOLD,
    GAME_MIN_THRESHOLD,
    build_profile,
    calibrate_threshold,
    score_sample,
)


def _line(rng: random.Random, hold_ms: float, flight_ms: float, jitter: float) -> list[Feature]:
    """One repetition in the shape run_benchmark.row_to_features
    gives: a hold per key and a flight per consecutive pair."""
    features = [Feature(hold_key(k), rng.gauss(hold_ms, hold_ms * jitter)) for k in KEYS]
    features += [
        Feature(flight_key(a, b), rng.gauss(flight_ms, flight_ms * jitter))
        for a, b in zip(KEYS, KEYS[1:], strict=False)
    ]
    return features


def _subjects(n: int, reps: int, seed: int = 7) -> dict[str, list[list[Feature]]]:
    """n typists with different paces and different steadiness."""
    rng = random.Random(seed)
    return {
        f"s{i:03d}": [
            _line(rng, hold_ms=70 + 12 * i, flight_ms=130 + 25 * i, jitter=0.05 + 0.04 * (i % 4))
            for _ in range(reps)
        ]
        for i in range(n)
    }


def _target(
    held_out: list[float],
    genuine_first: list[float] | None = None,
    genuine_later: list[float] | None = None,
    impostor: dict[str, list[float]] | None = None,
) -> TargetScores:
    return TargetScores(
        training=[],
        held_out=held_out,
        genuine_first_session=genuine_first or [],
        genuine_later_sessions=genuine_later or [],
        impostor=impostor or {},
    )


# ---------- it is the game's scoring, not a copy ----------


@pytest.mark.parametrize("seed", range(8))
def test_limits_are_the_games_calibrate_threshold(seed: int) -> None:
    lines = _subjects(8, 6, seed)
    for subject in lines:
        t = score_target(subject, lines)
        expected = calibrate_threshold(training_lines(lines[subject]), phrase=CMU_PHRASE)
        assert game_limit(t) == expected
        # The version 1 rule is the same formula with the old clamp:
        # it differs from the game's only where the game now caps.
        # So rules built on t.held_out start from the game's numbers.
        v1 = version_1_limit(t)
        assert min(GAME_MAX_THRESHOLD, v1) == pytest.approx(expected, abs=1e-12)
        assert v1 <= V1_MAX_THRESHOLD


def test_a_stumbled_line_separates_the_version_1_rule_from_the_games() -> None:
    # The seeds above never calibrate past the game's cap, so this is
    # the case where the two rules differ: one training line typed 3x
    # slower sends the version 1 limit above 2.0, and the game's own
    # function holds it there.
    lines = _subjects(1, 6)
    lines["s000"][2] = [Feature(f.key, f.value_ms * 3) for f in lines["s000"][2]]
    t = score_target("s000", lines)
    assert GAME_MAX_THRESHOLD < version_1_limit(t) <= V1_MAX_THRESHOLD
    assert game_limit(t) == GAME_MAX_THRESHOLD
    assert capped_limit(2.5)(t) == 2.5


def test_accepting_at_or_under_the_limit_is_the_games_decision() -> None:
    lines = _subjects(4, 12)
    profile = build_profile(training_lines(lines["s000"]))
    samples = [line for subject_lines in lines.values() for line in subject_lines]
    decisions = set()
    for limit in (1.3, 2.0, 3.5):
        for sample in samples:
            result = score_sample(sample, profile, phrase=CMU_PHRASE, threshold=limit)
            assert result.score == score(sample, profile)
            assert (score(sample, profile) <= limit) == (result.decision is Decision.MATCH)
            decisions.add(result.decision)
    # Both outcomes actually occurred, so the check above isn't vacuous.
    assert decisions == {Decision.MATCH, Decision.NO_MATCH}


# ---------- protocol ----------


def test_training_skips_the_warm_up_and_takes_the_next_four() -> None:
    lines = _subjects(1, 10)["s000"]
    assert training_lines(lines) == lines[1:5]


def test_genuine_attempts_are_only_repetitions_after_training() -> None:
    lines = _subjects(3, FIRST_SESSION_REPS + 10)
    t = score_target("s000", lines)
    profile = build_profile(lines["s000"][1:5])
    assert t.genuine_first_session == [
        score(line, profile) for line in lines["s000"][5:FIRST_SESSION_REPS]
    ]
    assert t.genuine_later_sessions == [
        score(line, profile) for line in lines["s000"][FIRST_SESSION_REPS:]
    ]


def test_impostors_are_the_first_five_repetitions_of_every_other_subject() -> None:
    lines = _subjects(3, 12)
    t = score_target("s000", lines)
    profile = build_profile(lines["s000"][1:5])
    assert set(t.impostor) == {"s001", "s002"}
    assert t.impostor["s001"] == [score(line, profile) for line in lines["s001"][:5]]


def test_split_is_seeded_disjoint_and_complete() -> None:
    subjects = [f"s{i:03d}" for i in range(51)]
    tuning, report = split_subjects(subjects)
    assert (len(tuning), len(report)) == (25, 26)
    assert set(tuning).isdisjoint(report)
    assert sorted(tuning + report) == subjects
    # Same seed and same subjects in any order: the same halves.
    assert split_subjects(list(reversed(subjects))) == (tuning, report)
    assert split_subjects(subjects, seed=1) != (tuning, report)


# ---------- limit rules ----------


@pytest.mark.parametrize(
    ("held_out", "multiplier", "expected"),
    [
        ([1.0, 1.2, 1.4, 9.0], 1.5, 1.3 * 1.5),  # median 1.3; the 9.0 is ignored
        ([0.2, 0.2, 0.2, 0.2], 1.5, GAME_MIN_THRESHOLD),  # clamped up
        ([5.0, 5.0, 5.0, 5.0], 1.5, V1_MAX_THRESHOLD),  # clamped down
    ],
)
def test_median_limit(held_out: list[float], multiplier: float, expected: float) -> None:
    assert median_limit(multiplier)(_target(held_out)) == pytest.approx(expected)


def test_fixed_limit_ignores_the_target() -> None:
    assert fixed_limit(1.9)(_target([0.1, 9.0])) == 1.9


@pytest.mark.parametrize("cap", [2.5, 3.0])
def test_capped_limit_only_lowers_limits_above_the_cap(cap: float) -> None:
    lines = _subjects(8, 6)
    for subject in lines:
        t = score_target(subject, lines)
        assert capped_limit(cap)(t) == min(cap, version_1_limit(t))


def test_drop_worst_applies_the_version_1_rule_to_the_three_best_lines() -> None:
    lines = _subjects(1, 6)["s000"]
    training = training_lines(lines)
    # Make the third training line a stumble: everything 3x slower.
    training[2] = [Feature(f.key, f.value_ms * 3) for f in training[2]]
    held_out = held_out_scores(training)
    assert max(range(4), key=held_out.__getitem__) == 2

    t = TargetScores(training, held_out, [], [], {})
    kept = [training[0], training[1], training[3]]
    assert drop_worst_limit(t) == version_1_limit(_target(held_out_scores(kept)))
    # Where the game's own function doesn't cap, the two agree.
    assert drop_worst_limit(t) < GAME_MAX_THRESHOLD
    assert drop_worst_limit(t) == pytest.approx(calibrate_threshold(kept, phrase=CMU_PHRASE))
    assert drop_worst_limit(t) < version_1_limit(t)


# ---------- blended spreads ----------


def test_average_spread_is_the_mean_of_each_typists_own_std() -> None:
    key = hold_key("t")
    a = [[Feature(key, v)] for v in (100.0, 110.0, 120.0, 130.0)]
    b = [[Feature(key, v)] for v in (100.0, 100.0, 100.0, 100.0)]
    std_a = build_profile(a)[key].std
    assert std_a is not None
    assert average_spreads({"a": a, "b": b}) == {key: pytest.approx((std_a + 0.0) / 2)}


@pytest.mark.parametrize(("weight", "expected_std"), [(0.0, 10.0), (0.5, 20.0), (1.0, 30.0)])
def test_blend_moves_the_std_toward_the_average_and_nothing_else(
    weight: float, expected_std: float
) -> None:
    key = hold_key("t")
    own = RunningStats(count=4, mean=100.0, m2=10.0**2 * 3)  # std 10
    blended = blend_profile({key: own}, {key: 30.0}, weight)[key]
    assert blended.std == pytest.approx(expected_std)
    assert (blended.count, blended.mean) == (4, 100.0)


def test_blend_leaves_alone_what_it_has_no_spread_for() -> None:
    key = hold_key("t")
    once = RunningStats(count=1, mean=100.0, m2=0.0)  # std undefined
    assert blend_profile({key: once}, {key: 30.0}, 0.5) == {key: once}
    twice = RunningStats(count=2, mean=100.0, m2=50.0)
    assert blend_profile({key: twice}, {}, 0.5) == {key: twice}


def test_blending_reaches_calibration_as_well_as_scoring() -> None:
    lines = _subjects(4, 12)
    wide = {key: 500.0 for key in build_profile(lines["s000"])}
    plain = score_target("s000", lines)
    blended = score_target("s000", lines, bench.blender(wide, 1.0))
    # A much wider spread shrinks every score, held-out ones included.
    assert max(blended.held_out) < min(plain.held_out)
    assert max(blended.impostor["s003"]) < min(plain.impostor["s003"])


# ---------- evaluate ----------


def test_evaluate_counts_accepts_and_rejects_at_each_targets_own_limit() -> None:
    scores = {
        "a": _target(
            [],
            genuine_first=[1.0, 2.0, 3.0, 4.0],
            genuine_later=[5.0, 5.0, 5.0, 5.0],
            impostor={"b": [1.0, 2.0], "c": [3.0, 9.0]},
        ),
        "b": _target(
            [],
            genuine_first=[1.0, 1.0],
            genuine_later=[1.0, 1.0],
            impostor={"a": [0.5, 0.5], "c": [0.5, 0.5]},
        ),
    }
    limits = {id(scores["a"]): 2.0, id(scores["b"]): 1.0}
    result = evaluate(scores, ["a", "b"], ["a", "b", "c"], lambda t: limits[id(t)])

    assert result.limits == [2.0, 1.0]
    # a: impostor scores 1, 2, 3, 9 -> two at or under 2.0. b: all four.
    assert result.fars == [2 / 4, 1.0]
    # a: 3 and 4 are over 2.0 in the same session; with the later
    # session's four 5.0s, 6 of 8 are over.
    assert result.frrs_first_session == [2 / 4, 0.0]
    assert result.frrs_all_later == [6 / 8, 0.0]
    assert result.far == 0.75
    assert result.frr_first_session == 0.25


def test_evaluate_uses_only_the_impostors_it_is_given() -> None:
    scores = {"a": _target([], genuine_first=[1.0], impostor={"b": [1.0], "c": [9.0]})}
    only_b = evaluate(scores, ["a"], ["a", "b"], fixed_limit(2.0))
    only_c = evaluate(scores, ["a"], ["a", "c"], fixed_limit(2.0))
    assert (only_b.far, only_c.far) == (1.0, 0.0)


def test_clamp_shares() -> None:
    result = RuleResult([GAME_MIN_THRESHOLD, 2.0, V1_MAX_THRESHOLD, V1_MAX_THRESHOLD], [], [], [])
    assert result.share_at_lower_clamp == 0.25
    assert result.share_at_upper_clamp == 0.5


# ---------- tuning ----------


def _result(far: float, frr: float) -> RuleResult:
    return RuleResult(limits=[1.0], fars=[far], frrs_first_session=[frr], frrs_all_later=[frr])


#: A stricter-to-looser sweep: false acceptance rises, false
#: rejection falls.
SWEEP = {1.0: _result(0.05, 0.50), 2.0: _result(0.30, 0.08), 3.0: _result(0.60, 0.02)}


@pytest.mark.parametrize(
    ("frr_ceiling", "expected"),
    [
        (0.10, 2.0),  # 2.0 and 3.0 meet it; 2.0 accepts fewer impostors
        (0.02, 3.0),  # only 3.0 meets it (the ceiling itself counts)
        (0.01, 3.0),  # nothing meets it: the lowest false rejection
    ],
)
def test_tune_matched(frr_ceiling: float, expected: float) -> None:
    assert tune_matched(list(SWEEP), SWEEP.__getitem__, frr_ceiling) == expected


def test_tune_balanced_minimizes_the_sum_of_both_errors() -> None:
    assert tune_balanced(list(SWEEP), SWEEP.__getitem__) == 2.0  # 0.38 < 0.55 < 0.62


def test_tuning_ties_go_to_the_earliest_value() -> None:
    same = {1.0: _result(0.2, 0.1), 2.0: _result(0.2, 0.1)}
    assert tune_matched(list(same), same.__getitem__, 0.5) == 1.0
    assert tune_balanced(list(same), same.__getitem__) == 1.0


# ---------- end to end ----------


def test_run_reports_every_rule_and_the_results_say_what_they_are_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines = _subjects(8, FIRST_SESSION_REPS + 10)
    results = bench.run(lines)

    assert sorted(results.tuning_half + results.report_half) == sorted(lines)
    names = [rule.name for rule in results.rules]
    assert names[0] == bench.BASELINE == "version 1 (cap 3.5)"
    assert bench.ADOPTED == "cap 2.0 (the game's rule now)"
    for expected in (
        "median x",
        "cap 3.0",
        "cap 2.5",
        bench.ADOPTED,
        "fixed",
        "blended",
        "dropped",
    ):
        assert any(expected in name for name in names), expected
    assert list(results.on_report_half) == names
    assert all(len(r.limits) == len(results.report_half) for r in results.on_report_half.values())
    # A lower cap can only tighten: never more impostors accepted.
    report = results.on_report_half
    assert report[bench.ADOPTED].far <= report["cap 2.5"].far <= report[bench.BASELINE].far

    out = tmp_path / "game_size_results.md"
    monkeypatch.setattr(bench, "RESULTS_MD_PATH", out)
    bench.write_results_md(results)
    text = out.read_text()
    assert "**None of this is the game's accuracy, or an estimate of it.**" in text
    # The warning comes before any number.
    assert text.index("What these numbers are not") < text.index("False acceptance")
    for name in names:
        assert f"| {name} |" in text
