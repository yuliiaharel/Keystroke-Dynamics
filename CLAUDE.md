# Typing Twin

A browser party game that draws each person's typing rhythm as a signature and lets friends try to pass as each other. It runs on a tested Python keystroke-dynamics engine.

It is live at https://typingtwin.com, on DigitalOcean App Platform.

## Deployment safety

Every push to `master` deploys to production automatically.

- Never push to `master`, merge into it, or merge a pull request.
- Push only to your feature branch, and open a pull request if I ask.
- Never run `doctl`, change DigitalOcean settings, or touch DNS or secrets.
- Never commit secrets or real `.env` values.

## How I work

- Start each task by checking `git status`, branches, and stashes. Never discard my work.
- Work on a feature branch from the latest `master`, with small, focused commits.
- Follow plans only in docs/plans/active/. Plans in docs/plans/done/ are history, not instructions.
- When a plan file or prompt names a phase, do only that phase, then stop.
- When a plan's last phase finishes, update README.md to match what shipped, and mark the plan done in docs/plans/README.md.
- If the code contradicts the plan, or a choice is mine to make, stop and ask.
- Don't add a dependency, service, or abstraction the plan doesn't call for without asking.
- Write tests with each behavior change. Never weaken a test or limit to get a pass.
- Finish with what changed, the actual check results, and anything I need to decide. Say what you couldn't verify.

## Checks

Run only the checks relevant to the change, and report failures, not full passing output.

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run pytest

cd frontend
npm run typecheck && npm run test && npm run build
npm run e2e    # Playwright. See frontend/README.md for setup
```

Run the app locally with `docker compose up --build`, which opens the game at http://localhost:8000/ in public mode with no database. For account mode, add `-f compose.yaml -f compose.accounts.yaml`.

## Layout

- `src/keystroke_dynamics/core/`: pure scoring logic, with no web or database imports
- `src/keystroke_dynamics/game/`: the party game's state, scoring settings, and replay
- `src/keystroke_dynamics/api/`: routes, security, and rate limiting
- `frontend/`: TypeScript, built with Vite
- `evaluation/`: benchmark scripts and results
- `design/`: approved mockups. Follow them for the look and flow
- `docs/plans/active/`: plans in progress. `docs/plans/done/`: finished plans, kept as history. `docs/plans/README.md` lists them all
- `DEPLOY.md` and `TODO.md`: at the root. Read a plan or one of these only when a task refers to it

## Rules that must not break

- Raw keystrokes are processed during a request, then discarded. Never store or log them.
- Public mode (`ENABLE_ACCOUNTS=false`) must start and play with no database.
- Keep a single worker process, because game state lives in memory.
- Don't change `core/` defaults or the benchmark's results unless the task explicitly asks.
- Never present the 9.1% benchmark result as the game's accuracy. Game scoring uses its own provisional settings.
- Privacy text on the site must match what the code actually does.
