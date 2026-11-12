"""POST /api/game/debug/record-target (docs/plans/done/PARTY_LAUNCH_PLAN.md Part 1
section 7) must not exist at all outside debug mode -- not just
reject the request. See _debug_false_subprocess.py for why this
needs a fresh process rather than flipping a setting in-process."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent / "_debug_false_subprocess.py"


def test_record_target_route_does_not_exist_outside_debug_mode() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_touch_capture_page_exists_in_debug_mode() -> None:
    # The other half of "debug only" (docs/plans/active/MOBILE_PLAN.md Phase 0): the
    # subprocess above proves the page is absent when DEBUG=false, and
    # this proves that check isn't passing just because the path is
    # wrong. conftest.py runs this process with DEBUG=true.
    from fastapi.testclient import TestClient

    from keystroke_dynamics.main import app

    resp = TestClient(app).get("/debug/touch-capture")

    assert resp.status_code == 200
    assert "/static/js/touch-capture.js" in resp.text
    assert "/static/css/touch-capture.css" in resp.text
    assert "fonts.googleapis.com" not in resp.text
    csp = resp.headers["content-security-policy"]
    script_src = next(d for d in csp.split(";") if d.strip().startswith("script-src"))
    assert script_src.strip() == "script-src 'self'"
