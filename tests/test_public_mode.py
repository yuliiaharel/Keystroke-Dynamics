"""Public mode (ENABLE_ACCOUNTS=false, no DATABASE_URL): the app
starts and a full game can be played with no database at all, and
the account system's routes and its own db.session module are never
even imported. See _public_mode_subprocess.py for why this has to run
in a fresh subprocess rather than just flipping a setting in-process.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent / "_public_mode_subprocess.py"


def test_the_app_starts_and_a_full_game_works_with_no_database() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout
