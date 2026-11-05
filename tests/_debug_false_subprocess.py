"""Not a pytest module -- a standalone script run in a fresh
subprocess by tests/test_debug_route_absent.py. settings.debug is
read once, at import time, to decide whether api/game.py even
registers POST /api/game/debug/record-target -- a fresh process is
the only way to actually exercise "absent outside debug mode", same
reasoning as _public_mode_subprocess.py.

Prints "OK" and exits 0 on success.
"""

from __future__ import annotations

import os

os.environ["ENABLE_ACCOUNTS"] = "false"
os.environ["DEBUG"] = "false"
os.environ["SESSION_SECRET"] = "a-real-looking-secret-not-the-example-placeholder"
os.environ["ALLOWED_ORIGIN"] = "http://testserver"
os.environ.pop("DATABASE_URL", None)

from fastapi.testclient import TestClient  # noqa: E402

from keystroke_dynamics.main import app  # noqa: E402

client = TestClient(app, headers={"origin": "http://testserver"})

assert client.get("/health").status_code == 200

resp = client.post(
    "/api/game/debug/record-target",
    json={"name": "Yuliia", "lines": {"word": [[]]}},
)
assert resp.status_code == 404, resp.status_code

print("OK")
