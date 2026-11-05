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

## BioKey 2012 comparison

A second, independent method, reconstructed from the author's 2012 thesis
"Біометричний контроль доступу на базі динамічного клавіатурного паролю" for
comparison against this app's actual scoring method above. Implemented in
`evaluation/biokey_2012.py` -- evaluation only, never imported by the app.

**As the thesis states it:** a Haar wavelet transform (formula 1/4) of a
per-repetition timing signal; an acceptance range per Haar coefficient, built
from a running mean/variance (formulas 7/8) and a Student's-t range multiplier
(formula 6); a normalized Hamming distance between a test sample's coefficients
and those ranges as the decision score (lower = more genuine-like). Formula (8)
is *not* the standard (Welford) variance -- it's a distinct, measurably biased
recursion; `biokey_as_written` uses it deliberately, to measure the thesis's
method exactly as written.

**Reconstruction (not specified by the thesis; the original code no longer
exists):** this dataset's `H.*`/`UD.*` columns are threaded into an alternating
H, UD, H, UD, ..., H sequence, **excluding `Return`** (its hold and the UD
leading into it reflect ending the trial, not ongoing typing rhythm -- the same
reasoning `core/events.py` already applies when excluding Enter/Return from this
app's own features), then linearly resampled to a fixed length N and divided by
its own sum. `biokey_corrected` and `raw_corrected` use exact (Welford) variance
and a two-sided, finite-sample-corrected range multiplier instead of formula (8)
and the one-sided multiplier; `raw_corrected` additionally skips the Haar
transform and ranges the raw resampled signal directly.

Two training sizes are reported: the paper's protocol (first 200 repetitions)
and the thesis's own enrollment size (first 10). Both use the *same* genuine
(remaining 200 repetitions) and impostor (first
5 from each other subject) test sets as the main
comparison above -- only the amount of enrollment data differs. The profile is
kept fixed during evaluation; the thesis's update-after-login step is not
applied here (see TODO.md).

| Variant | Train reps | Mean EER | Std EER | Genuine values out of range (intended 10%) | False rejects @0.3 | False accepts @0.3 |
|---|---|---|---|---|---|---|
| biokey_as_written | 200 | 0.2229 | 0.1111 | 17.5% | 21.8% | 26.6% |
| biokey_as_written | 10 | 0.5215 | 0.1887 | 42.1% | 79.1% | 23.0% |
| biokey_corrected | 200 | 0.2314 | 0.1111 | 9.2% | 5.4% | 56.0% |
| biokey_corrected | 10 | 0.4921 | 0.1732 | 23.8% | 35.3% | 63.1% |
| raw_corrected | 200 | 0.2297 | 0.1193 | 11.1% | 6.3% | 44.2% |
| raw_corrected | 10 | 0.5851 | 0.1627 | 33.7% | 65.6% | 49.7% |

The false-reject/false-accept columns use the thesis's own reported decision
threshold (0.3) taken as-is, not tuned on this data.

### Sensitivity to N (resample length, train reps = 200)

The thesis doesn't specify N; the primary results above use N=16.

| Variant | N | Mean EER | Std EER |
|---|---|---|---|
| biokey_as_written | 16 | 0.2229 | 0.1111 |
| biokey_as_written | 8 | 0.2549 | 0.1028 |
| biokey_as_written | 32 | 0.2142 | 0.1270 |
| biokey_corrected | 16 | 0.2314 | 0.1111 |
| biokey_corrected | 8 | 0.2536 | 0.1033 |
| biokey_corrected | 32 | 0.2129 | 0.1161 |
| raw_corrected | 16 | 0.2297 | 0.1193 |
| raw_corrected | 8 | 0.2419 | 0.1052 |
| raw_corrected | 32 | 0.2100 | 0.1191 |

### About the thesis's own reported results

The thesis itself reports results from one user, one password, 5 genuine
attempts, and 15 impostor attempts. The numbers above measure a reconstruction
of the method on a 51-subject public dataset with a different password and a
much larger genuine/impostor test set -- they do not confirm or reproduce the
thesis's own results, only measure the same method on different data.

## Limitation

All 51 subjects typed the same fixed password, while the app accepts longer
free text. These numbers validate the *scoring methods* -- whether they actually
separate genuine typists from impostors on real timing data -- not how the
deployed app performs.

## Reproduce

```bash
uv run python -m evaluation.run_benchmark
```
