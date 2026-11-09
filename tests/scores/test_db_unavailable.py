"""docs/plans/done/PARTY_LAUNCH_PLAN.md section 10's own 'Done when' bullet: 'a
stopped, slow, or unavailable database doesn't delay requests or
break a game.' Needs a fresh process -- see
tests/_scores_db_unavailable_subprocess.py's own docstring for why.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "_scores_db_unavailable_subprocess.py"


def test_a_full_game_stays_fast_with_the_scores_database_unreachable() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout
