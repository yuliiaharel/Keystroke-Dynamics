# The account-based demo

The repository's older demo: register, build a typing profile, and log in with a password plus your typing as a second signal. It uses the same scoring code as the game. It's off by default and off on the live site.

## Run it

It needs Postgres. With Docker Compose, layer `compose.accounts.yaml` on top:

```bash
cp .env.example .env
docker compose -f compose.yaml -f compose.accounts.yaml up --build
```

<http://127.0.0.1:8000> is then the account system's home page, and the game moves to <http://127.0.0.1:8000/party>, so the two don't collide at `/`.

Without Docker, after the steps in the main README:

```bash
cp .env.example .env               # edit DATABASE_URL, set ENABLE_ACCOUNTS=true
uv run alembic upgrade head
uv run uvicorn keystroke_dynamics.main:app --reload
```

## How it's built

- `ENABLE_ACCOUNTS=true` mounts the register, login, and profile routes and the account pages. With it `false`, none of them exist and the app opens no database connection.
- Postgres through SQLAlchemy 2 and Alembic, with three shared tables: `users`, `typing_profiles`, and `profile_features`.
- The server keeps a running count, mean, and variance for each timing (Welford's algorithm). It never stores the raw timestamps they came from.
- A sample is scored against the profile with the benchmark-calibrated threshold from `evaluation/results.md`. The result is match, no match, or not enough data.
- The `/how-it-works` page in this mode explains the method.

## Privacy and security

- Raw keystroke events are processed in memory, and never written to disk, the database, or logs.
- Passwords are hashed with Argon2id.
- A failed typing check is returned as a signal next to login. It never fails a login or locks an account by itself.
- Login responses are the same for an unknown username and a wrong password, and no endpoint reveals whether a username exists.
- Sessions use signed, `HttpOnly`, `SameSite=Lax` cookies, and `Secure` outside local development.
- Login, registration, and typing verification are rate-limited. The limiter is in memory and per process: it resets on restart and isn't shared between instances. See `src/keystroke_dynamics/api/rate_limit.py`.
- You can delete your typing profile at any time from the Authenticate page.

## Limits

- The measured accuracy is for one fixed password typed many times, not the free text this demo accepts. The match threshold is calibrated on that benchmark and hasn't been validated independently.
- Open items are in [`TODO.md`](../TODO.md).
- The plan this demo was built from is [`docs/plans/done/MODERNIZATION_PLAN.md`](plans/done/MODERNIZATION_PLAN.md).
