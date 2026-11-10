# Benchmark evaluation

Measures the scoring methods in `core/scoring.py`, plus the BioKey 2012
method (`biokey_2012.py`, evaluation only, never imported by the app),
against the CMU Keystroke Dynamics Benchmark Data Set (Killourhy & Maxion,
2009): https://www.cs.cmu.edu/~keystroke/

BioKey 2012 needs SciPy, which isn't installed by default (it's not an app
dependency -- see pyproject.toml's `evaluation` dependency group):

```bash
uv sync --group evaluation
```

## Get the dataset

Not committed to the repo. Download it into `evaluation/data/`:

```bash
mkdir -p evaluation/data
curl -o evaluation/data/DSL-StrongPasswordData.csv \
  https://www.cs.cmu.edu/~keystroke/DSL-StrongPasswordData.csv
```

Verify it's the expected file:

```bash
shasum -a 256 evaluation/data/DSL-StrongPasswordData.csv
# b11d23538b1865fa6ecf4e8b78567caa312e9c1027604bb022fcc6ad7eaa7a33
wc -l evaluation/data/DSL-StrongPasswordData.csv
# 20401 (1 header + 51 subjects x 400 repetitions)
```

## Run it

```bash
uv run python -m evaluation.run_benchmark
```

Writes `evaluation/results.md` and `evaluation/results.json`.

## What it measures, and what it doesn't

All 51 subjects typed the same fixed password (`.tie5Roanl`) hundreds of
times. This validates the *scoring method* -- does scaled Manhattan distance
actually separate genuine typists from impostors, on real timing data -- not
how the deployed app performs, since the app accepts arbitrary free text, not
one fixed password.

## Analyzing saved party scores

`analyze_scores.py` is a separate, unrelated script: a read-only look at
`score_attempts`, the party game's own table of automatically saved scores
(`docs/plans/done/PARTY_LAUNCH_PLAN.md` section 10) -- not the CMU benchmark above, and
not something that runs against benchmark data at all.

```bash
uv run python -m evaluation.analyze_scores "<read-only connection string>"
```

Use the **read-only** role's connection string (see `DEPLOY.md`), never the
app's own `SCORES_DATABASE_URL` -- that one is write-only by design (the
app's own database role can only insert and delete).

Prints, for each `scoring_version` present (never mixed across versions,
since a scoring or game-settings change makes old rows incomparable to
new ones): false-reject/false-accept rates across a range of candidate
limits, those same rates by `device_type` and by pace bucket, rhythm
compared with place, attempts per player and per party, and flags for
unusually bursty activity on one day. Any group with fewer than 5 attempts
is hidden from its table entirely, never shown with a caveat.

**This is not a benchmark.** `mode` and every identity in the table are
self-reported by whichever client sent the request, and real play can't be
reliably separated from scripted attempts. Rows with `consent_version`
"1" come from the earlier opt-in checkbox, so they are self-selected; later
rows are every attempt played. Treat every number here as an observed rate
on uncontrolled play -- never as this game's (or this scoring method's)
accuracy. For that, see the CMU benchmark above.
