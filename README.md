# Keystroke Dynamics

A demo app built around one idea: *how* you type is a signal, not just
*what* you type. The same scoring engine runs two things:

- **Typing Twin Party** -- an anonymous party game. Type a line a few
  times, see your rhythm drawn as a signature, then try to pass as your
  friends on one keyboard. No accounts, no database. This is what a
  visitor sees by default.
- **The account-based demo** -- register, build a typing profile, and log
  in with your password plus your typing as a second signal. Off by
  default; see [Running the account-based demo too](#running-the-account-based-demo-too).

**This is a research/demo project, not a production biometric system.** Its
measured accuracy (see [Method and results](#method-and-results) below) is
good enough to illustrate the idea, not to gate access to anything that
matters on its own. See [Known limitations](#known-limitations).

Originally a 2018 Python 2/Flask class project; rewritten from scratch in
Python 3 following [`MODERNIZATION_PLAN.md`](MODERNIZATION_PLAN.md), which
also has the full phase-by-phase history of that rewrite. The party game
was added later -- see [`PARTY_LAUNCH_PLAN.md`](PARTY_LAUNCH_PLAN.md).

## Quick start

With [Docker Compose](https://docs.docker.com/compose/):

```bash
docker compose up --build
```

Then open <http://127.0.0.1:8000> -- Typing Twin Party. No Postgres, no
`.env` file, nothing else to install.

### Running the account-based demo too

Needs Postgres, off by default. Layer `compose.accounts.yaml` on top:

```bash
cp .env.example .env
docker compose -f compose.yaml -f compose.accounts.yaml up --build
```

<http://127.0.0.1:8000> is now the account system's home page, and the
game moves to <http://127.0.0.1:8000/party> (see
[Party mode](#party-mode) below for why).

### Running without Docker

Requires Python 3.12+ ([`uv`](https://docs.astral.sh/uv/)) and Node.js 22+.

```bash
uv sync
cd frontend && npm install && npm run build && cd ..
uv run uvicorn keystroke_dynamics.main:app --reload
```

Opens the same Typing Twin Party at <http://127.0.0.1:8000>, no Postgres
needed. For the account-based demo too, additionally need a Postgres
instance:

```bash
cp .env.example .env               # edit DATABASE_URL, set ENABLE_ACCOUNTS=true
uv run alembic upgrade head
uv run uvicorn keystroke_dynamics.main:app --reload
```

## Architecture

- **Backend**: FastAPI (sync routes), Pydantic v2 for request/response
  validation, Jinja2 for server-rendered pages. SQLAlchemy 2 + Alembic
  against Postgres, with three shared tables (`users`, `typing_profiles`,
  `profile_features`) -- no per-user tables.
- **Frontend**: server-rendered HTML + local CSS, plus one small TypeScript
  module (built with Vite) that captures key timing. No jQuery, no SPA
  framework.
- **Scoring**: pure, dependency-free Python in `src/keystroke_dynamics/core/`
  -- event validation and pairing, hold/flight feature extraction, Welford's
  online algorithm for running statistics, and the scaled-Manhattan-distance
  scorer. None of it touches the database, HTTP, or the frontend, so it's
  tested in complete isolation (`tests/core/`).
- **Auth**: Argon2id password hashes, signed HttpOnly session cookies
  (Starlette's `SessionMiddleware`). Typing is a signal alongside the
  password, never a replacement for it.

```
src/keystroke_dynamics/
  core/        pure scoring logic (events, features, stats, scoring)
  db/          SQLAlchemy models and queries
  api/         FastAPI routes, auth, rate limiting, request schemas
  game/        the anonymous party game's own store/scoring/targets
  templates/   Jinja2 pages
  static/      local CSS + the built frontend JS
frontend/      TypeScript capture module, Vite build, Playwright e2e tests
migrations/    Alembic
evaluation/    accuracy benchmark against a public dataset
scripts/       one-off tooling (the party game's load test, its OG image)
tests/         pytest (core, api, db, game) -- see "Running the tests" below
```

### Party mode

`ENABLE_ACCOUNTS=false` (the default -- see `.env.example`) is public
mode: Typing Twin Party, and nothing else, at `/`. No registration/login/
profile routes, no account pages, no database connection of any kind --
a few friends type on one keyboard and get scored by the same `core/`
engine above, under a signed session cookie instead of an account.
`ENABLE_ACCOUNTS=true` mounts the account system too, and the game moves
to `/party` so it doesn't collide with the account system's own home
page at `/`. See [`PARTY_LAUNCH_PLAN.md`](PARTY_LAUNCH_PLAN.md) for the
full design and `src/keystroke_dynamics/game/` for the implementation.

## Method and results

Hold time (key down to key up) and flight time (key up to next key down) are
extracted for each key and key pair. The server keeps a running mean and
variance per feature (Welford's algorithm) -- never the raw timestamps they
came from. To score a sample, each feature is compared to its stored mean,
scaled by that feature's own standard deviation (scaled Manhattan distance);
the average distance across compared features determines match / no-match /
insufficient-data. The running app explains this in two places: Party's own
How it works tab (public mode, `/`), tuned for a handful of training
lines, and `/how-it-works` with the account system enabled, describing
the full benchmark-calibrated method below.

This was evaluated against the CMU Keystroke Dynamics Benchmark Data Set
(Killourhy & Maxion, 2009), reaching a **mean equal error rate of about
9%**, close to the ~10% the original paper reports for a comparable method.
Full method, numbers, and how to reproduce them:
[`evaluation/results.md`](evaluation/results.md).

## Privacy and security notes

- Raw keystroke events are processed in memory only -- never written to
  disk, the database, or logs. Only derived statistics (count, mean,
  variance) per key/key-pair are stored.
- Passwords are hashed with Argon2id. A failed typing check is returned as
  a signal alongside login; it never fails login or locks an account by
  itself, and never reveals whether the password was the thing that failed.
- Login responses are identical for an unknown username and a wrong
  password -- no username-enumeration endpoint exists.
- Sessions are signed, `HttpOnly`, `SameSite=Lax` cookies (`Secure` outside
  local development). No CORS middleware; the app is same-origin only, and
  every state-changing request is checked against the `Origin` header.
- Request size and event count are capped; login, registration, and typing
  verification are rate-limited (in-memory, per process -- see
  `src/keystroke_dynamics/api/rate_limit.py` for that limitation's exact
  scope).
- You can delete your typing profile (the statistics, not raw data, since
  none is kept) at any time from the Authenticate page.
- **Typing Twin Party** (public mode, `/`) has its own, separate identity
  model: a signed session cookie names your *party*, not an account. A
  party's players, attempts, and generated names live in memory only --
  no database, ever, in this mode -- and disappear when the party is
  deleted, expires (2 hours idle), or the process restarts. See the
  game's own How it works tab, or
  [`PARTY_LAUNCH_PLAN.md`](PARTY_LAUNCH_PLAN.md), for the full model.

## Known limitations

- **Measured accuracy is for one fixed password typed many times**, not the
  app's actual free-text passages -- see `evaluation/results.md`'s own
  Limitation section. The provisional match threshold is calibrated on that
  benchmark, not independently validated.
- **Rate limiting is in-memory and per-process.** It resets on restart and
  does not share state across multiple app instances/workers.
- Out of scope by design: microservices, message queues, Kubernetes, a
  separate frontend app, passkeys, cloud deployment. See
  `MODERNIZATION_PLAN.md`.
- See [`TODO.md`](TODO.md) for anything still open.

## Running the tests

Backend (needs a real Postgres -- `docker compose -f docker-compose.test.yml
up -d` starts a disposable one):

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

Frontend:

```bash
cd frontend
npm run typecheck
npm run test     # unit tests (vitest)
npm run build
npm run e2e       # Playwright, against a running app + Postgres -- see frontend/README.md
```
