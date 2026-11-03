# Keystroke Dynamics

A demo web app that authenticates users by *how* they type, not just *what* they
type. You create a profile by typing a passage of text; the app learns the timing
pattern between consecutive key presses (digraphs). Later, typing the same way is
enough to authenticate — no password needed.

## How it works

1. **Create a profile** — type a block of text. JS in the browser records every
   keydown/keyup timestamp and sends the raw log to the server.
2. The server breaks the log into **digraphs** (timing between consecutive key
   events) and stores the mean and variance of each digraph's timing for that user,
   in SQLite.
3. **Authenticate** — type again. The server extracts the same digraphs from the new
   sample and checks how many fall within 3 standard deviations of the stored mean.
   If enough do, access is permitted.

## Stack

- Flask (**Python 2** — `print` statements, `flask.ext.navigation`, `xrange`; it
  will not run under Python 3 without porting)
- Vanilla JS + jQuery on the frontend, capturing key events
- SQLite (one shared `digraphs` table, keyed by `(username, digraph_id)`)

## Run it locally

```bash
# needs a Python 2 interpreter
pip2 install Flask flask-cors Flask-Navigation
python2 run.py
```

`run.py` binds port 80, so you'll likely need `sudo python2 run.py`, or edit
`run.py` to use a port like 5000.

**Known gotcha:** the pages that actually do the work (`createprofile.html`,
`auth.html`) load `cp_keyscapt.js` / `auth_keyscapt.js`, and both hardcode the
original author's old server IP (`http://162.243.145.18:80/...`) instead of
`localhost`. Edit the `url_k` constant at the top of each file to point at
wherever you're running the Flask app, or nothing will reach your local server.
(`keycapture.js` is an older, unused variant that *does* default to
`localhost:5000` — not loaded by any template.)

## Notes

This is a 2018 class-project-style demo, not production code: there's no auth
on the API itself (anyone can create or overwrite anyone's profile), and the
statistical model (3-sigma match on raw digraph timing) is simple by design.
Treat it as a working illustration of the idea, not a biometric system to rely
on. See [`TODO.md`](TODO.md) for what's left — it used to also have a SQL
injection via unsanitized table names and a path-traversal-prone file write,
both now fixed.
