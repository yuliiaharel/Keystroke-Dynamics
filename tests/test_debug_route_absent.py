"""POST /api/game/debug/record-target (PARTY_LAUNCH_PLAN.md Part 1
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
