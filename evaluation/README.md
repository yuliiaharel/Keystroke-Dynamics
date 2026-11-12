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

## Limit rules at the game's size

`game_size_benchmark.py` replays the same dataset the way the party game
enrolls a player -- 1 warm-up repetition skipped, 4 repetitions of training,
`game/scoring.py`'s own functions and constants -- and compares rules for the
per-player limit:

```bash
uv run python -m evaluation.game_size_benchmark
```

Writes `evaluation/game_size_results.md`. It ranks limit rules against each
other on one password typed by people who were not imitating each other; it
is **not** the game's accuracy, and that file says why at the top.

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
new ones): the distribution of limits actually given (each attempt's own
`limit_value`, counted once per target), the real pass rate at each
attempt's own limit, false-reject/false-accept rates across a range of
hypothetical limits, those same rates by `device_type` and by pace bucket,
rhythm compared with place, Rhythm and Place split by `device_type` and then
by mode and same or different keyboard (or phone), attempts per player and
per party, and flags for unusually bursty activity on one day.

A touch row is judged on its `total` (rhythm and place together), a keyboard
row on its `rhythm`, which for a keyboard row is the same number. Versions
"2" and "3" score keyboard rows identically (`"3"` only added touch rooms),
so keyboard rows can be compared across the two, but the script still prints
each version under its own heading. The limit tables don't yet know that
touch limits start at 1.65 rather than 1.3: a touch limit at its lower clamp
is counted in the lowest range, not labeled as a clamp. Any group with fewer than 5 attempts
has its numbers hidden, never shown with a caveat; the table is followed by
a `hidden:` line naming the group and its size, so a missing row is not
mistaken for no data.

**This is not a benchmark.** `mode` and every identity in the table are
self-reported by whichever client sent the request, and real play can't be
reliably separated from scripted attempts. Rows with `consent_version`
"1" come from the earlier opt-in checkbox, so they are self-selected; later
rows are every attempt played. Treat every number here as an observed rate
on uncontrolled play -- never as this game's (or this scoring method's)
accuracy. For that, see the CMU benchmark above.
