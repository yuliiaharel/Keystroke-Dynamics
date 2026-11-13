# Typing Twin Party: Mobile Plan

> **Status: Active.** Phases 0 to 2 are built on the `mobile` branch: the capture test page, backend touch scoring, and the touch game itself. Everything so far was checked with emulated touches only, so Phase 0's real-device results and Phase 3 are still to come. Revised on 2026-11-12 for shareable rooms, which are now live.

Repository: `yuliiaharel/Keystroke-Dynamics`

## Goal

Make Typing Twin Party fully playable on a phone at the same URL, with no App Store app.

A group can pass one phone around, or share a room link and play from their own phones. They build signatures from their tap rhythm and where their thumbs land, and attack each other. A visitor from LinkedIn can start playing right away on their phone.

## Starting point

This was checked against `master` at commit `e7cc59e`, after the rooms launch.

**Already live and reused here:**
- The party game, with anonymous players, attacks, replay, scores, and a single "Start a party" flow on the sentence line
- Shareable rooms: a link per room, member browsers, a host, player ownership, live updates by event stream or polling, and `same_keyboard` on attempts and stored scores
- `Member.device_type`, which exists but always holds `keyboard`
- Game scoring at `SCORING_VERSION = "2"`, with each player's limit clamped between 1.3 and 2.0
- Pace and a one-line clue on every result
- Automatic score collection in `score_attempts`, which already has `device_type`, `rhythm`, and `place` columns
- `design/typing-twin-touch.html`, the approved phone design
- `CLAUDE.md`, with the standing rules for Claude Code
- Phase 0's capture test page, on the `mobile` branch. That branch is still based on `5bb3ac1` and conflicts with `master`

**What mobile has to change:**

| Area | Today | Needed |
|---|---|---|
| Phones | Shown "Best on a computer" or "Join from a computer to play" in four places in `party.ts`, and limited to watching | The full touch game |
| Rooms | Every room and member is `keyboard` | Each room has one device type. The other kind of device can watch |
| Scoring | Rhythm only. `place` is never filled | Rhythm and Place, scored separately |
| Clue | Names pace and rhythm only | Also names tap position when it's the giveaway |
| `score_attempts` constraints | `line_id` allows only `word`, `sentence`, and `long`. `mode` doesn't allow `grip` | A migration, following `7c2e9a4f1b3d`, that allows the touch line and `grip` |

## How to use this plan

1. Save this file in the repository as `docs/plans/active/MOBILE_PLAN.md`, and commit it.
2. Run each phase in a new Claude Code session, using the prompt under it, and review the result before continuing.

## Rules for Claude Code

1. Follow `CLAUDE.md`. Read this file and `design/typing-twin-touch.html` first, and read `docs/plans/done/PARTY_LAUNCH_PLAN.md` only where this plan points to it.
2. Do only the requested phase.
3. Work on the `mobile` branch. Before Phase 1, merge the latest `master` into it, resolve the conflicts, and confirm Phase 0's tests still pass. Make small commits, and push the branch. Never push to or merge into `master`, because that deploys.
4. Check `git status`, branches, and stashes first, and never discard my work.
5. Desktop results must not change. Do not change the defaults or behavior of `core/` for existing callers, the keyboard game's scoring, or how keyboard rooms work.
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
| Play style | Pass one phone around, or share the room link with other phones |
| Rooms | One device type per room, set by the creator's device. Someone on the other kind of device can open the link and watch, but not play |
| Evidence | Presented as a game. The 9.1% benchmark doesn't apply to touch |

### Out of scope for now

Do not add a native app, motion sensors, contact size or pressure, a tap-a-rhythm mode, scoring across device types, mixed rooms where phones and computers both play, or accounts.

## Open decisions

My recommendation comes first. Claude Code should use these unless I change them.

1. **Which level comes first?** One touch line. Add others only if the first test shows they're needed.
2. **What happens with a touchscreen laptop?** Use the physical keyboard by default, and offer a clear "Use on-screen keyboard" switch before starting a room, or when opening a touch room's link.
3. **What about mouse clicks on the touch keyboard?** Reject them outside debug mode, since mouse data isn't a touch signature.
4. **Should grip tests be saved in shared scores?** Yes, as their own mode, with no extra detail about the grip.
5. **Should screen size be recorded?** Decided: yes, as a broad size bucket only, because key size can affect results. Phase 1 section 6 has the buckets.
6. **Which limits should touch use?** Start with a minimum of 1.65, a provisional value from one small phone test, and the keyboard game's maximum of 2.0. Retest both in Phase 4.
7. **Can one phone attack a player on another phone?** Yes, labeled "different phone" on results and in scores, as keyboards are. Phone models differ in key size, so Phase 4 compares these attacks with same-phone ones.

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

- Add `device_type` (`keyboard` or `touch`) to a room when it's created, from the creator's device, and expose it in room state.
- Set each member's `device_type` when they join, from what their browser reports. The field already exists on `Member`.
- A member whose device type differs from the room's is a watcher. They can read the room, receive live updates, and run a replay, as phones can today. They can't enroll, rename, or type, and they count toward the room's member limit.
- Every player, attempt, sample target, and permanent target belongs to one device type.
- Reject an enrollment, attempt, or target that doesn't match the room's type, with a clear error, and test it.
- Keep the rooms plan's ownership, host, and limit rules unchanged for touch rooms. For touch, `same_keyboard` means the same phone.

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

Reject non-finite values, offsets beyond a sensible limit, a position on an `up` event, and oversized samples. Reuse the existing timing validation and pairing logic. Accept `dx` and `dy` only in touch rooms.

### 3. Touch line

Add a `touch` level for the line `tap the rhythm of your thumbs`, with 5 rounds including the warm-up. Keep the keyboard levels unchanged. Use only letters and spaces. A touch room always uses this level, and a keyboard room never does, with a clear 400 error otherwise.

### 4. Place features

Add a separate, pure module for position features:

- `("tap_x", code)` for every key except the space bar, because side-to-side position on a wide key is too noisy.
- `("tap_y", code)` for every key.
- Average repeated keys within a line.

### 5. Scoring

Position values aren't milliseconds, so don't push them through the timing floors. Add a game-level scorer for touch that:

- reuses `core.stats` and the existing scaled Manhattan approach, with no second copy of its formula if a small shared helper can avoid one
- applies `max(sd, 12 ms, 12% of the mean)` to timing, and `max(sd, 0.08 key)` to position
- keeps the keyboard game's timing features unchanged, so every key press and every consecutive pair counts, repeats included
- returns `distance`, `rhythm`, `place`, `compared_features`, and the decision
- calculates `rhythm` as the mean across the compared timing features, and `place` as the mean across the compared position features
- calculates `distance` as the equal-weight average of `rhythm` and `place`. A line has about twice as many timing features as position features, so a mean across all features would let the right rhythm hide taps in the wrong places
- uses a touch minimum limit of 1.65 and the existing maximum of 2.0, both labeled as provisional game tuning
- requires at least 70% of the line's timing features and at least 70% of its position features to be compared, each checked separately, and returns insufficient data otherwise. For this line that's 40 of 57 timing features and 19 of 27 position features

Add a golden test that confirms keyboard scores and limits are identical before and after this change.

### 6. Results and privacy of stored data

- Add `rhythm`, `place`, and `pace` to touch attempt responses. Reuse any existing pace field.
- Keep raw events in memory only for the request. Do not log them.
- Do not store offsets in `score_attempts`. Store only scores, plus the `touch` device type and agreed fields.
- Add a `grip` mode for score collection, if I keep that decision. It's separate from the keyboard game's `disguise` mode, and has no pace rule.
- Fill `rhythm` and `place` for touch rows. Keyboard rows keep `place` empty.
- Fill `same_keyboard` for touch rows, by the same rule as keyboard rows.
- Save a screen size bucket for touch rows, in a nullable `screen_size` column that stays empty for keyboard rows and replays. The browser reports its viewport width when it creates or joins a touch room. The server keeps only the bucket, and never stores or logs the width:

  | Bucket | Viewport width | Typical devices |
  |---|---|---|
  | `small` | Under 360 px | The narrowest phones, such as 320 px |
  | `medium` | 360 to 399 px | Most phones |
  | `large` | 400 to 479 px | Large phones |
  | `xlarge` | 480 px and up | Tablets and touchscreen laptops |

- Add a new migration in `migrations_scores/`, following `7c2e9a4f1b3d`, that widens the `line_id` check to allow `touch`, and the `mode` check to allow `grip`, and adds `screen_size` with a check that allows only the four buckets. Never edit an existing migration. The existing pre-deploy job applies it, so check that the migration role can alter the table, and document any manual step in `DEPLOY.md`.
- Increase `SCORING_VERSION` to `"3"` for touch scoring, and keep the keyboard rows comparable across versions. Note in the code what changed.
- Update `evaluation/analyze_scores.py` to report Rhythm and Place, split by `device_type` and then by `same_keyboard`.

### 7. Sharing the tap map

The room shows each player's tap map, so a touch player's view needs an average and spread per key. This is a deliberate exception to "never send profile statistics":

- Send only position averages and spreads, only to members of that player's room. That means anyone with the room link.
- Send them only in the room state request, never in the event stream, which still carries only a version number.
- Keep timing statistics private, as they are today.
- Permanent and sample targets follow the same rule.

### 8. Replay and targets

- Add simulated touch practice targets, clearly labeled.
- A replay rebuilds a tap line from the target's median timing and average tap position, then scores it on the server.
- Permanent targets are recorded separately for touch, and only through the debug-only route. Before I've recorded one, the game must work without it.

**Done when**

- Unit tests cover position features, each validation failure, floors, mixed scoring, insufficient data for each kind of feature on its own, and replay.
- A test confirms that a typist's own rhythm fails when every tap is shifted 0.35 of a key.
- API tests cover:
  - creating a touch room, and joining it from a second touch member
  - a keyboard member watching a touch room, and a touch member watching a keyboard room, with enrollment and attempts rejected for both
  - one touch member trying to rename, delete, or type as another's player
  - `same_keyboard` on touch attempts and in stored scores
  - tap maps appearing in room state for members only, and never in the event stream
- All existing room tests pass unchanged.
- The golden test confirms keyboard results are unchanged.
- The new migration applies to a real Postgres copy of the current schema, including `same_keyboard`, existing rows survive with an empty `screen_size`, and touch and `grip` rows can be inserted with a bucket or without one.
- Tests confirm no offsets or raw events reach logs or stored scores.
- Python tests, `ruff`, and `mypy` pass.

**Prompt**

```text
Read docs/plans/active/MOBILE_PLAN.md and carry out Phase 1 only. First merge the latest master into the mobile branch and confirm Phase 0's tests still pass. Do not change the frontend yet. Run the Done when checks, show the keyboard golden test result and the migration test, list anything that needs my decision, push the branch, and stop.
```

---

## Phase 2: Touch game

**Purpose:** bring the approved mockup into the real app.

### 1. Split the frontend sensibly

`frontend/src/pages/party.ts` is about 1,600 lines. Capture, room, and live-update code already live in `capture.ts`, `room.ts`, and `live.ts`. Move only what this work needs into small modules, such as the touch keyboard and tap map drawing. Do not rewrite the page or change the desktop look.

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
- Replay, Delete me, and New room

The clue must name the actual giveaway. Never say that everything fits on a failed attempt.

The mockup predates rooms. For these, follow the live desktop room, fitted to phone width:

- Room header with the code and **Copy link**
- Joining from a room link, and the "Leave your current room and join this one?" confirmation
- Host controls: lock, remove a player, and end the room
- **Leave room**, and the ended-room page
- **Who's typing** lists only this phone's own players, plus Guest
- Each player card shows whether it's on this phone or another one, and attacks from another phone show a "different phone" note
- New players, attacks, and scores appear live

### 4. Device detection

- Phones get a touch room, keeping the single "Start a party" flow. Remove all four "Best on a computer" and "Join from a computer to play" notices from the normal phone path.
- Computers keep the keyboard game unchanged, including the mobile path being off when a physical keyboard game is chosen.
- A phone that opens a keyboard room's link watches, with the notice "This room is for computers" and a **Start your own room** action. A computer that opens a touch room's link gets the same, with "This room is for phones".
- When a phone is locked or the browser goes to the background, the event stream drops. When the page is visible again, reconnect and fetch the room, and fall back to polling as today.
- A touchscreen laptop follows open decision 2.
- Portrait mode is required while typing. In landscape, pause and ask the player to rotate, because key shape changes tap positions.
- If a line is interrupted by rotation, app switching, or a lost connection, restart it clearly and don't score partial data.

### 5. Copy and privacy

Update the privacy text and How it works to say plainly:

- Key identity, tap timing, and position within the key are sent to the server for scoring.
- Raw taps are discarded after scoring. Average tap position and timing statistics stay in memory until the player deletes themselves, the room ends or expires, or the app restarts.
- Everyone in the room, which means anyone with its link, can see names, rings, and tap maps.
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
- Playwright with two emulated phones in separate browser contexts covers:
  - creating a room, joining from its link, and enrolling a player on each phone
  - attacking across phones, with the "different phone" label
  - live updates on both phones, and catching up after one page was hidden
  - one phone failing to rename or delete the other's player
  - host lock, removal, and ending the room
- Playwright covers a phone watching a keyboard room, and a computer watching a touch room, with no typing step in either.
- Tests cover overlapping fingers, `pointercancel`, wrong keys, mouse rejection, and rotation.
- Tests confirm that typed text isn't sent, no third-party request is made, and the page doesn't scroll sideways at 320, 390, and 430 px.
- The desktop and rooms Playwright suites still pass unchanged.
- Frontend tests and the production build pass.
- You provide screenshots at 390 px in light and dark themes, including the room header, host controls, and both watcher notices.

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
- [ ] Two phones join one room by its link, and each sees the other's changes within a few seconds
- [ ] A phone that was locked for a minute shows the current room when unlocked
- [ ] A room link opens correctly from a messaging app and from LinkedIn's in-app browser
- [ ] A phone opening a keyboard room's link, and a computer opening a touch room's link, can watch but not play
- [ ] Low Power Mode doesn't noticeably change the results
- [ ] Sound and haptics are optional, and absent ones cause no errors
- [ ] The app stays within the 512 MiB memory limit during the existing load test of 300 streams across 50 rooms, extended so that half the rooms are touch rooms with tap maps

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
4. 5 attacks on someone else, trying to match their pace (within 0.85x to 1.15x). Type at least 2 on the target's phone, and at least 2 from your own phone in the same room

**Before looking at results,** decide what counts as good enough. As a starting point, which is my judgment and not a standard:

- At least 80% of normal self-tests pass.
- Fewer than 20% of pace-matched attacks pass.
- At least 3 people's data points in the same direction.

**Then analyze it:**

- Use scores only, with `evaluation/analyze_scores.py`.
- Compare self-tests, grip tests, and pace-matched attacks.
- Compare Rhythm and Place.
- Compare attacks typed on the target's phone with attacks from another phone, using `same_keyboard`.
- Check how each result would change at limits from 1.3 to 2.5. The current maximum is 2.0, so this also shows whether that cap suits touch.

**Decide from the results:**

| Result | Action |
|---|---|
| Clear separation | Keep going, and adjust the limit modestly |
| Rhythm works, Place doesn't | Make Rhythm the main score, and keep Place as a visual |
| Grip changes results heavily | Ask players to enroll with their usual grip, and say so more clearly |
| Attacks from another phone score very differently | Say so on results, and consider counting only same-phone attacks in the scores |
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
   - [ ] Touch attempts are stored with `device_type = touch`, with no positions or timings
   - [ ] **Delete me** removes test rows
   - [ ] Logs contain no tap data
   - [ ] Two phones at different locations join one room link and play a full round
   - [ ] A phone in a keyboard room, and a computer in a touch room, can watch but not play
   - [ ] Touch attempts from another phone store `same_keyboard = false`
   - [ ] `scripts/check_live_rate_limit.sh https://typingtwin.com` still passes
   - [ ] `scripts/check_live_events.sh https://typingtwin.com` still passes
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

- Compare real touch and keyboard results from saved scores
- Mixed rooms, where phones and computers share a room and each attacks only its own kind
- A tap-a-rhythm bonus round
- A native iOS version, only if the web version shows real limits
