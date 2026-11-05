"""Benchmark scaled Manhattan, corrected 3-sigma, and plain Manhattan
scoring against the CMU Keystroke Dynamics Benchmark Data Set
(Killourhy & Maxion, 2009), following the paper's protocol exactly:

For each of the 51 subjects:
  - Train a profile from that subject's first 200 repetitions.
  - Genuine test scores: that subject's remaining 200 repetitions,
    scored against their own profile.
  - Impostor test scores: the first 5 repetitions from each of the
    other 50 subjects, scored against this subject's profile.
  - Compute that subject's EER from the genuine/impostor score split.
Then report the mean and standard deviation of EER across all 51
subjects, for each scoring method.

This protocol is fully deterministic -- the train/test split is a
fixed slice (first 200 / remaining 200 / first 5), not a random
sample -- so there is no randomness here to seed.

See evaluation/README.md to download the dataset first. Run:
    uv run python -m evaluation.run_benchmark
"""

from __future__ import annotations

import csv
import json
import statistics
from collections.abc import Callable
from pathlib import Path

from evaluation.biokey_2012 import (
    DEFAULT_P as BIOKEY_P,
)
from evaluation.biokey_2012 import (
    THESIS_THRESHOLD as BIOKEY_THESIS_THRESHOLD,
)
from evaluation.biokey_2012 import (
    enroll_biokey_as_written,
    enroll_biokey_corrected,
    enroll_raw_corrected,
    score_as_written,
    score_corrected,
    score_raw_corrected,
)
from evaluation.metrics import equal_error_rate
from keystroke_dynamics.core.features import Feature, FeatureKey
from keystroke_dynamics.core.scoring import (
    ScoreResult,
    plain_manhattan_score,
    scaled_manhattan_score,
    three_sigma_score,
)
from keystroke_dynamics.core.stats import RunningStats, from_values

DATA_PATH = Path(__file__).parent / "data" / "DSL-StrongPasswordData.csv"
RESULTS_MD_PATH = Path(__file__).parent / "results.md"
RESULTS_JSON_PATH = Path(__file__).parent / "results.json"

# The fixed password is ".tie5Roanl". Capital R is Shift+r, which the
# dataset records as one combined event, "Shift.r" -- so there are 11
# key events, not 10 characters.
KEYS = ["period", "t", "i", "e", "five", "Shift.r", "o", "a", "n", "l", "Return"]

TRAIN_REPS = 200
IMPOSTOR_REPS_PER_SUBJECT = 5

SCORERS: dict[str, Callable[..., ScoreResult]] = {
    "scaled_manhattan": scaled_manhattan_score,
    "three_sigma": three_sigma_score,
    "plain_manhattan": plain_manhattan_score,
}

# Published baseline (Killourhy & Maxion 2009) for scaled Manhattan,
# for the sanity check in the results writeup.
PUBLISHED_SCALED_MANHATTAN_EER = 0.10

# BioKey 2012 (evaluation.biokey_2012): "Return" is excluded from its
# timing signal -- see build_timing_signal's docstring for why.
BIOKEY_KEYS = KEYS[:-1]
BIOKEY_N = 16  # primary resample length
BIOKEY_SENSITIVITY_NS = [8, 32]  # sensitivity checks, train_reps=200 only
#: enroll(training_rows, keys, n, P) -> BioKeyProfile,
#: score(row, keys, n, profile) -> float
BIOKEY_VARIANTS: dict[str, tuple[Callable[..., object], Callable[..., float]]] = {
    "biokey_as_written": (enroll_biokey_as_written, score_as_written),
    "biokey_corrected": (enroll_biokey_corrected, score_corrected),
    "raw_corrected": (enroll_raw_corrected, score_raw_corrected),
}
#: Training sizes to report: the paper's protocol (200) and the
#: thesis's own enrollment size (10). Both use the *same* genuine/
#: impostor test sets (see run_biokey below) -- only the amount of
#: enrollment data differs between them.
BIOKEY_TRAIN_SIZES = [200, 10]


def hold_key(code: str) -> FeatureKey:
    return ("hold", code)


def flight_key(a: str, b: str) -> FeatureKey:
    return ("flight", a, b)


def row_to_features(row: dict[str, str]) -> list[Feature]:
    """One CSV row -> the Features core/ understands. H.<key> is
    exactly our hold definition (down-to-up, same key); DD.<a>.<b>
    (down-to-down) is exactly our flight definition. The dataset's
    UD.* (up-to-down) columns have no equivalent feature in core/ and
    aren't used.
    """
    features = [Feature(hold_key(key), float(row[f"H.{key}"]) * 1000.0) for key in KEYS]
    features += [
        Feature(flight_key(a, b), float(row[f"DD.{a}.{b}"]) * 1000.0)
        for a, b in zip(KEYS, KEYS[1:], strict=False)
    ]
    return features


def load_rows() -> dict[str, list[dict[str, str]]]:
    if not DATA_PATH.exists():
        raise SystemExit(
            f"Dataset not found at {DATA_PATH}.\nSee evaluation/README.md to download it."
        )
    by_subject: dict[str, list[dict[str, str]]] = {}
    with DATA_PATH.open(newline="") as f:
        for row in csv.DictReader(f):
            by_subject.setdefault(row["subject"], []).append(row)
    return by_subject


def build_profile(rows: list[dict[str, str]]) -> dict[FeatureKey, RunningStats]:
    per_key_values: dict[FeatureKey, list[float]] = {}
    for row in rows:
        for feature in row_to_features(row):
            per_key_values.setdefault(feature.key, []).append(feature.value_ms)
    return {key: from_values(values) for key, values in per_key_values.items()}


def to_anomaly_score(method: str, result: ScoreResult) -> float:
    """Unifies each method's native direction into "lower = more
    likely genuine": three_sigma_score's match ratio is higher-is-
    better, so it's inverted; the two Manhattan variants are already
    lower-is-better distances.
    """
    assert result.score is not None
    return 1.0 - result.score if method == "three_sigma" else result.score


def _biokey_impostor_rows(
    by_subject: dict[str, list[dict[str, str]]], subjects: list[str], subject: str
) -> list[dict[str, str]]:
    return [
        row
        for other in subjects
        if other != subject
        for row in by_subject[other][:IMPOSTOR_REPS_PER_SUBJECT]
    ]


def run_biokey(
    by_subject: dict[str, list[dict[str, str]]], subjects: list[str]
) -> dict[str, dict[str, object]]:
    """Runs all three BioKey 2012 variants at both training sizes
    (same genuine/impostor test sets for both -- only the amount of
    enrollment data differs), plus the N=8/32 sensitivity checks at
    train_reps=200. Returns one entry per "{variant}@{train_reps}" (and
    "{variant}@{train_reps}@N{n}" for the sensitivity runs).
    """
    results: dict[str, dict[str, object]] = {}

    for train_reps in BIOKEY_TRAIN_SIZES:
        for variant, (enroll, score) in BIOKEY_VARIANTS.items():
            for n in [BIOKEY_N, *(BIOKEY_SENSITIVITY_NS if train_reps == TRAIN_REPS else [])]:
                key = f"{variant}@{train_reps}" if n == BIOKEY_N else f"{variant}@{train_reps}@N{n}"

                eers = []
                genuine_out_of_range_shares = []
                false_reject_rates = []
                false_accept_rates = []

                for subject in subjects:
                    rows = by_subject[subject]
                    training_rows = rows[:train_reps]
                    # Always the same test sets, regardless of training
                    # size -- rows[TRAIN_REPS:] (not rows[train_reps:]).
                    genuine_test_rows = rows[TRAIN_REPS:]
                    impostor_rows = _biokey_impostor_rows(by_subject, subjects, subject)

                    profile = enroll(training_rows, BIOKEY_KEYS, n, BIOKEY_P)
                    genuine_scores = [
                        score(row, BIOKEY_KEYS, n, profile) for row in genuine_test_rows
                    ]
                    impostor_scores = [score(row, BIOKEY_KEYS, n, profile) for row in impostor_rows]

                    # Lower is already more genuine-like (the Hamming
                    # score IS the out-of-range fraction) -- no
                    # inversion needed, unlike three_sigma_score.
                    eers.append(equal_error_rate(genuine_scores, impostor_scores).eer)

                    # Each genuine score already *is* that sample's
                    # share of features outside their range -- their
                    # mean across genuine samples is directly "the
                    # actual share of genuine values outside their
                    # ranges" the plan asks to report.
                    genuine_out_of_range_shares.append(statistics.mean(genuine_scores))

                    false_reject_rates.append(
                        statistics.mean(s > BIOKEY_THESIS_THRESHOLD for s in genuine_scores)
                    )
                    false_accept_rates.append(
                        statistics.mean(s <= BIOKEY_THESIS_THRESHOLD for s in impostor_scores)
                    )

                results[key] = {
                    "train_reps": train_reps,
                    "n": n,
                    "mean_eer": statistics.mean(eers),
                    "std_eer": statistics.stdev(eers),
                    "mean_genuine_out_of_range_share": statistics.mean(genuine_out_of_range_shares),
                    "mean_false_reject_rate": statistics.mean(false_reject_rates),
                    "mean_false_accept_rate": statistics.mean(false_accept_rates),
                }
                print(
                    f"  biokey {key}: "
                    f"mean_eer={results[key]['mean_eer']:.4f} "
                    f"fr@{BIOKEY_THESIS_THRESHOLD}={results[key]['mean_false_reject_rate']:.4f} "
                    f"fa@{BIOKEY_THESIS_THRESHOLD}={results[key]['mean_false_accept_rate']:.4f}"
                )

    return results


def main() -> None:
    by_subject = load_rows()
    subjects = sorted(by_subject)
    print(f"Loaded {len(subjects)} subjects.")
    for subject, rows in by_subject.items():
        assert len(rows) == 400, f"{subject} has {len(rows)} rows, expected 400"

    per_subject: dict[str, dict[str, dict[str, float]]] = {}

    for subject in subjects:
        rows = by_subject[subject]
        train_rows, genuine_test_rows = rows[:TRAIN_REPS], rows[TRAIN_REPS:]
        profile = build_profile(train_rows)

        impostor_rows = [
            row
            for other in subjects
            if other != subject
            for row in by_subject[other][:IMPOSTOR_REPS_PER_SUBJECT]
        ]

        per_subject[subject] = {}
        for method, scorer in SCORERS.items():
            genuine_scores = []
            for row in genuine_test_rows:
                result = scorer(row_to_features(row), profile)
                assert result.score is not None, (
                    f"{subject}/{method}: unexpected INSUFFICIENT_DATA on a genuine test row"
                )
                genuine_scores.append(to_anomaly_score(method, result))

            impostor_scores = []
            for row in impostor_rows:
                result = scorer(row_to_features(row), profile)
                assert result.score is not None, (
                    f"{subject}/{method}: unexpected INSUFFICIENT_DATA on an impostor test row"
                )
                impostor_scores.append(to_anomaly_score(method, result))

            eer_result = equal_error_rate(genuine_scores, impostor_scores)
            per_subject[subject][method] = {
                "eer": eer_result.eer,
                "threshold": eer_result.threshold,
            }

        eer_summary = ", ".join(f"{m}={per_subject[subject][m]['eer']:.4f}" for m in SCORERS)
        print(f"  {subject}: {eer_summary}")

    summary = {}
    for method in SCORERS:
        eers = [per_subject[s][method]["eer"] for s in subjects]
        thresholds = [per_subject[s][method]["threshold"] for s in subjects]
        summary[method] = {
            "mean_eer": statistics.mean(eers),
            "std_eer": statistics.stdev(eers),
            "mean_eer_threshold": statistics.mean(thresholds),
        }

    print("\nBioKey 2012:")
    biokey_results = run_biokey(by_subject, subjects)

    results = {
        "dataset": "DSL-StrongPasswordData.csv (Killourhy & Maxion, 2009)",
        "subjects": len(subjects),
        "train_reps_per_subject": TRAIN_REPS,
        "genuine_test_reps_per_subject": 400 - TRAIN_REPS,
        "impostor_reps_per_other_subject": IMPOSTOR_REPS_PER_SUBJECT,
        "summary": summary,
        "per_subject": per_subject,
        "biokey_2012": biokey_results,
    }
    RESULTS_JSON_PATH.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {RESULTS_JSON_PATH}")

    write_results_md(summary, biokey_results)
    print(f"Wrote {RESULTS_MD_PATH}")


def _biokey_section(biokey_results: dict[str, dict[str, object]]) -> list[str]:
    lines = [
        "## BioKey 2012 comparison",
        "",
        "A second, independent method, reconstructed from the author's 2012 thesis",
        '"Біометричний контроль доступу на базі динамічного клавіатурного паролю" for',
        "comparison against this app's actual scoring method above. Implemented in",
        "`evaluation/biokey_2012.py` -- evaluation only, never imported by the app.",
        "",
        "**As the thesis states it:** a Haar wavelet transform (formula 1/4) of a",
        "per-repetition timing signal; an acceptance range per Haar coefficient, built",
        "from a running mean/variance (formulas 7/8) and a Student's-t range multiplier",
        "(formula 6); a normalized Hamming distance between a test sample's coefficients",
        "and those ranges as the decision score (lower = more genuine-like). Formula (8)",
        "is *not* the standard (Welford) variance -- it's a distinct, measurably biased",
        "recursion; `biokey_as_written` uses it deliberately, to measure the thesis's",
        "method exactly as written.",
        "",
        "**Reconstruction (not specified by the thesis; the original code no longer",
        "exists):** this dataset's `H.*`/`UD.*` columns are threaded into an alternating",
        "H, UD, H, UD, ..., H sequence, **excluding `Return`** (its hold and the UD",
        "leading into it reflect ending the trial, not ongoing typing rhythm -- the same",
        "reasoning `core/events.py` already applies when excluding Enter/Return from this",
        "app's own features), then linearly resampled to a fixed length N and divided by",
        "its own sum. `biokey_corrected` and `raw_corrected` use exact (Welford) variance",
        "and a two-sided, finite-sample-corrected range multiplier instead of formula (8)",
        "and the one-sided multiplier; `raw_corrected` additionally skips the Haar",
        "transform and ranges the raw resampled signal directly.",
        "",
        "Two training sizes are reported: the paper's protocol (first 200 repetitions)",
        "and the thesis's own enrollment size (first 10). Both use the *same* genuine",
        f"(remaining {400 - TRAIN_REPS} repetitions) and impostor (first",
        f"{IMPOSTOR_REPS_PER_SUBJECT} from each other subject) test sets as the main",
        "comparison above -- only the amount of enrollment data differs. The profile is",
        "kept fixed during evaluation; the thesis's update-after-login step is not",
        "applied here (see TODO.md).",
        "",
        f"| Variant | Train reps | Mean EER | Std EER | Genuine values out of range "
        f"(intended {BIOKEY_P:.0%}) | False rejects @{BIOKEY_THESIS_THRESHOLD} | "
        f"False accepts @{BIOKEY_THESIS_THRESHOLD} |",
        "|---|---|---|---|---|---|---|",
    ]
    for variant in BIOKEY_VARIANTS:
        for train_reps in BIOKEY_TRAIN_SIZES:
            r = biokey_results[f"{variant}@{train_reps}"]
            lines.append(
                f"| {variant} | {train_reps} | {r['mean_eer']:.4f} | {r['std_eer']:.4f} | "
                f"{r['mean_genuine_out_of_range_share']:.1%} | "
                f"{r['mean_false_reject_rate']:.1%} | {r['mean_false_accept_rate']:.1%} |"
            )

    lines += [
        "",
        "The false-reject/false-accept columns use the thesis's own reported decision",
        f"threshold ({BIOKEY_THESIS_THRESHOLD}) taken as-is, not tuned on this data.",
        "",
        f"### Sensitivity to N (resample length, train reps = {TRAIN_REPS})",
        "",
        "The thesis doesn't specify N; the primary results above use N=16.",
        "",
        "| Variant | N | Mean EER | Std EER |",
        "|---|---|---|---|",
    ]
    for variant in BIOKEY_VARIANTS:
        for n in [BIOKEY_N, *BIOKEY_SENSITIVITY_NS]:
            key = f"{variant}@{TRAIN_REPS}" if n == BIOKEY_N else f"{variant}@{TRAIN_REPS}@N{n}"
            r = biokey_results[key]
            lines.append(f"| {variant} | {n} | {r['mean_eer']:.4f} | {r['std_eer']:.4f} |")

    lines += [
        "",
        "### About the thesis's own reported results",
        "",
        "The thesis itself reports results from one user, one password, 5 genuine",
        "attempts, and 15 impostor attempts. The numbers above measure a reconstruction",
        "of the method on a 51-subject public dataset with a different password and a",
        "much larger genuine/impostor test set -- they do not confirm or reproduce the",
        "thesis's own results, only measure the same method on different data.",
        "",
    ]
    return lines


def write_results_md(
    summary: dict[str, dict[str, float]], biokey_results: dict[str, dict[str, object]]
) -> None:
    scaled = summary["scaled_manhattan"]
    diff = scaled["mean_eer"] - PUBLISHED_SCALED_MANHATTAN_EER

    lines = [
        "# Benchmark results",
        "",
        "## Method",
        "",
        "CMU Keystroke Dynamics Benchmark Data Set (Killourhy & Maxion, 2009),",
        "51 subjects x 400 repetitions of the fixed password `.tie5Roanl`.",
        "Following the paper's protocol, for each subject:",
        "",
        f"- **Train**: that subject's first {TRAIN_REPS} repetitions build a profile",
        "  (`core.stats.from_values` per hold/flight feature).",
        f"- **Genuine test**: that subject's remaining {400 - TRAIN_REPS} repetitions,",
        "  scored against their own profile.",
        "- **Impostor test**: the first "
        f"{IMPOSTOR_REPS_PER_SUBJECT} repetitions from each of the other 50 subjects,",
        "  scored against this subject's profile "
        f"({IMPOSTOR_REPS_PER_SUBJECT} x 50 = {IMPOSTOR_REPS_PER_SUBJECT * 50} impostor scores).",
        "- **EER**: computed per subject from that subject's genuine/impostor score split",
        "  (`evaluation.metrics.equal_error_rate`), then averaged across all 51 subjects.",
        "",
        "The dataset's `H.*` (hold) and `DD.*` (down-to-down) columns map directly onto",
        "`core.features`'s Hold and Flight definitions; `UD.*` (up-to-down) has no",
        "equivalent feature in `core/` and isn't used.",
        "",
        "This evaluation is fully deterministic (the train/test split is a fixed slice,",
        "not a random sample), so no random seed applies.",
        "",
        "## Results",
        "",
        "| Method | Mean EER | Std EER |",
        "|---|---|---|",
    ]
    for method, stats in summary.items():
        lines.append(f"| {method} | {stats['mean_eer']:.4f} | {stats['std_eer']:.4f} |")

    lines += [
        "",
        "## Comparison against the published baseline",
        "",
        f"The paper reports a scaled Manhattan EER of about {PUBLISHED_SCALED_MANHATTAN_EER:.2f}.",
        f"This run: **{scaled['mean_eer']:.4f}** (difference: {diff:+.4f}).",
        "",
        "## Provisional threshold",
        "",
        "`scaled_manhattan_score`'s `DEFAULT_THRESHOLD` (Phase 2's placeholder of 1.0) is",
        "replaced with the mean of each subject's own EER-crossover threshold on this",
        "benchmark: "
        f"**{summary['scaled_manhattan']['mean_eer_threshold']:.4f}**. This is a provisional",
        "calibration, not an independently-validated operating point -- see the limitation",
        "below.",
        "",
        *_biokey_section(biokey_results),
        "## Limitation",
        "",
        "All 51 subjects typed the same fixed password, while the app accepts longer",
        "free text. These numbers validate the *scoring methods* -- whether they actually",
        "separate genuine typists from impostors on real timing data -- not how the",
        "deployed app performs.",
        "",
        "## Reproduce",
        "",
        "```bash",
        "uv run python -m evaluation.run_benchmark",
        "```",
        "",
    ]
    RESULTS_MD_PATH.write_text("\n".join(lines))


if __name__ == "__main__":
    main()
