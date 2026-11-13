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
npm run og-image      # regenerate static/img/party-preview.png
```

The built JS must exist before the backend can serve any page, Party
included -- run `npm run build` at least once after a fresh clone, and
again after editing anything in `src/`.

`npm run og-image` screenshots `scripts/og-image.html` (three
decorative signature rings, drawn from the same deterministic sample
data the party page's own intro view uses) with the chromium build
Playwright already bundles, rather than adding an image library just
for this one static asset. The committed PNG only needs regenerating
if that ring drawing or the sample data changes.

## End-to-end tests

`npm run e2e` drives a real running app against a real Postgres -- it
does not start either for you. Before running it:

```bash
# from the repo root
docker compose -f docker-compose.test.yml up -d
uv run alembic upgrade head
ENABLE_ACCOUNTS=true RATE_LIMIT_MAX_ATTEMPTS=50 \
  uv run uvicorn keystroke_dynamics.main:app --host 127.0.0.1 --port 8000
```

`ENABLE_ACCOUNTS=true` mounts the account system (register/login/
profile, and the account pages) -- `flow.spec.ts`,
`no-typed-text-sent.spec.ts`, `retry-resets-capture.spec.ts`, and
`screenshots.spec.ts` all need it; it's `false` by default
(public-launch mode, no database). `party.spec.ts` and
`no-third-party-requests.spec.ts` run either way, since the
anonymous game has no such flag.

`RATE_LIMIT_MAX_ATTEMPTS` (an existing, already environment-configurable
setting -- see `.env.example`) is raised here only for this one locally-run
dev server, not the app's actual default (still 10, unchanged). The full
suite's own login/register traffic, across every spec file, legitimately
exceeds the production default's 10-per-60s budget -- that default is
tuned for a real user, not an automated suite exercising several accounts
back to back (playwright.config.ts already pins `workers: 1`, since the
suite shares this one server process and its rate limiters are in-memory,
global, and keyed by client IP; `workers: 1` only fixes collisions between
*parallel* spec files, not the suite's own cumulative volume run serially).

The game has its own limit, `GAME_RATE_LIMIT_MAX_ATTEMPTS` (20 per minute
per client), and joining a room by its code has another,
`GAME_JOIN_RATE_LIMIT_MAX_ATTEMPTS` (also 20 per minute). Each spec fits
inside them, but not all in the same minute (`rooms.spec.ts` alone fills a
room to its limit), so add `GAME_RATE_LIMIT_MAX_ATTEMPTS=200
GAME_JOIN_RATE_LIMIT_MAX_ATTEMPTS=200` to the command above when running the
whole suite.

`rooms.spec.ts` plays one room from several browser contexts, each its own
member of the room. `room-screenshots.spec.ts` saves the room header, join
step, and ended page to `screenshots/`, on a desktop and on a phone.

### The touch game

The `touch-*.spec.ts` files play the phone game
(`docs/plans/active/MOBILE_PLAN.md` Phase 2) with emulated touches: Chromium's
`Input.dispatchTouchEvent`, which the browser turns into the trusted
`pointerType: "touch"` events the game listens for. `touch-helpers.ts` holds
the shared tapping. They need nothing beyond the setup above.

- `touch-party.spec.ts`: a full game on one phone.
- `touch-rooms.spec.ts`: two phones in one room, each its own browser context.
- `touch-watching.spec.ts`: a phone in a keyboard room, a computer in a touch
  room, and a touchscreen laptop choosing between the two keyboards.
- `touch-input.spec.ts`: overlapping fingers, a canceled touch, wrong keys, a
  mouse, rotation, and a line interrupted by switching apps or losing the
  connection.
- `touch-privacy.spec.ts`: what a phone game sends, and no sideways scroll at
  320, 390, and 430 px.
- `touch-screenshots.spec.ts`: saves each main phone view to `screenshots/` at
  390 px, in the light and the dark theme.

This is emulation. It proves the page's own logic, not how a real phone's
browser delivers touches, which is what Phase 3 of that plan checks by hand.
The local server runs with `DEBUG=true`, where a mouse may stand in for a
finger on the on-page keyboard; `touch-input.spec.ts` removes that mark to
check that the deployed site refuses one.

Then, in another terminal, from `frontend/`: `npm run e2e`. Override
the target with `E2E_BASE_URL` if the app is running somewhere other
than `http://127.0.0.1:8000`.

### Visitor-counting tests

`npm run e2e:analytics` is a separate suite (`e2e-analytics/`,
`playwright.analytics.config.ts`). It starts its own server on port
8137 in public mode, with no database and a made-up
`GOATCOUNTER_SITE_CODE`, so it can run alongside the main suite. The
main suite's server must never have a site code set. Nothing reaches
GoatCounter: the script is served from a pinned copy
(`e2e-analytics/fixtures/count.js`) and the count request is
intercepted. Refresh that copy from `https://gc.zgo.at/count.js` if
GoatCounter changes its script.

## Layout

- `src/analytics.ts` -- decides what GoatCounter is told about a page
  view (see `docs/plans/active/ANALYTICS_PLAN.md`). Does nothing unless
  the page was served with the snippet.

- `src/capture.ts` -- records key timing (`event.code`, action, and a
  timestamp relative to the first event in the sample). Never reads
  `event.key` or any textarea value, so the typed text itself is never
  captured. Shared by every page below.
- `src/api.ts` -- thin `fetch` wrappers for the account system's JSON API.
- `src/game-api.ts` -- thin `fetch` wrappers for the party game's JSON API
  (`/api/game/*`).
- `src/live.ts` -- keeps a room on screen current: listens to the event
  stream (`/api/game/room/events`), and polls the room when the stream
  fails. See `docs/plans/active/ROOMS_PLAN.md` Phase 2.
- `src/room.ts` -- room links and codes: reading `/r/<code>`, showing a
  code as `ABCD-EFGH`, and naming why a join was refused.
- `src/device.ts` -- whether this browser plays by tapping (a phone) or by
  typing (a computer), which is what it reports when it creates or joins a
  room.
- `src/tap-line.ts` -- one line tapped on the on-page keyboard: which key is
  expected, what each finger did, and the events sent for scoring. Pure, like
  `capture.ts`: key codes, timing, and where on the key a finger landed, never
  text.
- `src/touch-keyboard.ts` -- the on-page keyboard's elements and pointer
  events. Never a text input, so a phone's own keyboard stays closed.
- `src/tap-map.ts` -- draws where a player's taps land, and names what stood
  out in a tapped line. Display only: scores always come from the server.
- `src/ui.ts` -- small DOM helpers shared by the account pages.
- `src/pages/create-profile.ts`, `src/pages/authenticate.ts` -- the
  account system's two page-specific entry points.
- `src/pages/party.ts` -- the party game's own entry point (ported from
  `design/typing-twin-party.html`; see `docs/plans/done/PARTY_LAUNCH_PLAN.md`).
  Also the touch game, for a phone (ported from
  `design/typing-twin-touch.html`; see `docs/plans/active/MOBILE_PLAN.md`
  Phase 2).
- `src/touch-capture.ts`, `src/pages/touch-capture.ts` -- the debug-only
  touch capture test page (`/debug/touch-capture`, `DEBUG=true` only; see
  `docs/touch-capture-testing.md`). `e2e/touch-capture.spec.ts` drives it
  with emulated touches and needs the app running with `DEBUG=true`.
- `scripts/og-image.html`, `scripts/generate-og-image.mjs` -- generates
  `static/img/party-preview.png` (`npm run og-image`).
- `e2e/` -- Playwright specs.
