# Modernization TODO

Rough priority order. This is a 2018 demo; nothing here is urgent, but the
security issues (1–2) are the kind you'd actually want fixed before showing
this to anyone else or exposing it off localhost.

## Security

1. **SQL injection via table names.** Usernames are concatenated directly into
   `CREATE TABLE`/`SELECT`/`INSERT` statements (`"SELECT * FROM " + username`)
   in `bioauth.py`, `profile.py`, `checkname.py`. A username like
   `x; DROP TABLE sqlite_master;--` goes straight into the query. Fix properly
   by moving to one shared table (`digraphs(username, digraph_id,
   expected_value, variance, frequency)`, username as a bound parameter) —
   also fixes #6 below.
2. **Raw request bodies written to disk as JSON**, named only from the
   client-supplied username and type (`Create_Profile_<user>POST.json`) with
   no path sanitization — a crafted username could write outside the working
   directory. Validate/allowlist the username before it touches a filename,
   or stop round-tripping through files entirely (see #5).
3. **No auth on the API itself.** Anyone can create or overwrite anyone's
   profile — there's no password, token, or session tied to a username.
   Keystroke dynamics is acting as the *entire* auth system with zero
   gatekeeping on who gets to submit a "training" sample.
4. `app.run(..., debug=True)` in `run.py` — Flask's debugger exposes a remote
   code execution console if this ever ends up reachable from outside
   localhost. Fine for local dev, never for anything else.
5. `CORS(app)` with no restriction allows any origin. Scope it to the actual
   frontend origin(s).

## Correctness bugs

6. `user.replace(" ", "_")` in `keystroke.py` discards its return value —
   strings are immutable in Python, so this line does nothing. Usernames with
   spaces still reach the DB layer unmodified.
7. `profile.py`/`bioauth.py` build table names as `"".join(prof.keys())` —
   works only because there's exactly one key; fragile and confusing. Goes
   away with #1's schema fix.

## Python 2 → 3

8. The whole backend is Python 2 only: `print` statements, `xrange`,
   `dict.has_key()`, `dict.values()[0]` indexing (dict views aren't
   subscriptable in Py3). Python 2 has been EOL since 2020; this needs a real
   port, not a 2to3 pass and a prayer — `values()[0]` in particular needs to
   become `list(values())[0]` or a rewrite to avoid it.
9. `from flask.ext.navigation import Navigation` is the Flask 0.x extension
   import style, removed since Flask 1.0. Modern equivalent:
   `from flask_navigation import Navigation` (if the package is kept at all —
   consider dropping the nav bar dependency and hand-writing the three links).

## Frontend

10. `cp_keyscapt.js` / `auth_keyscapt.js` hardcode the old deployment's IP
    (`162.243.145.18`) instead of a relative URL or configurable base —
    breaks on any fresh clone until manually edited (see README). Switch to
    relative paths (`/createprofile`, `/auth`) so the frontend always talks
    to whatever server is actually serving it.
11. `keycapture.js` is dead code — not loaded by any template, duplicates
    logic that now lives (slightly differently) in `cp_keyscapt.js` and
    `auth_keyscapt.js`. Delete it or reconcile the three into one shared file.
12. No client-side validation beyond "is the textarea empty" — e.g. nothing
    stops a user from typing 3 characters and submitting a profile that's too
    short to be a meaningful biometric sample.

## Project hygiene

13. No `requirements.txt` (or `pyproject.toml`) — `readme.txt` has three
    unpinned `pip install` lines. Pin versions once a target Python version is
    decided.
14. No tests at all — `digraph.py`'s timing math and `bioauth.py`'s 3‑sigma
    match logic are both small, pure-ish, and very testable in isolation.
15. `keystroke.sqlite` (the actual database file, with whatever profile data
    was in it) is committed to the repo. Should be gitignored and shipped
    empty/absent; `.gitignore` currently doesn't cover it.
16. DB path (`'keystroke.sqlite'`) and server port (`run.py`'s hardcoded 80)
    are hardcoded rather than configurable via env vars or a config file.
17. `origin/refactor` is an abandoned, incomplete reorg attempt — it moves
    files into `api/`/`utils/` and starts a `model.py`, but
    `db_helper.create_db()` is an empty function body (a syntax error) and the
    per-user-table SQL injection pattern is untouched. Worth a skim for ideas,
    not worth merging as-is.
