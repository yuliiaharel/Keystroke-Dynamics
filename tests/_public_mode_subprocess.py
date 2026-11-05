"""Not a pytest module (no test_ prefix) -- a standalone script run in
a fresh subprocess by tests/test_public_mode.py. It has to be a fresh
process, not just a fresh env var inside the main test run: config.py,
db/session.py, and main.py are already imported (with Postgres and
ENABLE_ACCOUNTS=true baked in) the moment tests/conftest.py runs, and
Python caches that import -- there's no way to re-import them with
different settings from inside the same process. This script is the
only way to actually exercise "the app starts and a full game can be
played with no DATABASE_URL at all", for real, rather than trusting
that the conditional in main.py does what it says.

Prints "OK" and exits 0 on success. Any failed assertion or exception
propagates as a nonzero exit with a traceback on stderr, which the
parent test surfaces via subprocess.run(check=True).
"""

from __future__ import annotations

import os
import sys

os.environ["ENABLE_ACCOUNTS"] = "false"
os.environ["DEBUG"] = "true"
os.environ["ALLOWED_ORIGIN"] = "http://testserver"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("SESSION_SECRET", None)

from fastapi.testclient import TestClient  # noqa: E402

from keystroke_dynamics.main import app  # noqa: E402

# The actual "no database connection" guarantee: db/session.py (which
# calls create_engine at import time) must never have been imported
# at all, not just never queried.
assert "keystroke_dynamics.db.session" not in sys.modules
assert "keystroke_dynamics.api.auth" not in sys.modules
assert "keystroke_dynamics.api.profile" not in sys.modules

client = TestClient(app, headers={"origin": "http://testserver"})

assert client.get("/health").status_code == 200

# The game page itself lives at "/" in this mode (api/pages.py).
home = client.get("/")
assert home.status_code == 200
assert "/static/js/party.js" in home.text
assert home.headers["content-security-policy"].startswith("default-src 'self'")

# No old nav/page survives into this page's own body -- Party is the
# only thing a visitor sees in this mode. Checked by href/class, not
# visible text -- this page's own brand button is legitimately named
# "Typing Twin", so a plain substring check for that phrase would be
# a false positive.
for old_marker in (
    'href="/create-profile"',
    'href="/authenticate"',
    'href="/how-it-works"',
    'href="/about"',
    'href="/finish"',
    'href="/typing-twin"',
    "site-header",  # base.html's own header class -- this page doesn't extend it
    "static/css/styles.css",  # the old pages' own stylesheet
):
    assert old_marker not in home.text, old_marker

# The game's old path redirects to its new one instead of 404ing.
party_redirect = client.get("/party", follow_redirects=False)
assert party_redirect.status_code == 308, party_redirect.status_code
assert party_redirect.headers["location"] == "/"

for path in ("/api/register", "/api/login", "/api/logout"):
    assert client.post(path, json={}).status_code == 404, path
assert client.post("/api/profile/samples", json={}).status_code == 404
assert client.post("/api/profile/verify", json={}).status_code == 404
assert client.delete("/api/profile").status_code == 404
for path in (
    "/create-profile",
    "/authenticate",
    "/how-it-works",
    "/about",
    "/finish",
    "/typing-twin",
):
    assert client.get(path).status_code == 404, path

# A full game, end to end, with no database at all.
party = client.post("/api/game/party", json={"level": "word"}).json()
assert party["phrase"] == "nukiae"

LINE = [
    {"code": "KeyN", "action": "down", "t_ms": 0.0},
    {"code": "KeyN", "action": "up", "t_ms": 80.0},
    {"code": "KeyU", "action": "down", "t_ms": 230.0},
    {"code": "KeyU", "action": "up", "t_ms": 310.0},
    {"code": "KeyK", "action": "down", "t_ms": 460.0},
    {"code": "KeyK", "action": "up", "t_ms": 540.0},
    {"code": "KeyI", "action": "down", "t_ms": 690.0},
    {"code": "KeyI", "action": "up", "t_ms": 770.0},
    {"code": "KeyA", "action": "down", "t_ms": 920.0},
    {"code": "KeyA", "action": "up", "t_ms": 1000.0},
    {"code": "KeyE", "action": "down", "t_ms": 1150.0},
    {"code": "KeyE", "action": "up", "t_ms": 1230.0},
]
player = client.post(
    "/api/game/players", json={"name": "Alice", "training_lines": [LINE] * 5}
).json()
assert player["name"] == "Alice"

attack = client.post(
    "/api/game/attempts",
    json={
        "typist_id": None,
        "target_id": player["id"],
        "mode": "attack",
        "events": LINE,
        "client_attempt_id": "attempt-1",
    },
)
assert attack.status_code == 200, attack.text

replay = client.post("/api/game/replay", json={"target_id": player["id"]})
assert replay.status_code == 200, replay.text

renamed = client.patch(f"/api/game/players/{player['id']}", json={"name": "Alicia"})
assert renamed.status_code == 200, renamed.text
assert renamed.json()["name"] == "Alicia"

deleted = client.delete(f"/api/game/players/{player['id']}")
assert deleted.status_code == 204

reset = client.post("/api/game/party/reset")
assert reset.status_code == 204

print("OK")
