# Keystroke Dynamics: Modernization Plan

> **Status: Done.** Merged to `master` on 2026-11-04 in pull request #3.
>
> Archived. This plan is history, not instructions, and may no longer match the code.

## Outcome

Written on 2026-11-09 from the repository and git history only. Dates are git commit dates.

**What shipped**

- The Python 2 Flask demo was replaced by a Python 3 app: FastAPI, Jinja2 pages, Postgres through SQLAlchemy 2 and Alembic, and Argon2id passwords.
- `core/` holds the timing features, running statistics, and scoring, with tests.
- `evaluation/` holds the benchmark scripts, with results in `evaluation/results.md`.
- The frontend is a TypeScript capture module built with Vite, with Playwright end-to-end tests.
- The app runs locally from a Dockerfile and Compose file, and GitHub Actions runs the checks.
- `legacy/` and the old `readme.txt` are gone.

**Pull requests:** #3 (`modernize`, 37 commits).

**Notable changes from the plan**

- The BioKey 2012 comparison was added to the plan on 2026-11-03, after work had started.
- A first "Typing Twin" game was added on the same branch on 2026-11-04. The plan doesn't mention it. `docs/plans/done/PARTY_LAUNCH_PLAN.md` later replaced it.
- Cloud deployment was out of scope here. It was done later under the party launch plan.
- The account system this plan built is now off by default (`ENABLE_ACCOUNTS=false`).

**Left undone**

- The five open items in `TODO.md`.
- Everything under "Later ideas".
- **Uncertain:** the Phase 7 history decision. A commit titled "Stop tracking keystroke.sqlite" exists, but no `.sqlite` path appears anywhere in the reachable history. That suggests the history was rewritten, which the repository alone can't confirm.
- **Uncertain:** the Phase 0 closeout table and the Phase 7 audit results were reported in conversation, and aren't in the repository.

---

Repository: `yuliiaharel/Keystroke-Dynamics`

## Goal

Replace the 2018 Python 2 Flask demo with a tested Python 3 application that:

- has no known injection or file-write vulnerabilities
- calculates its statistics correctly
- reports measured accuracy on a public benchmark

Keep the original idea and page flow: create a profile, then type to authenticate.

## How to use this plan

Run each phase in a new Claude Code session, using the prompt under that phase. Review the result before starting the next phase.

First-time setup, from the repository root:

```bash
git checkout master
git pull
git checkout -b modernize
# Copy this file into the repository as docs/plans/done/MODERNIZATION_PLAN.md
git add docs/plans/done/MODERNIZATION_PLAN.md
git commit -m "Add modernization plan"
```

## Rules for Claude Code (every phase)

1. Read this file, `README.md`, and `TODO.md` before making changes.
2. Work only on the requested phase. Do not begin the next phase.
3. Work on the `modernize` branch. Make small, focused commits. Do not push, open a pull request, or rewrite git history.
4. Do not add a dependency, service, or abstraction that this plan does not call for without asking first.
5. Write or update tests with each behavior change. Do not weaken a test or threshold to get a passing result.
6. Run every check in the phase's "Done when" list and show the actual results.
7. Ask me if the code contradicts this plan or a decision here looks wrong. Do not silently choose a different design.
8. Finish with a summary of what changed, the check results, and anything I need to decide.

## Decisions already made

| Area | Decision |
|---|---|
| Runtime | Python 3.12 or newer, managed with `uv`, with a committed lockfile |
| Web | FastAPI, Pydantic v2, and Jinja2 templates |
| Numerics | NumPy for scoring and evaluation; SciPy for evaluation only; scikit-learn only if a compared model needs it |
| Database | Postgres through SQLAlchemy 2 and Alembic, with shared tables and no per-user tables |
| Passwords | Argon2id through `argon2-cffi` |
| Frontend | Server-rendered pages plus one small TypeScript module built with Vite; no jQuery or SPA framework |
| Quality | `pytest`, `ruff`, `mypy`, and GitHub Actions |
| Local run | Docker Compose |
| Role of typing data | A risk signal alongside a password, never the only login factor |
| Raw keystrokes | Processed in memory and never written to disk, the database, or logs |
| Old data | Not migrated; the old statistics are wrong and users have no credentials |

### Out of scope

Do not add microservices, message queues, Kubernetes, a separate frontend application, passkeys, or a cloud deployment.

## Target layout

```text
pyproject.toml
uv.lock
compose.yaml
Dockerfile
.env.example
alembic.ini
migrations/
frontend/                  # TypeScript capture module and Vite config
src/keystroke_dynamics/
  main.py                  # App creation and wiring
  config.py                # Settings loaded from the environment
  api/                     # Routes and request/response schemas
  core/
    events.py              # Validate events and pair keydown/keyup
    features.py            # Hold and flight features
    stats.py               # Welford running statistics
    scoring.py             # Match score and decision
  db/                      # Models and repository functions
  templates/
  static/
evaluation/                # Benchmark scripts and committed results
tests/
```

`core/` must not import FastAPI, SQLAlchemy, or any other I/O library.

---

## Phase 0: Audit the plan against the code

**Purpose:** confirm the known problems before changing anything. Make no application code changes in this phase.

Confirm each item with a file and line reference, and report anything else this plan misses.

**Security**
- [ ] Usernames are concatenated into SQL as table names in `profile.py`, `bioauth.py`, and `checkname.py`.
- [ ] Usernames from the `User` request header are used in filenames without validation in `keystroke.py`.
- [ ] CORS allows any origin, `debug=True` is enabled, and the server binds `0.0.0.0`.
- [ ] Any username can be submitted without a credential.

**Statistics and scoring**
- [ ] The running mean in `profile.py` uses `(mean + value) / count`, which is incorrect.
- [ ] The variance in `profile.py` is overwritten by each sample instead of accumulating.
- [ ] `bioauth.py` treats digraphs missing from a profile as mean and variance of 0.
- [ ] `bioauth.py` divides by the number of stored profile rows, not by the number of compared digraphs.
- [ ] Digraphs seen once have zero variance, so they match only on the exact same time.
- [ ] Decision text is compared by string, and scores from 0.5 to 0.6 return "Wait".

**Capture**
- [ ] `Digraph.add` pairs consecutive events of any type, so it mixes hold and flight timings under composite string keys.
- [ ] `auth()` in `auth_keyscapt.js` converts `timelog` in place on every call. Older entries get converted again on later requests, which corrupts the timing data.
- [ ] Authentication resends the whole log every 40 events.
- [ ] Key repeat events are not filtered.
- [ ] `keyCode` is deprecated.
- [ ] `cp_keyscapt.js` and `auth_keyscapt.js` hardcode an old server IP.
- [ ] The pages load CSS over plain HTTP from a third party and load an old jQuery version.
- [ ] `keycapture.js` is not loaded by any template.

**Repository**
- [ ] `keystroke.sqlite` is committed. Report its table count and whether its table names look like real people's names. Do not print its contents or put the names in any committed file.

**Done when:** you have given me the checked list with references. Do not commit anything.

**Prompt**
```text
Read docs/plans/done/MODERNIZATION_PLAN.md and carry out Phase 0 only. Do not change any files. Report the audit in the conversation and stop.
```

---

## Phase 1: Project foundation

**Purpose:** create a clean Python 3 project that runs and passes CI, before moving any features.

1. Create `pyproject.toml` with `uv`, and commit `uv.lock`.
2. Create the `src/keystroke_dynamics/` package and an empty `tests/` package.
3. Move the old application to `legacy/` with `git mv`, as a temporary reference. It gets deleted in Phase 7.
4. Add `config.py` using `pydantic-settings`. Include the database URL, session secret, debug flag (default off), host (default `127.0.0.1`), and port (default `8000`).
5. Add `.env.example`. It must contain placeholder values only.
6. Add `GET /health`, which returns `{"status": "ok"}`, and a test for it.
7. Configure `ruff` and strict `mypy` for `src/`. Exclude `legacy/` from tooling.
8. Add a GitHub Actions workflow that runs lint, type checks, and tests on Python 3.12.
9. Update `.gitignore` to cover `.env`, virtual environments, caches, `node_modules`, frontend build output, `*.sqlite`, and downloaded benchmark data.
10. Run `git rm --cached` on `keystroke.sqlite`, wherever it is after the move, without deleting the local copy. Do not rewrite history.

**Done when**
- `uv run pytest` passes.
- `uv run ruff check .` and `uv run ruff format --check .` pass.
- `uv run mypy src` passes.
- `uv run uvicorn keystroke_dynamics.main:app` serves `/health`.
- The database file is no longer tracked.

**Prompt**
```text
Read docs/plans/done/MODERNIZATION_PLAN.md and carry out Phase 1 only. Follow the rules for Claude Code, run the Done when checks, show the results, and stop.
```

---

## Phase 2: Core timing and scoring

**Purpose:** rewrite the logic as pure, tested functions. This is the most important phase. It involves no web or database code.

### Input event format

```python
@dataclass(frozen=True)
class KeyEvent:
    code: str          # KeyboardEvent.code, e.g. "KeyA"
    action: Literal["down", "up"]
    t_ms: float        # Milliseconds, relative to the start of the sample
```

### `core/events.py`

- Reject samples that exceed the configured event limit, have times that go backward, or include unknown actions.
- Pair each keydown with its next keyup by `code`. This must handle overlapping presses, such as A down, B down, A up, B up.
- Drop unmatched events and repeated keydowns for a key that is already held.
- Exclude editing and modifier keys, such as Backspace, Delete, arrows, Shift, Ctrl, Alt, and Meta, from features. Do not let a flight time span across an excluded key.

### `core/features.py`

Produce two explicit feature types, using a typed key instead of a concatenated string:

- **Hold:** key A down to key A up. Key: `("hold", "KeyA")`.
- **Flight:** key A down to next key B down. Key: `("flight", "KeyA", "KeyB")`.

Discard flight values above a configured pause limit (default 2,000 ms), because those are pauses, not typing rhythm.

### `core/stats.py`

Use Welford's algorithm. Store `count`, `mean`, and `m2`. Variance is `m2 / (count - 1)`, and is undefined when `count < 2`. Provide `update()` and a function that combines stats from a batch.

### `core/scoring.py`

Implement scaled Manhattan distance:

1. Compare only features with at least `min_feature_count` profile samples (default 5). Enforce a minimum standard deviation (default 1 ms) to avoid dividing by zero. Never treat a missing feature as zero.
2. For each feature, calculate `abs(sample_mean - profile_mean) / profile_std`.
3. The score is the average across all compared features. Lower means more similar.
4. Require at least `min_compared_features` (default 20, configurable).
5. Return a typed result:

```python
class Decision(StrEnum):
    MATCH = "match"
    NO_MATCH = "no_match"
    INSUFFICIENT_DATA = "insufficient_data"
```

The result also includes the score, threshold, and compared feature count. Keep the threshold in configuration and mark it as provisional until Phase 3 calibrates it.

Also implement a correct version of the old 3-sigma rule as `three_sigma_score`, for comparison in Phase 3 only.

### Required tests

- Welford results match `numpy.mean` and `numpy.var(ddof=1)` on random input, using `hypothesis`.
- Batch statistics do not depend on arrival order.
- Overlapping presses, repeated keydowns, excluded keys, unmatched events, and backward time are each handled as specified.
- A long pause creates no flight feature.
- A missing or low-count feature is excluded from scoring.
- Too few features returns `INSUFFICIENT_DATA`.
- A sample with identical means scores 0.
- A shifted sample scores higher, and the score grows as the shift grows.
- A regression test covers each old statistics bug from Phase 0.

**Done when**
- All Phase 1 checks pass.
- `core/` has at least 95% branch coverage.
- Nothing in `core/` imports a web or database library.

**Prompt**
```text
Read docs/plans/done/MODERNIZATION_PLAN.md and carry out Phase 2 only. Write the tests alongside the implementation, run the Done when checks, show the coverage result, and stop.
```

---

## Phase 3: Benchmark evaluation

**Purpose:** measure the model before building more on top of it.

Use the CMU Keystroke Dynamics Benchmark Data Set (Killourhy & Maxion, 2009): https://www.cs.cmu.edu/~keystroke/

1. Add `evaluation/README.md` with instructions for downloading `DSL-StrongPasswordData.csv` into `evaluation/data/`. Do not commit the dataset. If Claude Code cannot download it, ask me to add it and stop.
2. Add `evaluation/run_benchmark.py`, following the paper's protocol. For each subject:
   - **Training:** that subject's first 200 repetitions
   - **Genuine tests:** that subject's remaining 200 repetitions
   - **Impostor tests:** the first 5 repetitions from each other subject
3. Calculate the equal error rate (EER) for each subject, then report the mean and standard deviation across subjects.
4. Compare the following:
   - scaled Manhattan distance
   - corrected 3-sigma rule
   - plain Manhattan distance
   - the three BioKey 2012 variants defined below
5. Use a fixed random seed wherever randomness is used. Save results to `evaluation/results.md` and a machine-readable JSON file.
6. Choose a provisional threshold with a method you document. Do not report tuned performance from the same data as if it were held out.

### BioKey 2012 method

Implement this in `evaluation/biokey_2012.py`, using NumPy and SciPy. It is for evaluation only and must not be imported by the app. The source is my 2012 thesis, "Біометричний контроль доступу на базі динамічного клавіатурного паролю". Do not add the thesis file to the repository unless I ask.

**Formulas, as written in the thesis:**

```text
(1) har(0,0,t) = 1
    har(r,m,t) =  2^(r/2)  if (m-1)/2^r   <= t < (m-1/2)/2^r
                 -2^(r/2)  if (m-1/2)/2^r <= t < m/2^r
                  0        otherwise
    with 0 <= r <= n-1, 1 <= m <= 2^r, n = log2(N)

(4) V = (1/N) * H(n) * F

(6) min(v_i) = m(v_i) - t[L, 1-P] * sigma(v_i)
    max(v_i) = m(v_i) + t[L, 1-P] * sigma(v_i)

(7) m_j = ((j-1)/j) * m_(j-1) + (1/j) * v_j

(8) var_j = ((j-2)/(j-1)) * var_(j-1) + (1/(j-1)) * (v_j - m_j)^2
```

The intervals in (1) are half-open, and `r` stops at `n-1`. Those two points correct small errors in the thesis text and match its flowchart. Treat `sigma` as the standard deviation.

**Decision score:** set `e_i = 0` if `v_i` is inside its range and `e_i = 1` otherwise. The score is the normalized Hamming distance, `sum(e_i) / N`.

**Variants to compare (all at `P = 0.1`):**

| Variant | Features | Variance | Range multiplier |
|---|---|---|---|
| `biokey_as_written` | Haar | Formula (8) | One-sided `t(1-P, L-1)` |
| `biokey_corrected` | Haar | Exact sample variance (Welford) | Two-sided `t(1-P/2, L-1) * sqrt(1 + 1/L)` |
| `raw_corrected` | Raw timings, no Haar | Exact sample variance (Welford) | Two-sided `t(1-P/2, L-1) * sqrt(1 + 1/L)` |

**Timing signal:** the thesis does not specify how timings become a fixed-length signal, and the original code is not available. Do the following and label it as a reconstruction, not the original method:

1. For each repetition, build the alternating sequence `H, UD, H, UD, ..., H` from the dataset's columns. Leave out `Return` if its timing is not comparable, and document the choice.
2. Resample to `N = 16` samples using linear interpolation.
3. Divide by the sequence's sum so that the signal has a common scale.
4. Report `N = 8` and `N = 32` as sensitivity checks.

Keep the profile fixed during evaluation. Do not apply the thesis's update-after-login step in this benchmark.

**How to report it:**

- Train the BioKey variants on two sizes: the first 200 repetitions (the paper's protocol) and the first 10 repetitions (matching the thesis's enrollment). Use the same genuine and impostor test sets for both.
- Report mean EER and standard deviation across subjects for each variant and training size.
- Report the score distribution for genuine and impostor attempts, and the actual share of genuine values outside their ranges, compared with the intended rate.
- Report false rejections and false acceptances at the thesis's threshold of 0.30. Mark this threshold as taken from the thesis, not tuned here.
- State that the thesis results came from one user, one password, 5 genuine attempts, and 15 impostors. These benchmark results measure a reconstruction on a different dataset, so they do not confirm or reproduce those exact results.

**Required tests (`tests/test_biokey_2012.py`):**

- `H(3)` matches the thesis's matrix:
  ```text
   1    1    1    1    1    1    1    1
   1    1    1    1   -1   -1   -1   -1
  √2   √2  -√2  -√2    0    0    0    0
   0    0    0    0   √2   √2  -√2  -√2
   2   -2    0    0    0    0    0    0
   0    0    2   -2    0    0    0    0
   0    0    0    0    2   -2    0    0
   0    0    0    0    0    0    2   -2
  ```
- `H(n) * H(n)^T` equals `N * I`, and applying `H(n)^T` to `V` recovers `F`.
- Formula (7) matches `numpy.mean`.
- Exact variance matches `numpy.var(ddof=1)`, and formula (8) reproduces a hand-calculated value. For inputs 1 and 3, formula (8) gives 1, while the exact variance is 2.
- The one-sided multiplier matches the thesis's table for spot checks: `L=10, P=0.1` gives 1.38, and `L=5, P=0.05` gives 2.13.
- Hamming scores cover all in-range values, all out-of-range values, and values exactly on a boundary.

**Sanity check:** the paper's scaled Manhattan EER is about 0.10. If the result is far from that, find out why and tell me before going further. Do not tune the code just to match the number.

**Limitation to state in the results:** this dataset uses one fixed password, while the app accepts longer free text. These numbers validate the scoring methods, not how the deployed app performs.

**Done when**
- The script reproduces its results from a clean checkout plus the downloaded data.
- `evaluation/results.md` includes the method, the comparison table, the BioKey findings, the limitation, and the command to reproduce the results.
- It says clearly which BioKey choices come from the thesis and which are reconstruction.
- `tests/test_biokey_2012.py` passes.
- Phase 1 checks pass.

**Prompt**
```text
Read docs/plans/done/MODERNIZATION_PLAN.md and carry out Phase 3 only. Report the EER table, the BioKey as-written versus corrected results, and any difference from the published baseline, then stop.
```

---

## Phase 4: Database and API

**Purpose:** connect the tested core to persistent storage and safe endpoints.

### Schema (through Alembic)

```text
users
  id, username (unique), password_hash, created_at

typing_profiles
  id, user_id (FK, unique), sample_count, created_at, updated_at

profile_features
  profile_id (FK), kind, key_a, key_b (nullable), count, mean, m2
  unique key on (profile_id, kind, key_a, key_b)
```

Handle the nullable `key_b` so that the uniqueness rule works for hold features, for example by storing an empty string or using a partial index.

### Endpoints

| Method | Path | Behavior |
|---|---|---|
| `POST` | `/api/register` | Create a user with a validated username and an Argon2id password hash |
| `POST` | `/api/login` | Check the password, start a session, and return the typing result if a sample is included |
| `POST` | `/api/logout` | End the session |
| `POST` | `/api/profile/samples` | Requires a session. Add a typing sample to the user's own profile |
| `POST` | `/api/profile/verify` | Requires a session. Score a sample against the user's own profile |
| `DELETE` | `/api/profile` | Requires a session. Delete the user's typing profile |

### Security requirements

- **Usernames:** allow only `^[A-Za-z0-9_-]{3,32}$`. Never put a username in a filename or SQL identifier.
- **Queries:** use the SQLAlchemy ORM or bound parameters only.
- **Raw data:** process events in memory. Never persist or log raw events, feature values, or request bodies.
- **Sessions:** use signed, `HttpOnly`, `SameSite=Lax` cookies, and `Secure` outside local development. The secret comes from the environment.
- **CORS:** no CORS middleware; the app is same-origin.
- **CSRF:** require a CSRF token, or strictly verify `Origin`, on all state-changing requests.
- **Limits:** cap request size and event count. Rate-limit login, registration, and verification, in memory per process, and document that limitation.
- **Login errors:** return the same response for an unknown user and a wrong password. Remove the old endpoint that checks whether a username exists.
- **Access:** derive the user only from the session, never from a header or request body.
- **Typing results:** a failed typing check does not reveal the password result and does not by itself lock the account. Return it as a signal in the login response.
- **Enrollment:** adding samples uses the Welford batch update in one transaction, so concurrent requests cannot lose updates.

Use the provisional threshold from Phase 3.

### Required tests

Use a real Postgres instance in tests and CI, through a Compose or Actions service.

- SQL injection and path traversal attempts in usernames are rejected, and the database stays intact.
- User A cannot read, change, or delete user B's profile.
- Unauthenticated profile requests return 401.
- Login responses for an unknown user and a wrong password are identical.
- Oversized and malformed samples are rejected.
- Requests with a bad `Origin` or missing CSRF token are rejected.
- A test confirms no raw events reach the database or application logs.
- Concurrent sample uploads keep the correct count.
- Migrations apply to an empty database and match the models.

**Done when**
- All tests pass locally and in CI.
- `alembic upgrade head` works on an empty database.
- Nothing writes files during a request.

**Prompt**
```text
Read docs/plans/done/MODERNIZATION_PLAN.md and carry out Phase 4 only. Do not build the frontend yet. Run the Done when checks, list each security requirement with the test that covers it, and stop.
```

---

## Phase 5: Frontend

**Purpose:** port the existing pages and replace the capture code with one correct module.

1. Add a TypeScript capture module in `frontend/`, built with Vite into `static/`.
2. Capture `event.code`, the action, and `event.timeStamp`, all relative to the first event in the sample. Ignore events where `event.repeat` is true or `event.isTrusted` is false. Never read or send the typed text.
3. Never mutate recorded data when sending it. Add a unit test that sending twice produces the same values, as a regression test for the old `timelog` bug.
4. Send one sample on submit, or on an explicit check. Do not resend the whole log every 40 events.
5. Port these pages to the new Jinja templates: home, create profile, authenticate, how it works, about, and the finish page.
   - Add password fields.
   - Add a visible delete profile action.
   - Replace `flask_navigation` with plain links.
   - Remove jQuery, inline event handlers, hardcoded IP addresses, and the third-party `w3.css` link. Use local CSS instead.
6. Show `match`, `no_match`, and `insufficient_data` as distinct states, with the score and feature count. Do not rely on color alone.
7. Update the "How it works" page to describe the actual method and its measured limits.
8. Add a clear privacy notice: what is captured, that raw keystrokes are not stored, that timing statistics per key pair are stored, and how to delete them.
9. Add one Playwright end-to-end test that registers, enrolls a sample with scripted keystrokes, logs in, and verifies the result.

**Done when**
- The frontend builds with `npm run build`, and its unit tests pass.
- The Playwright test passes.
- No page sends the typed text, as confirmed by a test that inspects the outgoing request.
- The browser console has no errors on any page.

**Prompt**
```text
Read docs/plans/done/MODERNIZATION_PLAN.md and carry out Phase 5 only. Run the Done when checks, take a screenshot of each main page for review, and stop.
```

---

## Phase 6: Packaging

**Purpose:** let anyone run the project with one command.

1. Add a multi-stage `Dockerfile` that builds the frontend and runs as a non-root user.
2. Add `compose.yaml` with the app and Postgres, including a database health check. Bind published ports to `127.0.0.1`.
3. Run migrations in a separate, explicit Compose step or start command.
4. Fail at startup, outside local development, if the session secret is missing or still the example value.
5. Add a CI step that builds the image and runs the health check against the Compose stack.

**Done when**
- These commands work from a clean clone:
  ```bash
  cp .env.example .env
  docker compose up --build
  ```
- The app starts, migrations apply, and the Playwright flow passes against it.
- The container does not run as root.

**Prompt**
```text
Read docs/plans/done/MODERNIZATION_PLAN.md and carry out Phase 6 only. Test from a clean clone in a temporary directory, run the Done when checks, and stop.
```

---

## Phase 7: Cleanup and final review

**Purpose:** remove the old code, update the documentation, and independently check the result.

1. Delete `legacy/`, `readme.txt`, and every leftover reference to the old IP address and Python 2.
2. Rewrite `README.md` to cover:
   - what the project is, with a clear note that it is a research demo and not a production biometric system
   - quick start
   - an architecture summary
   - the method and benchmark table, linked to `evaluation/results.md`
   - privacy and security notes
   - known limitations
   - how to run the tests
3. Replace `TODO.md` with only the items that are still open.
4. Go through every item from Phase 0 and mark it fixed, with its test, or explain why it is still open.
5. Run dependency and secret checks: `uv run pip-audit`, `npm audit`, and a check that no secrets or real profile data are tracked.
6. Review the full branch diff against `master` as a skeptical reviewer, and report findings ranked by severity. Fix only clear bugs; list anything else for me to decide.

**History decision (mine to make):** `keystroke.sqlite` remains in old git history even after removal, and its table names may include real people's names. Tell me this before finishing. I will decide whether to rewrite history. Do not do it yourself.

**Done when**
- All checks from all phases pass in a clean clone.
- `rg -n "162\.243\.145\.18|flask\.ext|xrange|has_key"` finds nothing outside the plan and the Phase 0 record.
- The Phase 0 list is closed out.

**Prompt**
```text
Read docs/plans/done/MODERNIZATION_PLAN.md and carry out Phase 7 only. Give me the Phase 0 closeout table, audit results, and ranked review findings. Remind me about the git history decision, and stop. Do not push.
```

---

## After all phases

Once you have reviewed the branch:

```bash
git push -u origin modernize
gh pr create --base master --head modernize --fill
```

## Later ideas (not part of this work)

- Passkeys in place of passwords
- Testing BioKey's update-after-login step, including whether an impostor who gets in once can shift the profile
- A consented dataset of free-text typing from the app itself, to measure real-world performance
- Handling a profile drifting as someone's typing changes over time
- Evaluating on mobile touch typing
