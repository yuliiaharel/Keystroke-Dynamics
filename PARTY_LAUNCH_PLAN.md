# Typing Twin Party: Launch Plan

Repository: `yuliiaharel/Keystroke-Dynamics`

## Goal

Launch the party game at a public URL that people can open from LinkedIn and GitHub and start playing immediately.

- Players are anonymous, with no email or password.
- Several people can play on one keyboard.
- Visitors can try to pass as me, or as simulated practice targets.
- The public version runs on one small DigitalOcean App Platform instance with no database.
- The backend scores attempts with the existing `core/` code.

Online rooms come after launch. Do not build them now, but don't make choices that block them.

## How to use this plan

1. Save this file in the repository root as `PARTY_LAUNCH_PLAN.md`.
2. Save the approved mockup as `design/typing-twin-party.html`.
3. Commit or stash any unfinished backend hookup work, so it can't be lost.
4. Run each part in a new Claude Code session using its prompt, and review the result before continuing.

## Rules for Claude Code

1. Read this file, `README.md`, `TODO.md`, and `design/typing-twin-party.html` first.
2. Do only the requested part. Do not start the next one.
3. Work on the `party-launch` branch. Make small commits. Do not push, merge, deploy, or rewrite history unless the part's prompt says to.
4. Check `git status`, local branches, and stashes before changing anything. If I have work in progress on the game, build on it. Never discard it. Ask me if it conflicts with this plan.
5. Treat the mockup as the approved look and behavior. Keep its flow, copy, and visual design unless this plan says otherwise.
6. Write tests with each behavior change. Do not weaken a test or limit to get a pass.
7. Run every check under "Done when" and show the actual results.
8. If the code contradicts this plan, stop and ask me.

## Decisions already made

| Area | Decision |
|---|---|
| Hosting | One DigitalOcean App Platform instance, 1 vCPU and 512 MiB, built from the Dockerfile |
| Database | None in public mode. The app must start and play without Postgres |
| Game state | In memory, with a time limit, and allowed to disappear on restart |
| Identity | A signed session cookie. Generated names by default, with optional renaming |
| Raw keystrokes | Processed during a request, then discarded. Never stored or logged |
| Accounts code | Kept in the repository and tested, but switched off in public mode |
| Scoring | The existing `core/` code, with no second implementation in the browser |
| Sharing | No public directory or global leaderboard |

### Out of scope for now

Do not add online rooms, server-sent events, Redis, a public lobby, a global leaderboard, analytics, or new cloud services.

---

## Part 1: Anonymous party game

### 1. Public mode

Add an `enable_accounts` setting, defaulting to `false`.

When it is `false`:

- Do not mount the registration, login, or profile routes, or the old account pages.
- Do not create a database connection, and do not require `DATABASE_URL`.
- Serve the game at `/`.

When it is `true`, the existing account features and their tests must keep working. CI must cover both modes. Set `enable_accounts=true` in the Compose and test configurations that use Postgres.

### 2. Game state

Add a game module with an in-memory store:

- **Party:** ID, chosen line, players, attempts, and last activity time.
- **Player:** ID, display name, profile statistics, limit, and median timing for the ring and roll. Do not keep raw training lines after enrollment.
- **Attempt:** who typed, target, type, distance, limit, and result.

Make these limits configurable:

| Limit | Default |
|---|---|
| Parties in memory | 500 |
| Players per party | 12 |
| Attempts kept per party | 200 |
| Idle expiry | 2 hours |

Remove expired parties automatically. When the party limit is reached, remove the oldest idle party, or return a clear "try again soon" response if none has expired. Keep the store behind a small interface so rooms can be added later. Run a single worker process, and document why.

### 3. Identity and names

- The first visit starts an anonymous session, with no sign-up form.
- Each party player gets a generated name like "Quiet Otter" and may rename themselves.
- The session cookie identifies the party. Validate party access on the server, and never trust a party or player ID from the browser without checking it belongs to that session.
- Custom names: trim whitespace, 1 to 24 characters, a basic blocked-word list, and no duplicates within a party. Render names as text only, and test HTML in a name.

### 4. Game API

Build these endpoints, adjusting the exact paths if needed:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/game/party` | Create a party on a chosen line |
| `GET` | `/api/game/party` | Read the current party state |
| `POST` | `/api/game/party/reset` | Delete everything and start over |
| `POST` | `/api/game/players` | Create a player from training lines |
| `PATCH` | `/api/game/players/{id}` | Rename a player |
| `DELETE` | `/api/game/players/{id}` | Delete a player and their attempts |
| `POST` | `/api/game/attempts` | Score a typed attempt |
| `POST` | `/api/game/replay` | Run a server-side replay attack |

Apply the existing `Origin` check, body-size limit, event limit, and rate limiting to all state-changing routes. Rate-limit by client IP, including behind DigitalOcean's proxy, and don't trust a client-supplied forwarding header unless the proxy setup makes it safe. Make attempts idempotent if the browser retries.

### 5. Scoring

Reuse `core/events.py`, `core/features.py`, `core/stats.py`, and `core/scoring.py`.

The game trains on far less data than the benchmark, and the current defaults may not fit:

- `min_feature_count` can be too high for 3 to 8 training lines.
- `min_compared_features` is too high for the one-word line, which has about 11 features.
- The minimum standard deviation may be too low for a small sample.
- The benchmark threshold doesn't suit a small personal profile.

Add a game-specific scoring configuration. Do not change the defaults or behavior of the non-game code. As a starting point, use the mockup's rules:

- a minimum of 2 samples per feature
- at least 70% of the line's features compared, up to 20
- a minimum spread of `max(sample standard deviation, 12 ms, 12% of the mean)`
- a per-player limit set from leave-one-line-out scoring: `clamp(highest held-out score * 1.2, 1.3, 3.5)`

Label these values as game tuning in code comments and in `How it works`. Never present the 9.1% benchmark result as the accuracy of this game. Test all three lines (one word, sentence, long line), including that a real game can complete on each.

### 6. Replay attack

Run the replay on the server using the target's median timing, then score it. The browser receives only what it needs to animate the replay. Update the copy so it says the replay uses the target's typical timing.

### 7. Targets

Keep the three simulated practice targets, clearly labeled.

Add support for a permanent target stored as a committed JSON file, such as `src/keystroke_dynamics/game/targets/yuliia.json`, with one entry per line. It holds only the name, the profile statistics, the limit, and median timing, with no raw events.

Add a local-only way for me to record it, available only when `debug=true`, and test that it doesn't exist otherwise. Show "Can you pass as Yuliia?" prominently for any line that has a recording. Before a recording exists, the game must still work without it. Do not invent my data.

### 8. Frontend

Port the mockup to the existing TypeScript and Jinja setup:

- Keep the signature ring, room, attack, scores, and how-it-works views.
- Self-host the fonts and remove third-party requests. Add a strict Content Security Policy with no inline scripts.
- Show the page right away, even if a request is slow, and show a clear message if the app restarted and the party is gone.
- Add a visible **Delete me** action for each player, and keep **New party**.
- On phones, show "Best on a computer", and let visitors explore the sample targets, signatures, and replay without typing.

Replace the privacy text. It must say, in plain language:

- Key timing and key identity for the game line are sent to the server for scoring.
- Raw timings are discarded after scoring. The server keeps a player's timing statistics in memory until they delete themselves, or the party expires or the app restarts.
- Everyone playing in the same party can see names and signatures.
- Nothing is written to a database, and typed text outside the game line isn't accepted.

### 9. Link previews and metadata

Add a page title, description, Open Graph and Twitter tags, and a 1200 x 630 preview image of signature rings. Generate the image from sample data, and label nothing in it as a real person's signature. Use absolute URLs from a new `public_base_url` setting.

**Done when**

- With no `DATABASE_URL`, the app starts and a full game can be played.
- Python and frontend tests, `ruff`, `mypy`, and Playwright all pass.
- Playwright plays a full one-keyboard game: two players, an attack, a replay, a rename, a deletion, and the scores page.
- Tests confirm that:
  - one session cannot access another session's party
  - expired parties are removed, and limits hold
  - raw events aren't kept after requests or written to logs
  - no request goes to a third-party host
  - account routes are absent in public mode and working when enabled
- A short load test against a container limited to 512 MiB, with 100 parties at the player limit, stays within memory. Show peak memory.

**Prompt**

```text
Read PARTY_LAUNCH_PLAN.md and carry out Part 1 only. Check my current branches, stashes, and uncommitted work first, and build on any game hookup already in progress. Run the Done when checks, show the results and peak memory, list anything that needs my decision, and stop. Do not push or deploy.
```

---

## Part 2: Deployment setup

**Purpose:** prepare everything for DigitalOcean. I will do the steps that need my account.

1. Add `.do/app.yaml` defining one Dockerfile-built web service from `master`, with:
   - auto-deploy on push
   - the current 1 vCPU, 512 MiB instance size, one instance
   - `http_port: 8000`, and a health check on `/health`
   - `DEBUG=false`, `ENABLE_ACCOUNTS=false`, `ALLOWED_ORIGIN`, and `PUBLIC_BASE_URL`
   - `SESSION_SECRET` declared as an encrypted secret with no value in the file
2. Check the current spec format, instance slug, and region names against DigitalOcean's documentation. Validate the file with `doctl apps spec validate` if `doctl` is available, otherwise tell me it wasn't validated.
3. Configure Uvicorn for a single worker, and for correct HTTPS and client IP handling behind the platform proxy. Secure cookies and the `Origin` check must work on the live HTTPS URL.
4. Make sure the app fails at startup if `SESSION_SECRET` is missing, or if `ALLOWED_ORIGIN` or `PUBLIC_BASE_URL` are missing outside debug.
5. Make sure CI passes before deploys where the platform allows it. If auto-deploy can't wait for CI, tell me the options rather than choosing one.
6. Add `DEPLOY.md` with the exact steps for me, how to roll back, how to change the domain, and the expected monthly cost.
7. Update `README.md`: a live link placeholder, screenshot, short description, and how public mode differs from account mode.

Never commit real secrets.

**Done when**

- A production-like container runs locally with `DEBUG=false`, no database, and a 512 MiB limit.
- A full game works against that container with HTTPS forwarding headers simulated.
- All Part 1 checks still pass.
- `DEPLOY.md` is clear enough for me to follow without additional help.

**Prompt**

```text
Read PARTY_LAUNCH_PLAN.md and carry out Part 2 only. Do not create a DigitalOcean app, deploy, or push. Run the Done when checks, show the results, give me the exact steps that need my account, and stop.
```

---

## Part 3: My steps

1. Review the `party-launch` branch, then merge it to `master`.
2. Create a DigitalOcean account and connect the GitHub repository.
3. Create the app from `.do/app.yaml`, using a long random `SESSION_SECRET`.
4. After the first deploy, set `ALLOWED_ORIGIN` and `PUBLIC_BASE_URL` to the live URL, and redeploy.
5. Optional: add a custom domain, then update those two settings again.
6. Record my signature locally, commit the file, and let it deploy. Use a line I don't use for anything else, like a password.

---

## Part 4: Live check before sharing

Check all of this on the live URL, in a private window:

- [ ] A full game works on a computer, including attack, replay, rename, deletion, and scores
- [ ] "Can you pass as Yuliia?" works
- [ ] On a phone, the sample room, signatures, and replay work, and the keyboard note appears
- [ ] The app opens inside LinkedIn's mobile app
- [ ] The LinkedIn Post Inspector shows the right title, description, and image
- [ ] Cookies are `Secure` and `HttpOnly`
- [ ] Browser developer tools show no third-party requests and no console errors
- [ ] The logs contain no keystroke data
- [ ] Restarting the app shows the friendly "party is gone" message
- [ ] The repository's About section and README link to the live site
- [ ] Friends with different keyboards have played, and the limits feel right

---

## After launch

1. Private room links, with results updating on refresh.
2. Live updates through server-sent events, a shared Scores page, and an expiry notice.
