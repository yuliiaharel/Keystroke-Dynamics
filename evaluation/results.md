# Benchmark results

## Method

CMU Keystroke Dynamics Benchmark Data Set (Killourhy & Maxion, 2009),
51 subjects x 400 repetitions of the fixed password `.tie5Roanl`.
Following the paper's protocol, for each subject:

- **Train**: that subject's first 200 repetitions build a profile
  (`core.stats.from_values` per hold/flight feature).
- **Genuine test**: that subject's remaining 200 repetitions,
  scored against their own profile.
- **Impostor test**: the first 5 repetitions from each of the other 50 subjects,
  scored against this subject's profile (5 x 50 = 250 impostor scores).
- **EER**: computed per subject from that subject's genuine/impostor score split
  (`evaluation.metrics.equal_error_rate`), then averaged across all 51 subjects.

The dataset's `H.*` (hold) and `DD.*` (down-to-down) columns map directly onto
`core.features`'s Hold and Flight definitions; `UD.*` (up-to-down) has no
equivalent feature in `core/` and isn't used.

This evaluation is fully deterministic (the train/test split is a fixed slice,
not a random sample), so no random seed applies.

## Results

| Method | Mean EER | Std EER |
|---|---|---|
| scaled_manhattan | 0.0910 | 0.0746 |
| three_sigma | 0.1456 | 0.0853 |
| plain_manhattan | 0.1386 | 0.0833 |

## Comparison against the published baseline

The paper reports a scaled Manhattan EER of about 0.10.
This run: **0.0910** (difference: -0.0090).

## Provisional threshold

`scaled_manhattan_score`'s `DEFAULT_THRESHOLD` (Phase 2's placeholder of 1.0) is
replaced with the mean of each subject's own EER-crossover threshold on this
benchmark: **1.0724**. This is a provisional
calibration, not an independently-validated operating point -- see the limitation
below.

## Limitation

All 51 subjects typed the same fixed password. This validates the *scoring
method* -- whether scaled Manhattan distance actually separates genuine typists
from impostors on real timing data -- not how the deployed app performs, since
the app accepts arbitrary free text, not one fixed password.

## Reproduce

```bash
uv run python -m evaluation.run_benchmark
```
