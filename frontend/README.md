# Frontend

A small TypeScript capture module and the per-page scripts that use it,
built with Vite straight into `../src/keystroke_dynamics/static/js/`
(gitignored -- a build artifact, rebuilt from source, not committed).

## Commands

```bash
npm install          # once
npm run build         # build the capture module + page scripts into static/js
npm run test          # unit tests (vitest + jsdom)
npm run typecheck     # tsc --noEmit
npm run e2e           # Playwright end-to-end tests
```

The built JS must exist before the backend can serve the create-profile
and authenticate pages -- run `npm run build` at least once after a
fresh clone, and again after editing anything in `src/`.

## End-to-end tests

`npm run e2e` drives a real running app against a real Postgres -- it
does not start either for you. Before running it:

```bash
# from the repo root
docker compose -f docker-compose.test.yml up -d
uv run alembic upgrade head
uv run uvicorn keystroke_dynamics.main:app --host 127.0.0.1 --port 8000
```

Then, in another terminal, from `frontend/`: `npm run e2e`. Override
the target with `E2E_BASE_URL` if the app is running somewhere other
than `http://127.0.0.1:8000`.

## Layout

- `src/capture.ts` -- records key timing (`event.code`, action, and a
  timestamp relative to the first event in the sample). Never reads
  `event.key` or any textarea value, so the typed text itself is never
  captured.
- `src/api.ts` -- thin `fetch` wrappers for the JSON API.
- `src/ui.ts` -- small DOM helpers shared by both pages.
- `src/pages/create-profile.ts`, `src/pages/authenticate.ts` -- the two
  page-specific entry points Vite builds.
- `e2e/` -- Playwright specs.
