# Benchmark evaluation

Measures the scoring methods in `core/scoring.py` against the CMU Keystroke
Dynamics Benchmark Data Set (Killourhy & Maxion, 2009):
https://www.cs.cmu.edu/~keystroke/

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
