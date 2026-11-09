# Typing Twin Party: Mobile Plan

> **Status: Active.** Phase 0's capture test page is built on the `mobile` branch. Real-device results are still to come.

Repository: `yuliiaharel/Keystroke-Dynamics`

## Goal

Make Typing Twin Party fully playable on a phone at the same URL, with no App Store app.

A group can pass one phone around, build signatures from their tap rhythm and where their thumbs land, and attack each other. A visitor from LinkedIn can start playing right away on their phone.

## Status: Draft

Review the open decisions below before starting.

## Starting point

This was checked against `master` at commit `5bb3ac1`, after the desktop launch.

**Already live and reused here:**
- The party game, with anonymous players, attacks, replay, scores, and a single "Start a party" flow on the sentence line
- Pace and a one-line clue on every result
- Opt-in score collection in `score_attempts`, which already has `device_type`, `rhythm`, and `place` columns
- `design/typing-twin-touch.html`, the approved phone design
- `CLAUDE.md`, with the standing rules for Claude Code

**What mobile has to change:**

| Area | Today | Needed |
|---|---|---|
| Phones | Shown "Best on a computer" and limited to looking around | The full touch game |
| Scoring | Rhythm only. `place` is never filled | Rhythm and Place, scored separately |
| Clue | Names pace and rhythm only | Also names tap position when it's the giveaway |
| `score_attempts` constraints | `line_id` allows only `word`, `sentence`, and `long`. `mode` doesn't allow `grip` | A migration that allows the touch line and `grip` |

## How to use this plan

1. Save this file in the repository as `docs/plans/active/MOBILE_PLAN.md`, and commit it.
2. Run each phase in a new Claude Code session, using the prompt under it, and review the result before continuing.

## Rules for Claude Code

1. Follow `CLAUDE.md`. Read this file and `design/typing-twin-touch.html` first, and read `docs/plans/done/PARTY_LAUNCH_PLAN.md` only where this plan points to it.
2. Do only the requested phase.
3. Work on the `mobile` branch, branched from the latest `master`. Make small commits, and push the branch. Never push to or merge into `master`, because that deploys.
4. Check `git status`, branches, and stashes first, and never discard my work.
5. Desktop results must not change. Do not change the defaults or behavior of `core/` for existing callers, or the keyboard game's scoring.
6. Write tests with each behavior change, and do not weaken a test or limit to get a pass.
7. Run every check under "Done when" and show the actual results. Say clearly what could only be emulated, and what still needs a real phone.
8. If the code contradicts this plan, stop and ask me.

## Decisions already made

| Area | Decision |
|---|---|
| Platform | Mobile web at the same URL and in the same app |
| Keyboard | A custom on-page keyboard, never the phone's system keyboard |
| Input | Pointer events, recording when each finger lands and lifts, and where it lands on the key |
| Game line | A short touch-specific line: `tap the rhythm of your thumbs` |
| Scores | Rhythm and Place shown separately, with pace as a separate clue |
| Device separation | Phone and physical keyboard signatures are never compared |
| Play style | Pass one phone around. Online rooms remain a separate project |
| Evidence | Presented as a game. The 9.1% benchmark doesn't apply to touch |

### Out of scope for now

Do not add a native app, motion sensors, contact size or pressure, a tap-a-rhythm mode, scoring across device types, online play, or accounts.

## Open decisions

My recommendation comes first. Claude Code should use these unless I change them.

1. **Which level comes first?** One touch line. Add others only if the first test shows they're needed.
2. **What happens with a touchscreen laptop?** Use the physical keyboard by default, and offer a clear "Use on-screen keyboard" switch before a party starts.
3. **What about mouse clicks on the touch keyboard?** Reject them outside debug mode, since mouse data isn't a touch signature.
4. **Should grip tests be saved in shared scores?** Yes, as their own mode, with no extra detail about the grip.
5. **Should screen size be recorded?** Save only a broad size bucket, because key size can affect results. Keep it out if you'd rather minimize data.
6. **Which minimum limit should touch use?** Start at 1.65, a provisional value from one small phone test, and retest it in Phase 4.

---

## Phase 0: Test on real phones

**Purpose:** find device problems before changing the backend. Build no production features in this phase.

1. Confirm that the starting point above still matches `master`, and list any differences.
2. Build a minimal capture test page that's available only when `debug=true`, using the touch keyboard from `design/typing-twin-touch.html`.
3. Let me test it from my phone over the local network or a temporary debug deployment that I set up myself. Document how, and don't deploy anything.
4. The page should show, for a typed line:
   - events per tap, and whether any were lost or out of order
   - tap duration, gaps, and offsets from the center of each key
   - any scrolling, zooming, text selection, callouts, or canceled touches
5. Give me a checklist for these devices and browsers:
   - iPhone Safari
   - Android Chrome
   - LinkedIn in-app browser on iPhone and Android
   - the smallest and largest phones available

**Done when**

- The test page works in emulated touch tests.
- Tests confirm the page doesn't exist when `debug=false`.
- I have reported real-device results, and you've listed any problems that change this plan.

**Prompt**

```text
Read docs/plans/active/MOBILE_PLAN.md and carry out Phase 0 only. Check the starting point first. Build the debug-only capture test page, run the checks that don't need a real device, give me the instructions and checklist for testing on my phones, push the branch, and stop.
```

---

## Phase 1: Backend touch scoring

**Purpose:** score tap rhythm and tap position with the existing engine, without changing keyboard results.

### 1. Device type

- Add `device_type` (`keyboard` or `touch`) to a party when it's created, and expose it in party state.
- Every player, attempt, sample target, and permanent target belongs to one device type.
- Reject an attempt or target that doesn't match the party's type, with a clear error, and test it.

### 2. Touch event format

Add game-specific request schemas. Do not change the account API's event format.

```python
class TapEvent:
    code: str          # A key on the on-page keyboard, such as "KeyA"
    action: Literal["down", "up"]
    t_ms: float
    dx: float | None   # Down events only, in letter-key widths from the center
    dy: float | None   # Down events only, in letter-key heights from the center
```

Reject non-finite values, offsets beyond a sensible limit, a position on an `up` event, and oversized samples. Reuse the existing timing validation and pairing logic. Accept `dx` and `dy` only in touch parties.

### 3. Touch line

Add a `touch` level for the line `tap the rhythm of your thumbs`, with 5 rounds including the warm-up. Keep the keyboard levels unchanged. Use only letters and spaces, and allow this level only in touch parties, with a clear 400 error otherwise.

### 4. Place features

Add a separate, pure module for position features:

- `("tap_x", code)` for every key except the space bar, because side-to-side position on a wide key is too noisy.
- `("tap_y", code)` for every key.
- Average repeated keys within a line.

### 5. Scoring

Position values aren't milliseconds, so don't push them through the timing floors. Add a game-level scorer for touch that:

- reuses `core.stats` and the existing scaled Manhattan approach, with no second copy of its formula if a small shared helper can avoid one
- applies `max(sd, 12 ms, 12% of the mean)` to timing, and `max(sd, 0.08 key)` to position
- returns `distance`, `rhythm`, `place`, `compared_features`, and the decision
- calculates `distance` as the mean across all compared timing and position features
- uses a touch minimum limit of 1.65, labeled as provisional game tuning
- requires a minimum number of compared features suited to this line

Add a golden test that confirms keyboard scores and limits are identical before and after this change.

### 6. Results and privacy of stored data

- Add `rhythm`, `place`, and `pace` to touch attempt responses. Reuse any existing pace field.
- Keep raw events in memory only for the request. Do not log them.
- Do not store offsets in `score_attempts`. Store only scores, plus the `touch` device type and agreed fields.
- Add a `grip` mode for score collection, if I keep that decision.
- Fill `rhythm` and `place` for touch rows. Keyboard rows keep `place` empty.
- Add a new migration in `migrations_scores/` that widens the `line_id` check to allow `touch`, and the `mode` check to allow `grip`. Never edit the existing migration. The existing pre-deploy job applies it, so check that the migration role can alter the table, and document any manual step in `DEPLOY.md`.
- Increase `SCORING_VERSION` for touch scoring, and keep the keyboard rows comparable across versions. Note in the code what changed.
- Update `evaluation/analyze_scores.py` to report Rhythm and Place, split by `device_type`.

### 7. Sharing the tap map

The room shows each player's tap map, so a touch player's view needs an average and spread per key. This is a deliberate exception to "never send profile statistics":

- Send only position averages and spreads, only inside that player's party.
- Keep timing statistics private, as they are today.
- Permanent and sample targets follow the same rule.

### 8. Replay and targets

- Add simulated touch practice targets, clearly labeled.
- A replay rebuilds a tap line from the target's median timing and average tap position, then scores it on the server.
- Permanent targets are recorded separately for touch, and only through the debug-only route. Before I've recorded one, the game must work without it.

**Done when**

- Unit tests cover position features, each validation failure, floors, mixed scoring, insufficient data, and replay.
- API tests cover touch parties, separation by device type, and access between sessions.
- The golden test confirms keyboard results are unchanged.
- The new migration applies to a real Postgres copy of the current schema, existing rows survive, and touch and `grip` rows can be inserted.
- Tests confirm no offsets or raw events reach logs or stored scores.
- Python tests, `ruff`, and `mypy` pass.

**Prompt**

```text
Read docs/plans/active/MOBILE_PLAN.md and carry out Phase 1 only. Do not change the frontend yet. Run the Done when checks, show the keyboard golden test result and the migration test, list anything that needs my decision, push the branch, and stop.
```

---

## Phase 2: Touch game

**Purpose:** bring the approved mockup into the real app.

### 1. Split the frontend sensibly

`frontend/src/pages/party.ts` is about 1,200 lines. Move only what this work needs into small modules, such as capture, keyboard, and tap map drawing. Do not rewrite the page or change the desktop look.

### 2. Touch keyboard and capture

- Build the keyboard from `design/typing-twin-touch.html`, fixed to the bottom of the screen, respecting safe areas.
- Use pointer events. Handle overlapping fingers using `pointerId`, and treat `pointercancel` as an unusable hold.
- Normalize offsets to letter-key size, so that they don't depend on screen size.
- Never focus a text input while typing, so the system keyboard stays closed.
- Ignore untrusted events.
- Prevent scrolling, double-tap zoom, text selection, and long-press menus on the keyboard, while keeping normal scrolling and zoom elsewhere.
- Wrong keys show an error and don't advance. Gaps after an error aren't counted.
- Use haptics only where available, and never depend on them.

### 3. Game flow

Port these from the mockup:

- Intro, name, warm-up, and enrollment
- Rhythm ring, tap map, and traits
- Room with Add a player, Attack, Test me, and New grip
- Result with verdict, gauge, pace, Rhythm, Place, clue, giveaways, ring overlay, and tap map overlay
- Scores with pace, Rhythm, and Place
- Replay, Delete me, and New party

The clue must name the actual giveaway. Never say that everything fits on a failed attempt.

### 4. Device detection

- Phones get the touch party. Replace the "Best on a computer" notice with the actual game, keeping the single "Start a party" flow.
- Computers keep the keyboard game unchanged, including the mobile path being off when a physical keyboard game is chosen.
- A touchscreen laptop follows open decision 2.
- Portrait mode is required while typing. In landscape, pause and ask the player to rotate, because key shape changes tap positions.
- If a line is interrupted by rotation, app switching, or a lost connection, restart it clearly and don't score partial data.

### 5. Copy and privacy

Update the privacy text and How it works to say plainly:

- Key identity, tap timing, and position within the key are sent to the server for scoring.
- Raw taps are discarded after scoring. Average tap position and timing statistics stay in memory until the player deletes themselves, or the party expires or the app restarts.
- Everyone in the party can see names, rings, and tap maps.
- Shared scores never include tap positions or timings.
- Different grips and phones can change a signature, and this is a game, not security.

Update Open Graph text so it also fits phones.

### 6. Accessibility

- Provide visible focus states and proper labels on all controls.
- Do not rely on color alone for results.
- Keep key targets usable at 320 px wide.
- Respect reduced motion.
- Screen-reader users won't be able to create an honest typing signature with this keyboard, so explain that and keep the sample room, signatures, and replay readable.

**Done when**

- Playwright with emulated touch (`Input.dispatchTouchEvent`) plays a full game: two players, an attack, a self test, a grip test, a replay, a rename, a deletion, and scores.
- Tests cover overlapping fingers, `pointercancel`, wrong keys, mouse rejection, and rotation.
- Tests confirm that typed text isn't sent, no third-party request is made, and the page doesn't scroll sideways at 320, 390, and 430 px.
- The desktop Playwright suite still passes unchanged.
- Frontend tests and the production build pass.
- You provide screenshots at 390 px in light and dark themes.

**Prompt**

```text
Read docs/plans/active/MOBILE_PLAN.md and carry out Phase 2 only. Keep the desktop game unchanged. Run the Done when checks, show screenshots of each main phone view in light and dark themes, tell me what still needs a real phone, push the branch, and stop.
```

---

## Phase 3: Real-device check

**Purpose:** catch what emulation misses. I run this with a build you've prepared.

- [ ] iPhone Safari, in normal use
- [ ] Android Chrome, in normal use
- [ ] LinkedIn in-app browser, on both
- [ ] The smallest phone available
- [ ] Fast two-thumb typing doesn't miss taps or merge them
- [ ] No zoom, page movement, selection, or long-press menu while tapping
- [ ] The keyboard clears the home indicator and browser bars
- [ ] Rotation, app switching, and a lost connection recover clearly
- [ ] Low Power Mode doesn't noticeably change the results
- [ ] Sound and haptics are optional, and absent ones cause no errors
- [ ] The app stays within the 512 MiB memory limit during the existing load test, extended for touch parties

**Prompt**

```text
Read docs/plans/active/MOBILE_PLAN.md. Here are my Phase 3 real-device results: [paste results]. Fix only the problems I reported, add a regression test where possible, push the branch, and tell me what I need to retest.
```

---

## Phase 4: Field test and tuning

**Purpose:** check whether phone signatures work with several real people before sharing it widely.

**Who:** 3 to 5 adults, on at least 2 phone models.

**Each person does:**

1. Enrollment
2. 5 **Test me** attempts
3. 2 **New grip** attempts
4. 5 attacks on someone else, trying to match their pace (within 0.85x to 1.15x)

**Before looking at results,** decide what counts as good enough. As a starting point, which is my judgment and not a standard:

- At least 80% of normal self-tests pass.
- Fewer than 20% of pace-matched attacks pass.
- At least 3 people's data points in the same direction.

**Then analyze it:**

- Use scores only, with `evaluation/analyze_scores.py`.
- Compare self-tests, grip tests, and pace-matched attacks.
- Compare Rhythm and Place.
- Check how each result would change at limits from 1.3 to 2.5.

**Decide from the results:**

| Result | Action |
|---|---|
| Clear separation | Keep going, and adjust the limit modestly |
| Rhythm works, Place doesn't | Make Rhythm the main score, and keep Place as a visual |
| Grip changes results heavily | Ask players to enroll with their usual grip, and say so more clearly |
| Attacks often pass | Keep it as a party game, say so on the page, and don't tune to hide it |
| Results are too mixed | Launch only as an experimental mode, or hold it back |

Treat any tuning as provisional. With this few people, results can't establish accuracy, and any limit chosen from them is fit to the same data. Do not publish an accuracy number from this test.

**Prompt**

```text
Read docs/plans/active/MOBILE_PLAN.md. Here are the Phase 4 field test scores: [paste results]. Compare them with the criteria we set before testing. Recommend what to change, say how little or how much this data can support each recommendation, and make no code changes until I approve them.
```

---

## Phase 5: Launch

1. Apply approved tuning, and increase `SCORING_VERSION` again if scoring changed.
2. Open a pull request from `mobile`. I merge it, which deploys through the existing App Platform setup and runs the score migration. No new services are needed.
3. Check the live site with this list:
   - [ ] A full phone game works in Safari, Chrome, and LinkedIn's in-app browser
   - [ ] The desktop game still works
   - [ ] Opted-in touch attempts are stored with `device_type = touch`, with no positions or timings
   - [ ] **Delete me** removes test rows
   - [ ] Logs contain no tap data
   - [ ] A phone and a computer can't attack each other's signatures
   - [ ] `scripts/check_live_rate_limit.sh https://typingtwin.com` still passes
   - [ ] The link preview looks right on LinkedIn
4. Update `README.md` and the post text to say that phones are supported and how the results should be read.

**Done when**

- Every item on the live checklist passes.
- `README.md` matches what shipped, including its Play it, Privacy, and Roadmap sections.
- `docs/plans/README.md` marks this plan done, and this file has moved to `docs/plans/done/` with an Outcome section.

**Prompt**

```text
Read docs/plans/active/MOBILE_PLAN.md and carry out Phase 5 steps 1 and 4. Push the branch and open a pull request with the live checklist in its description, then stop. I'll merge it myself.
```

---

## After launch

- Compare real touch and keyboard results from opted-in scores
- Private rooms that keep phones with phones
- A tap-a-rhythm bonus round
- A native iOS version, only if the web version shows real limits
