# Keystroke Dynamics

A demo web app that uses *how* you type, not just *what* you type, as an
additional login signal. You create a profile by typing a passage of text;
the app learns the timing between your key presses. Later, typing the same
way is scored alongside your password at login.

**This is a research/demo project, not a production biometric system.** Its
measured accuracy (see [Method and results](#method-and-results) below) is
good enough to illustrate the idea, not to gate access to anything that
matters on its own. See [Known limitations](#known-limitations).

Originally a 2018 Python 2/Flask class project; rewritten from scratch in
Python 3 following [`MODERNIZATION_PLAN.md`](MODERNIZATION_PLAN.md), which
also has the full phase-by-phase history of that rewrite.

## Quick start

With [Docker Compose](https://docs.docker.com/compose/):

```bash
cp .env.example .env
docker compose up --build
```

Then open <http://127.0.0.1:8000>. This builds the frontend, starts
Postgres, runs migrations, and starts the app -- one command, nothing else
to install.

### Running without Docker

Requires Python 3.12+ ([`uv`](https://docs.astral.sh/uv/)), Node.js 22+, and
a Postgres instance.

```bash
cp .env.example .env               # edit DATABASE_URL to point at your Postgres
uv sync
cd frontend && npm install && npm run build && cd ..
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

`ENABLE_ACCOUNTS=false` (the default -- see `.env.example`) turns this
into a different app: an anonymous, no-database party game at `/`, where
a few friends on one keyboard try to type like each other and get scored
by the same `core/` engine above, under a signed session cookie instead
of an account. `ENABLE_ACCOUNTS=true` runs both at once (the game moves
to `/party`). See [`PARTY_LAUNCH_PLAN.md`](PARTY_LAUNCH_PLAN.md) for the
full design and `src/keystroke_dynamics/game/` for the implementation.

## Method and results

Hold time (key down to key up) and flight time (key up to next key down) are
extracted for each key and key pair. The server keeps a running mean and
variance per feature (Welford's algorithm) -- never the raw timestamps they
came from. To score a sample, each feature is compared to its stored mean,
scaled by that feature's own standard deviation (scaled Manhattan distance);
the average distance across compared features determines match / no-match /
insufficient-data. See [`/how-it-works`](http://127.0.0.1:8000/how-it-works)
in the running app for the full description.

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
- **[Typing Twin](http://127.0.0.1:8000/typing-twin)** is a multiplayer
  party game built on top of the real scoring engine above (not a separate
  toy): each real player gets a random, disposable account, enrolled and
  scored through the same endpoints the rest of the app uses. Attacking
  another player works without any new backend capability -- the page
  silently logs in as whichever player is the *target* right before
  scoring an attempt, since the backend only ever checks whoever is
  actually logged in, never a header or request field. The three
  "simulated" practice players are explicitly fake data and never touch
  the backend. "New party" deletes every real player's profile. See
  `TODO.md` for the one place its disposable accounts outlive the party.

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
