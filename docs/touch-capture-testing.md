# Testing touch capture on real phones

This is the real-device half of `MOBILE_PLAN.md` Phase 0. The page at
`/debug/touch-capture` shows what a phone's browser delivers for each tap on
the on-page keyboard. It exists only when `DEBUG=true`, has no backend, and
sends nothing: results stay on the phone until you copy them.

## Run it on your local network

From the repository root, on your computer:

```bash
cd frontend && npm ci && npm run build && cd ..
DEBUG=true ENABLE_ACCOUNTS=false uv run uvicorn keystroke_dynamics.main:app --host 0.0.0.0 --port 8000
```

`docker compose up` won't work for this, because it publishes the port on
`127.0.0.1` only.

Then, with the phone on the same Wi-Fi:

1. Find the computer's address with `ipconfig getifaddr en0`.
2. Open `http://<that address>:8000/debug/touch-capture` on the phone.
3. If it doesn't load, allow incoming connections for Python in macOS
   Firewall settings, and check that the Wi-Fi doesn't isolate devices
   (guest networks often do).

Stop the server when you're done. While it runs, anyone on the network can
reach the app in debug mode.

### LinkedIn's in-app browser

Send yourself the link in a LinkedIn message and tap it inside the app. If
LinkedIn refuses a plain `http://` address, you'll need an HTTPS address. That
means a temporary tunnel or debug deployment that you set up yourself. Keep it
short-lived, since it exposes a `DEBUG=true` app, and never point it at
production. HTTPS also turns on the **Copy results** button, which browsers
allow only on HTTPS or localhost. Over plain HTTP, the page selects the
results text instead, and you copy it by hand.

## What to do on each device

1. Tap **Start a line** and type `tap the rhythm of your thumbs` with your
   normal two-thumb grip. Do this 3 times.
2. Type one more line as fast as you can, letting your thumbs overlap.
3. Type one more line while trying to break it: hold a key for 2 seconds,
   double-tap a key quickly, drag a thumb off a key, tap between keys, and
   try to pinch or scroll on the keyboard.
4. After the last line, copy the results and send them to yourself with the
   device and browser name. The export covers every line since the page
   loaded.

The report marks each automatic check `OK` or `CHECK`. Wrong keys and
`stopped early` are expected on the line where you try to break it.

## Checklist

Fill in one column per device and browser.

| | iPhone Safari | Android Chrome | LinkedIn on iPhone | LinkedIn on Android | Smallest phone | Largest phone |
|---|---|---|---|---|---|---|
| Device and OS version | | | | | | |
| **From the report** | | | | | | |
| Events per tap: 2 for every tap | | | | | | |
| Lost or out of order: none | | | | | | |
| Pointer and touch counts match | | | | | | |
| Canceled touches: 0 in normal typing | | | | | | |
| Scrolling, zooming, selection, callouts: all 0 | | | | | | |
| Viewport resized: 0 | | | | | | |
| Pointer types: `touch` only | | | | | | |
| Smallest time step (write the value) | | | | | | |
| Hold and gap times look plausible (holds roughly 40 to 150 ms) | | | | | | |
| Offsets stay within about half a key | | | | | | |
| Fast line: overlapping taps counted, none lost | | | | | | |
| **By eye, which the page can't detect** | | | | | | |
| The system keyboard never opens | | | | | | |
| Every tap you made shows up, and none is doubled | | | | | | |
| The pressed key lights up under your thumb, not a neighbor | | | | | | |
| No magnifier, selection handles, or long-press menu on a 2-second hold | | | | | | |
| No double-tap zoom, and the page doesn't move or bounce | | | | | | |
| Swiping from the screen edges doesn't go back or switch apps mid-line | | | | | | |
| The keyboard clears the home indicator and browser bars | | | | | | |
| The whole keyboard and the line are visible together | | | | | | |
| Keys are comfortable to hit (note the letter key size from the report) | | | | | | |
| Low Power Mode: timings look the same | | | | | | |
| Haptics: note whether you feel a tick (none on iPhone is expected) | | | | | | |

## What to send back

For each device: the copied results, the filled-in column, and a sentence on
anything that felt wrong even when the report said `OK`. A screenshot helps
for anything visual.

## Limits of this page

- It can only count what the browser reports. A tap the browser never
  delivered leaves no trace, so compare the tap count with what you typed.
- iOS doesn't fire an event for every callout or magnifier, so check those by
  eye.
- It accepts mouse clicks and reports the pointer type, so it works on a
  computer too. The game itself will reject them.
