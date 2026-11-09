"""End-to-end: a real game, driven over HTTP, with score collection
turned on against the real scores test database -- docs/plans/done/PARTY_LAUNCH_PLAN.md
section 10's own "Done when" requirement that a real Postgres test
confirms the consent rule, stored column values, and the "Delete me"/
"New party" cascades. Needs a fresh process (see
tests/_scores_enabled_subprocess.py's own docstring for why) that
isn't a pytest module itself.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tests.scores.conftest import SCORES_TEST_DATABASE_URL

SCRIPT = Path(__file__).parent.parent / "_scores_enabled_subprocess.py"


def test_a_full_game_with_scores_on_records_only_consenting_attempts() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), SCORES_TEST_DATABASE_URL],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout
