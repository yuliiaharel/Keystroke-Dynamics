"""Turns one judged game attempt into a score_attempts row, or
decides there's nothing to record -- docs/plans/done/PARTY_LAUNCH_PLAN.md section
10's consent rule and column mapping. Pure and side-effect free:
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
from keystroke_dynamics.game.store import Mode

#: score_attempts.target_kind's own vocabulary -- deliberately not
#: game/schemas.py's PlayerView.kind TargetKind ("player"/"sample"/
#: "target"), which is the frontend-facing label set; this is the
#: plan's own table definition's wording instead.
ScoreTargetKind = Literal["player", "simulated", "permanent"]

#: This game captures keystrokes from a physical keyboard only -- see
#: game/judge.py's _clue() docstring on why there's no touch
#: ("place") dimension yet. A constant, not a setting: there's
#: nothing to configure until the touch version (out of scope for
#: this launch) exists.
DEVICE_TYPE = "keyboard"


def should_record_score(
    *, typist_consents: bool, target_kind: ScoreTargetKind, target_consents: bool
) -> bool:
    """ "Store an attempt only if the typist opted in, and the target
    opted in or is simulated or permanent."

    typist_consents is always True for a server-run replay (there's no
    real typist to consent -- see api/game.py's create_replay); for
    every other mode it's the real typist's own choice (a stored
    Player.shares_scores, or a Guest's per-attack flag).
    """
    if not typist_consents:
        return False
    return target_consents if target_kind == "player" else True


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
    consent_version: str,
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
        "consent_version": consent_version,
        "device_type": DEVICE_TYPE,
        "line_id": line_id,
        "mode": mode,
        "target_kind": target_kind,
        "party_id": party_id,
        "typist_id": typist_id,
        "target_id": target_id,
        "training_lines": training_lines,
        "compared_features": verdict.compared_features,
        # rhythm and total hold the same value -- this game has no
        # touch-position dimension to combine rhythm with (see
        # game/judge.py's _clue() docstring). Populated whenever a
        # distance was computed at all, even for an attempt that
        # didn't count toward the party's own live tally (a disguise
        # attempt disqualified by the pace gate still has a real,
        # meaningful distance) -- only "unusable" (no distance at
        # all) leaves these null.
        "rhythm": verdict.distance,
        "place": None,
        "total": verdict.distance,
        "limit_value": limit_value,
        "pace": pace,
        "outcome": outcome,
    }
