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

    results = {
        "dataset": "DSL-StrongPasswordData.csv (Killourhy & Maxion, 2009)",
        "subjects": len(subjects),
        "train_reps_per_subject": TRAIN_REPS,
        "genuine_test_reps_per_subject": 400 - TRAIN_REPS,
        "impostor_reps_per_other_subject": IMPOSTOR_REPS_PER_SUBJECT,
        "summary": summary,
        "per_subject": per_subject,
    }
    RESULTS_JSON_PATH.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {RESULTS_JSON_PATH}")

    write_results_md(summary)
    print(f"Wrote {RESULTS_MD_PATH}")


def write_results_md(summary: dict[str, dict[str, float]]) -> None:
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
        "## Limitation",
        "",
        "All 51 subjects typed the same fixed password. This validates the *scoring",
        "method* -- whether scaled Manhattan distance actually separates genuine typists",
        "from impostors on real timing data -- not how the deployed app performs, since",
        "the app accepts arbitrary free text, not one fixed password.",
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
