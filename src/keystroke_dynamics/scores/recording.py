"""Turns one judged game attempt into a score_attempts row --
docs/plans/done/PARTY_LAUNCH_PLAN.md section 10's column mapping. Every attempt is
recorded; there's no per-player choice. Pure and side-effect free:
callers (api/game.py) own checking settings.scores_database_url is
set at all, and actually enqueueing the result (scores/writer.py).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Literal

from keystroke_dynamics.game.judge import Verdict
from keystroke_dynamics.game.levels import Level
from keystroke_dynamics.game.scoring import SCORING_VERSION
from keystroke_dynamics.game.screen import ScreenSize
from keystroke_dynamics.game.store import DeviceType, Mode

#: score_attempts.target_kind's own vocabulary -- deliberately not
#: game/schemas.py's PlayerView.kind TargetKind ("player"/"sample"/
#: "target"), which is the frontend-facing label set; this is the
#: plan's own table definition's wording instead.
ScoreTargetKind = Literal["player", "simulated", "permanent"]

#: score_attempts.device_type for a row whose caller doesn't say --
#: a physical keyboard, which is all there was before touch rooms.
DEVICE_TYPE: DeviceType = "keyboard"

#: Written to score_attempts.consent_version on every row. The column
#: keeps its original name (its migration is never edited), but it now
#: records which wording of the site's score-saving notice
#: (frontend/src/scores-memo.ts) was on screen, not a choice anyone
#: made. "1" was the old opt-in checkbox: those rows came only from
#: players who ticked it. "2" is automatic saving, so analysis can
#: tell the self-selected rows from the rest. Bump it in the same
#: change that materially edits the notice.
NOTICE_VERSION = "2"


def build_score_row(
    *,
    verdict: Verdict,
    pace: float | None,
    mode: Mode,
    target_kind: ScoreTargetKind,
    line_id: Level,
    party_id: str,
    typist_id: str,
    target_id: str,
    training_lines: int,
    limit_value: float,
    same_keyboard: bool | None,
    device_type: DeviceType = DEVICE_TYPE,
    screen_size: ScreenSize | None = None,
) -> dict[str, object]:
    """Builds the row dict scores/writer.py's InsertRow carries.
    party_id/typist_id/target_id must already be score_ids (random,
    never the game's own ids -- game/store.py's Player.score_id/
    Party.score_id, or scores/target_ids.py for the sample bots and
    the permanent target), never checked here: this function has no
    way to tell a score_id from any other string.
    """
    if verdict.distance is None:
        outcome = "unusable"
    elif verdict.distance <= limit_value:
        outcome = "pass"
    else:
        outcome = "fail"
    return {
        "id": str(uuid.uuid4()),
        "created_on": datetime.date.today(),
        "scoring_version": SCORING_VERSION,
        "consent_version": NOTICE_VERSION,
        "device_type": device_type,
        "line_id": line_id,
        "mode": mode,
        "target_kind": target_kind,
        "party_id": party_id,
        "typist_id": typist_id,
        "target_id": target_id,
        "training_lines": training_lines,
        "compared_features": verdict.compared_features,
        # A keyboard row's rhythm and total hold the same value, and
        # its place stays null: a physical keyboard has no tap
        # position to combine rhythm with. A touch row has all three:
        # the timing-only score, the position-only score, and the
        # distance the limit was applied to. Scores only -- never a
        # tap position or a timing (docs/plans/active/MOBILE_PLAN.md
        # Phase 1 section 6).
        #
        # Populated whenever a distance was computed at all, even for
        # an attempt that didn't count toward the party's own live
        # tally (a disguise attempt disqualified by the pace gate
        # still has a real, meaningful distance) -- only "unusable"
        # (no distance at all) leaves these null.
        "rhythm": verdict.rhythm if device_type == "touch" else verdict.distance,
        "place": verdict.place if device_type == "touch" else None,
        "total": verdict.distance,
        "limit_value": limit_value,
        "pace": pace,
        "outcome": outcome,
        # Whether typist and target share a room member (a keyboard)
        # -- docs/plans/active/ROOMS_PLAN.md Phase 1 section 5. A plain
        # true/false/null, not an id: it says nothing about who. In a
        # touch room the "keyboard" is the phone.
        "same_keyboard": same_keyboard,
        # Touch rows only: roughly how wide the typist's screen was
        # (game/screen.py), since key size can move tap positions.
        # One of four buckets, null when the browser didn't say, and
        # always null for a keyboard row.
        "screen_size": screen_size if device_type == "touch" else None,
    }
