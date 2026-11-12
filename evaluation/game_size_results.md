# Limit rules at the game's size, on the CMU data

Written by `evaluation/game_size_benchmark.py`. It replays the CMU Keystroke
Dynamics Benchmark Data Set the way the party game enrolls a player -- 1 warm-up
line thrown away, 4 lines of training, a limit calibrated from those same
4 lines -- and compares rules for that limit.

## What these numbers are not

**None of this is the game's accuracy, or an estimate of it.** The CMU data is one
10-character password typed by 51 people in a lab. The game is different in ways
that move every rate below:

- **Impostors here are not trying.** Each "impostor" simply typed the same password
  in their own rhythm. A player attacking in the game has seen the target's rhythm
  and is imitating it, so false acceptance in the game should be expected to be
  higher than here at the same limit.
- **Genuine typists here are still learning.** `.tie5Roanl` was new to every
  subject, and repetitions 2-5 are the very start of learning it. An English
  sentence is typed with settled habits. False rejection in the game should be
  expected to be lower than here, and the later-session column (other days) has no
  counterpart in a game played in one sitting.
- **The line is different.** 21 features here, each seen once per repetition. A
  game line has more features, and repeated letters give some of them several
  values per line. The scores, and so the limits a rule hands out, are
  on a different footing: do not read the distribution of limits below as the
  game's. `evaluation/analyze_scores.py` prints the real one.
- **One keyboard, one device type.** No phones, no second keyboard.

What the replay can do is rank rules against each other under one fixed set of
conditions, and show where a rule's cost falls. Read it as that.

## Method

For each of the 51 subjects, using `game/scoring.py`'s own `build_profile`,
`score_sample` and `calibrate_threshold` with the game's constants:

- **Train**: repetitions 2-5. Repetition 1 is the warm-up
  and is not used.
- **Genuine attempts**: that subject's later repetitions, reported two ways. *Same
  session* is repetitions 6-50, the rest of the sitting the training came from,
  and the closer of the two to a game. *All later* is repetitions 6-400, which
  adds 7 sessions on other days.
- **Impostor attempts**: the first 5 repetitions of each other subject, as
  `evaluation/run_benchmark.py` does.
- An attempt is accepted when its score is at or under the target's limit.

Rates are the mean over targets of each target's own rate. Where a table shows
`±`, it is the standard error of that mean across targets, in percentage points.

## The version 1 rule, all subjects

Limit = highest held-out score x 1.2, clamped to 1.3-3.5. 51 targets, 250
impostor attempts each.

| | Rate |
|---|---|
| False acceptance | 41.2% ± 4.0 |
| False rejection, same session | 8.0% ± 2.1 |
| False rejection, all later | 14.6% ± 3.2 |

### Calibrated limits

| | Min | p10 | p25 | p50 | p75 | p90 | Max |
|---|---|---|---|---|---|---|---|
| Limit given | 1.30 | 1.45 | 1.59 | 1.95 | 2.49 | 3.02 | 3.50 |
| Before clamping | 1.11 | 1.45 | 1.59 | 1.95 | 2.49 | 3.02 | 3.76 |

### How often each clamp is reached

| Clamp | Targets | Share |
|---|---|---|
| Lower, 1.3 (raised to it) | 2 of 51 | 3.9% |
| Upper, 3.5 (cut down to it) | 1 of 51 | 2.0% |

Before clamping, 6 of 51 limits are above 3.0, 11 above 2.5 and 25 above 2.0 --
the targets a lower cap would actually change.

### Scores behind those rates

| Scores | n | p10 | p25 | p50 | p75 | p90 |
|---|---|---|---|---|---|---|
| Held-out training lines (what calibration sees) | 204 | 0.69 | 0.85 | 1.05 | 1.39 | 1.89 |
| Genuine, same session (repetitions 6-50) | 2295 | 0.78 | 0.92 | 1.12 | 1.34 | 1.65 |
| Genuine, later sessions (repetitions 51-400) | 17850 | 0.96 | 1.15 | 1.37 | 1.62 | 1.94 |
| Impostor | 12750 | 1.34 | 1.67 | 2.19 | 3.18 | 4.91 |

The two populations overlap heavily at this size: the lowest-scoring quarter of
impostor attempts is under 1.67, and the highest-scoring tenth of same-session
genuine attempts is over 1.65. No limit rule can separate what the
scores don't; a rule can only choose where to cut.

## Limit rules compared

The 51 subjects are split by a seeded shuffle (seed 2009) into a tuning half
(25) and a report half (26). Tuned values are chosen on the tuning half. Every
number in the first two tables is from the report half, with impostors drawn
from the report half only (125 attempts per target).

The rules:

- **version 1**: highest held-out score x 1.2, clamped to 1.3-3.5. The game's rule when this comparison was run.
- **median x m**: median held-out score (of 4, so the mean of the middle two) times
  m, inside the same 1.3-3.5 clamps.
- **cap c**: the version 1 rule with the upper clamp lowered to c. Nothing tuned.
  The 2.0 row is the rule the game uses now, computed by `calibrate_threshold` itself.
- **fixed v**: the same limit v for every target; no calibration.
- **version 1, spreads blended w**: before scoring, each feature's standard deviation
  is replaced by (1 - w) x the typist's own + w x the average of that feature's
  standard deviation across the tuning half's typists (each measured over their own
  4 training lines). The same blend is applied inside calibration. The game's
  spread floors still apply on top. The weight w is tuned.
- **version 1, worst line dropped**: the training line with the highest held-out
  score is removed, and the version 1 rule calibrates on the remaining 3. The profile
  attempts are scored against still uses all 4 lines. Nothing tuned.

Tuned values are chosen two ways, because one alone would mislead:

- **matched**: the lowest false acceptance among values whose same-session false
  rejection on the tuning half is no higher than the version 1 rule's there
  (7.1%). This asks whether a rule is *better* than version 1 at
  the false rejection players already get.
- **balanced**: the lowest false acceptance plus same-session false rejection.
  This shows how strict a rule gets when both errors count equally.

A rule has one row, marked *matched and balanced*, where both pick the same value.

### Report half (26 targets)

| Rule | False acceptance | False rejection, same session | False rejection, all later | Median limit | At 1.3 | At 3.5 |
|---|---|---|---|---|---|---|
| version 1 (cap 3.5) | 39.8% ± 5.6 | 8.9% ± 3.6 | 16.5% ± 5.1 | 1.94 | 7.7% | 3.8% |
| median x 1.6 (matched) | 27.0% ± 4.9 | 12.4% ± 3.5 | 23.7% ± 5.4 | 1.70 | 3.8% | 0.0% |
| median x 1.3 (balanced) | 14.9% ± 4.2 | 22.1% ± 3.9 | 41.3% ± 5.7 | 1.38 | 30.8% | 0.0% |
| cap 3.0 | 39.3% ± 5.5 | 8.9% ± 3.6 | 16.5% ± 5.1 | 1.94 | 7.7% | 0.0% |
| cap 2.5 | 38.3% ± 5.3 | 9.1% ± 3.5 | 16.6% ± 5.1 | 1.94 | 7.7% | 0.0% |
| cap 2.0 (the game's rule now) | 31.8% ± 4.3 | 9.8% ± 3.5 | 18.2% ± 4.9 | 1.94 | 7.7% | 0.0% |
| fixed 1.9 (matched) | 35.0% ± 3.6 | 4.5% ± 0.8 | 9.7% ± 2.0 | 1.90 | 0.0% | 0.0% |
| fixed 1.4 (balanced) | 11.0% ± 2.4 | 21.4% ± 3.1 | 43.5% ± 4.8 | 1.40 | 0.0% | 0.0% |
| version 1, spreads blended 0.5 (matched and balanced) | 33.6% ± 5.0 | 6.4% ± 2.9 | 18.9% ± 4.8 | 1.42 | 46.2% | 0.0% |
| version 1, worst line dropped | 33.2% ± 5.8 | 10.9% ± 3.1 | 21.9% ± 5.7 | 1.67 | 11.5% | 0.0% |

### Change from the version 1 rule, target by target (report half)

Each rule's rate minus the version 1 rule's on the same target, averaged, in
percentage points. A change smaller than about twice its `±` is not
distinguishable from no change on this many targets.

| Rule | False acceptance, change | False rejection (same session), change |
|---|---|---|
| median x 1.6 (matched) | -12.8 ± 4.1 | +3.5 ± 1.9 |
| median x 1.3 (balanced) | -24.9 ± 4.0 | +13.2 ± 2.6 |
| cap 3.0 | -0.5 ± 0.5 | +0.0 ± 0.0 |
| cap 2.5 | -1.4 ± 0.9 | +0.2 ± 0.2 |
| cap 2.0 (the game's rule now) | -8.0 ± 2.4 | +0.9 ± 0.3 |
| fixed 1.9 (matched) | -4.8 ± 4.1 | -4.4 ± 3.2 |
| fixed 1.4 (balanced) | -28.7 ± 4.4 | +12.5 ± 2.2 |
| version 1, spreads blended 0.5 (matched and balanced) | -6.2 ± 2.8 | -2.5 ± 1.8 |
| version 1, worst line dropped | -6.6 ± 5.7 | +2.0 ± 1.9 |

### Tuning half (25 targets), where the tuned values were chosen

For reference only: tuned rules look better here than they are.

| Rule | False acceptance | False rejection, same session | False rejection, all later | Median limit | At 1.3 | At 3.5 |
|---|---|---|---|---|---|---|
| version 1 (cap 3.5) | 42.8% ± 5.7 | 7.1% ± 2.2 | 12.6% ± 3.8 | 2.11 | 0.0% | 0.0% |
| median x 1.6 (matched) | 35.6% ± 4.1 | 6.3% ± 1.3 | 19.1% ± 4.6 | 1.72 | 0.0% | 0.0% |
| median x 1.3 (balanced) | 20.4% ± 3.9 | 16.4% ± 3.4 | 35.3% ± 6.3 | 1.40 | 28.0% | 0.0% |
| cap 3.0 | 42.0% ± 5.5 | 7.4% ± 2.2 | 13.0% ± 3.8 | 2.11 | 0.0% | 0.0% |
| cap 2.5 | 40.2% ± 5.1 | 8.0% ± 2.4 | 14.0% ± 3.9 | 2.11 | 0.0% | 0.0% |
| cap 2.0 (the game's rule now) | 33.5% ± 4.1 | 9.9% ± 2.9 | 17.5% ± 4.3 | 2.00 | 0.0% | 0.0% |
| fixed 1.9 (matched) | 38.8% ± 3.4 | 7.0% ± 2.7 | 11.4% ± 3.2 | 1.90 | 0.0% | 0.0% |
| fixed 1.4 (balanced) | 15.6% ± 2.7 | 19.0% ± 3.9 | 43.0% ± 5.5 | 1.40 | 0.0% | 0.0% |
| version 1, spreads blended 0.5 (matched and balanced) | 35.8% ± 4.6 | 6.2% ± 2.2 | 16.3% ± 3.5 | 1.47 | 36.0% | 0.0% |
| version 1, worst line dropped | 37.3% ± 5.2 | 9.5% ± 2.9 | 20.5% ± 5.0 | 1.90 | 8.0% | 4.0% |

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

## Reproduce

```bash
uv run python -m evaluation.game_size_benchmark
```
