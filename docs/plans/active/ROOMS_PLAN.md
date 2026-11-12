# Typing Twin: Shareable Rooms Plan

> **Status: Active, Phases 1 to 3 built.** As of 2026-11-10 Phase 1 (rooms in the backend), Phase 2 (live updates), and Phase 3 (the room experience: links, joining, host controls) are on the `rooms` branch, not merged. Phase 4 (launch readiness) is next. On the live site the event stream needs DigitalOcean's edge caching turned off; until then the page falls back to polling. The stats bug this plan says to fix first was merged in pull request #11.

Repository: `yuliiaharel/Keystroke-Dynamics`

## Goal

Let someone start a room, share its link, and have friends join from their own computers and play together live.

- Opening a room link drops a visitor straight into that room, with no sign-up.
- Everyone in the room sees new signatures, attacks, and scores appear without refreshing.
- Several people can still share one keyboard, as today.
- This must be ready and tested before the public announcement and LinkedIn post.

## Starting point

Checked against `master` at commit `5bb3ac1`.

- Each browser session has one private party, stored in memory on one app instance. The session cookie holds `party_id`, and every route checks it through `_party_for_session`.
- The store sits behind a small `GameStore` interface that was designed for this change.
- The URL is always `typingtwin.com`, with no room link.
- **Known bug to fix first:** the reveal screen's stats show "undefined". It has its own fix and pull request, separate from this plan.

## How to use this plan

1. Save this file in the repository as `docs/plans/active/ROOMS_PLAN.md`, and commit it.
2. Merge the stats bug fix first.
3. Run each phase in a new Claude Code session, using its prompt, and review the result before continuing.

## Rules for Claude Code

1. Follow `CLAUDE.md`. Read this file and the parts of `docs/plans/done/PARTY_LAUNCH_PLAN.md` it points to.
2. Work on the `rooms` branch from the latest `master`. Push the branch after each phase. Never push to or merge into `master`, because that deploys.
3. Do only the requested phase.
4. Keep everything that works today working, including one-keyboard play and the scoring results.
5. Write tests with each behavior change, run the "Done when" checks, and report actual results.
6. If the code contradicts this plan, stop and ask me.

## Decisions already made

| Area | Decision |
|---|---|
| Room link | `https://typingtwin.com/r/<code>`, with an 8-character code from an unambiguous alphabet, shown as `ABCD-EFGH` |
| Who can join | Anyone with the link. The link is the only key, so it must be hard to guess |
| Identity | Anonymous, as today. Each browser that joins becomes a room member |
| Ownership | A member can type as, rename, or delete only the players they created. Anyone can attack any player |
| Host | The member who created the room. They can remove players, lock the room to new joiners, and end the room |
| Live updates | Server-sent events that tell browsers "the room changed", followed by a normal state request. Fall back to polling if the event stream fails |
| Storage | In memory on the single app instance, as today. No Redis or database for rooms |
| One room per browser | Joining another room leaves the current one, after a confirmation |
| Device types | Every member records `keyboard` for now. The design must let mobile add `touch` later, with no attacks across device types |

### Out of scope

Do not add accounts, a public room list, a global leaderboard, chat, invitations by email, multiple app instances, Redis, or a native app.

## Open decisions

My recommendation comes first. Claude Code should use these unless I change them.

1. **Room size:** 12 players and 12 member browsers, the current party limit.
2. **Idle expiry:** 2 hours, the current party expiry.
3. **Attacks between keyboards:** allowed, and labeled "different keyboard" on results and in scores, because a different keyboard can change timing.
4. **Starting point:** "Start a party" creates a room right away. The room link appears in the room, with a copy button, so solo play needs no extra step.

---

## Phase 1: Rooms in the backend

### 1. Data model

Rename `Party` to `Room` only if it's a small, safe change. Otherwise keep the name in code and call it a room everywhere users see it.

Add to each room:

- `code`: 8 characters from `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`, generated with `secrets`, unique among live rooms
- `members`: member ID, created time, last seen time, and `device_type`
- `host_member_id`
- `locked`
- `version`: a counter that increases on every change, for live updates

Each player records `owner_member_id`. Attempts record whether the typist and target belong to the same member, as `same_keyboard`.

### 2. Sessions

- The session holds `room_id` and `member_id`, both random and server-generated.
- Every route checks that this member belongs to this room.
- A member may only enroll, rename, delete, or type as their own players. Attempts typed by a "Guest" are tied to the member who sent them.
- Remove the session's link to a room when the member leaves or is removed, or the room ends.

### 3. Endpoints

Adjust paths to fit the existing API.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/game/rooms` | Create a room and join it as host |
| `POST` | `/api/game/rooms/{code}/join` | Join by code |
| `POST` | `/api/game/rooms/leave` | Leave the current room |
| `GET` | `/api/game/room` | Read the current room, including its `version` |
| `POST` | `/api/game/room/lock` | Host only: lock or unlock new joiners |
| `DELETE` | `/api/game/room/players/{id}` | Your own players, or any player for the host |
| `POST` | `/api/game/room/end` | Host only: end the room for everyone |
| `GET` | `/r/{code}` | Serve the game page for that room |

Keep the existing player, attempt, and replay endpoints, now scoped to the session's room.

### 4. Safety

- Rate-limit joins and failed code lookups per client IP, so codes can't be guessed. Use the existing `client_ip()`.
- Return the same response for an unknown, expired, or ended room code.
- Locked or full rooms return a clear message.
- Normalize codes, so lowercase input and a missing dash work.
- Enforce the room, member, player, and attempt limits.
- Don't log full room codes in application logs.
- Keep every existing check: `Origin`, body size, event limits, and HTML-safe names.

### 5. Scores

- Add a migration in `migrations_scores/` with a nullable `same_keyboard` boolean column. Never edit the existing migration.
- Fill it for new rows. Scores are saved automatically for every attempt, with no opt-in. Keep that unchanged.
- Update `evaluation/analyze_scores.py` to split attacks by `same_keyboard`.
- Increase `SCORING_VERSION` only if scoring itself changes. It shouldn't here.

**Done when**

- Unit and API tests cover:
  - creating, joining, leaving, locking, ending, and expiry
  - a member trying to rename, delete, or type as another member's player
  - a removed member or ended room losing access
  - unknown, ended, and expired codes giving identical responses
  - join rate limiting
  - code format, normalization, and uniqueness
  - room and member limits
  - `same_keyboard` on attempts and in stored scores
- The new migration applies to a real Postgres copy of the current schema, and existing rows survive.
- All existing game tests pass, adjusted only where sessions became rooms.
- `ruff`, `mypy`, and `pytest` pass.

**Prompt**

```text
Read docs/plans/active/ROOMS_PLAN.md and carry out Phase 1 only. Do not change the frontend yet. Run the Done when checks, list each permission rule with the test that covers it, list anything that needs my decision, push the branch, and stop.
```

---

## Phase 2: Live updates

### 1. Event stream

- Add `GET /api/game/room/events`, a server-sent event stream for the session's room.
- Send only `{"version": N}` or `{"ended": true}`, never names, scores, or timings. Browsers then fetch `/api/game/room` as usual, so the existing access checks still apply.
- Send a heartbeat comment every 20 seconds, so proxies keep the connection open.
- Close streams when a member leaves or is removed, or the room ends or expires.
- Cap open streams at 3 per member and 300 in total, and return a clear error past the cap.
- Use async code for the stream, so it doesn't hold a worker thread.

### 2. Fallback

- If the stream fails or is blocked, poll `/api/game/room` every 5 seconds while the page is visible, and every 30 seconds while hidden.
- Combine updates that arrive close together into one request.

### 3. Hosting check

DigitalOcean's edge proxy may buffer or time out streaming responses. Check DigitalOcean's documentation, and set headers like `Cache-Control: no-cache` and `X-Accel-Buffering: no` if they help. Add `scripts/check_live_events.sh`, which I run against the live site to confirm events arrive within 2 seconds and the connection survives 5 minutes. If streaming can't work there, polling must be good enough on its own.

**Done when**

- Tests confirm that events fire on every change, ended and removed members are disconnected, caps hold, and the stream never includes room data.
- A local test with two browsers sees each other's changes within 2 seconds, through both the stream and polling.
- The 512 MiB load test, extended to 300 open streams across 50 rooms, stays within memory. Show peak memory.

**Prompt**

```text
Read docs/plans/active/ROOMS_PLAN.md and carry out Phase 2 only. Run the Done when checks, show the peak memory, push the branch, and stop. Do not run anything against the live site.
```

---

## Phase 3: Room experience

### 1. Flow

- **Start:** "Start a party" creates a room and opens `/r/<code>`.
- **Room header:** shows the code, a **Copy link** button, and a short note: "Anyone with this link can join and see names and signatures."
- **Joining:** opening a room link joins it immediately and goes to the name step, or straight to the room for a returning member.
- **Another room:** if the browser is already in a different room, ask "Leave your current room and join this one?" first.
- **Presence:** each player card shows whether it's on this keyboard or another one, and new players appear live.
- **Results:** attacks from another keyboard show a small "different keyboard" note.
- **Host controls:** lock or unlock the room, remove a player, and end the room, each with an in-page confirmation.
- **Leaving:** a **Leave room** action. **New party** becomes **New room**.
- **Ended or expired:** a clear page that says the room ended and offers **Start your own room**. The same page appears after an app restart.
- **Who's typing:** lists only this browser's own players, plus Guest.
- **Scores:** shared by the whole room, updating live.

### 2. Copy and privacy

- Update How it works and the privacy text: room links are shared, anyone with the link can join, and everyone in the room sees names, signatures, and scores.
- Repeat that raw keystrokes are discarded after scoring, and that everything disappears when the room ends, expires, or the app restarts.

### 3. Link previews

Room links use the same generic title, description, and image as the home page. Never put a room's names or scores in a preview.

### 4. Phones

Phones can open a room link and watch, until the mobile version lands. Show "Join from a computer to play" in place of the typing step.

**Done when**

- Playwright with two separate browser contexts covers:
  - creating a room, copying its link, joining from the second browser, and enrolling a player in each
  - attacking across browsers, with the "different keyboard" label
  - live updates in both browsers
  - one browser failing to rename or delete the other's player
  - host lock, removal, and ending the room
  - the ended-room page, an invalid code, and a full room
- The existing one-keyboard Playwright test still passes.
- Screenshots show the room header, join step, and ended page, on desktop and at phone width.
- Frontend typecheck, tests, and build pass.

**Prompt**

```text
Read docs/plans/active/ROOMS_PLAN.md and carry out Phase 3 only. Keep the existing look and one-keyboard play. Run the Done when checks, show the screenshots, push the branch, and stop.
```

---

## Phase 4: Launch readiness

**Purpose:** confirm rooms work on the real site before the announcement. Claude Code prepares the pull request. I merge and test.

1. Open a pull request from `rooms` that summarizes the changes, the migration, and these live checks.
2. After I merge, the deploy runs the score migration. Then I check:
   - [ ] `scripts/check_live_events.sh https://typingtwin.com` passes
   - [ ] `scripts/check_live_rate_limit.sh https://typingtwin.com` still passes
   - [ ] Friends on 3 or more computers, at different locations, join one link and play a full round
   - [ ] Updates appear within a few seconds for everyone
   - [ ] A room link opens correctly inside LinkedIn's in-app browser on a phone
   - [ ] The LinkedIn Post Inspector shows the generic preview for a room link
   - [ ] Attempts store `same_keyboard` correctly
   - [ ] The app stays well under its memory limit during the test, in DigitalOcean's metrics
3. **On announcement day:** avoid deploying for at least a day after posting, because every deploy ends all live rooms.

**Done when**

- Every live check above passes.
- `README.md` matches what shipped, including its Roadmap section.
- `docs/plans/README.md` marks this plan done, and this file has moved to `docs/plans/done/` with an Outcome section.

**Prompt**

```text
Read docs/plans/active/ROOMS_PLAN.md and carry out Phase 4 step 1. Run all checks from Phases 1 to 3 once more, push the branch, open the pull request with the live checklist in its description, and stop. I'll merge it myself.
```

---

## After launch

- Mobile, following `docs/plans/active/MOBILE_PLAN.md`, with phones joining rooms as `touch` members
- Rooms that survive a deploy, which would need shared storage such as Redis
- More than one app instance, which also needs shared storage and a shared rate limiter
