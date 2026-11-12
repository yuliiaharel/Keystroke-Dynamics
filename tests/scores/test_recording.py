"""scores/recording.py: the score_attempts column mapping, a pure
function -- no database, no app wiring."""

from __future__ import annotations

import pytest

from keystroke_dynamics.game.judge import Verdict
from keystroke_dynamics.game.scoring import SCORING_VERSION
from keystroke_dynamics.scores.models import ScoreAttempt
from keystroke_dynamics.scores.recording import DEVICE_TYPE, NOTICE_VERSION, build_score_row


def _verdict(**overrides: object) -> Verdict:
    defaults: dict[str, object] = {
        "word": "Caught!",
        "text": "...",
        "counted": True,
        "passed": False,
        "distance": 2.0,
        "ratio": 1.33,
        "pace": 1.0,
        "clue": "Right speed, wrong rhythm",
        "compared_features": 11,
    }
    defaults.update(overrides)
    return Verdict(**defaults)  # type: ignore[arg-type]


# ---------- build_score_row ----------


def _row(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "verdict": _verdict(),
        "pace": 1.0,
        "mode": "attack",
        "target_kind": "player",
        "line_id": "word",
        "party_id": "party-score-id",
        "typist_id": "typist-score-id",
        "target_id": "target-score-id",
        "training_lines": 5,
        "limit_value": 1.5,
        "same_keyboard": True,
    }
    defaults.update(overrides)
    return build_score_row(**defaults)  # type: ignore[arg-type]


def test_row_carries_the_given_ids_and_version_constants() -> None:
    row = _row()
    assert row["party_id"] == "party-score-id"
    assert row["typist_id"] == "typist-score-id"
    assert row["target_id"] == "target-score-id"
    assert row["scoring_version"] == SCORING_VERSION
    # Not "1": that value marks rows from the old opt-in checkbox.
    assert row["consent_version"] == NOTICE_VERSION == "2"
    assert row["device_type"] == DEVICE_TYPE == "keyboard"


def test_row_has_exactly_the_table_columns_and_nothing_else() -> None:
    # Automatic saving must store the same fields the opted-in rows
    # always had -- no name, keystrokes, timings, or IP can ride along.
    assert set(_row()) == {column.name for column in ScoreAttempt.__table__.columns}


@pytest.mark.parametrize("same_keyboard", [True, False, None])
def test_same_keyboard_passes_through(same_keyboard: bool | None) -> None:
    assert _row(same_keyboard=same_keyboard)["same_keyboard"] is same_keyboard


def test_rhythm_and_total_mirror_distance_place_stays_null() -> None:
    row = _row(verdict=_verdict(distance=2.0))
    assert row["rhythm"] == 2.0
    assert row["total"] == 2.0
    assert row["place"] is None


def test_outcome_pass_when_distance_is_at_or_under_the_limit() -> None:
    row = _row(verdict=_verdict(distance=1.5), limit_value=1.5)
    assert row["outcome"] == "pass"


def test_outcome_fail_when_distance_exceeds_the_limit() -> None:
    row = _row(verdict=_verdict(distance=1.51), limit_value=1.5)
    assert row["outcome"] == "fail"


def test_outcome_unusable_when_there_is_no_distance_at_all() -> None:
    row = _row(
        verdict=_verdict(
            distance=None, ratio=None, pace=None, clue=None, counted=False, passed=None
        ),
        pace=None,
    )
    assert row["outcome"] == "unusable"
    assert row["rhythm"] is None
    assert row["total"] is None


def test_outcome_is_pass_fail_even_for_an_uncounted_disguise_pace_rejection() -> None:
    # A disguise attempt disqualified by the pace gate still has a
    # real, meaningful distance -- counted=False only means it didn't
    # count toward the party's own live tally, not that the rhythm
    # itself was unusable.
    row = _row(verdict=_verdict(distance=0.5, counted=False, passed=None), limit_value=1.5)
    assert row["outcome"] == "pass"
    assert row["rhythm"] == 0.5


def test_compared_features_and_training_lines_pass_through() -> None:
    row = _row(verdict=_verdict(compared_features=7), training_lines=6)
    assert row["compared_features"] == 7
    assert row["training_lines"] == 6


def test_pace_is_the_given_value_not_the_verdicts_own() -> None:
    # build_score_row takes pace as its own argument (game/judge.py's
    # pace_ratio(), always available) rather than reading
    # verdict.pace (None exactly when distance is None, the UI's own
    # display rule) -- this is exactly the case that distinguishes
    # them.
    row = _row(verdict=_verdict(distance=None, pace=None), pace=0.92)
    assert row["pace"] == 0.92


# ---------- touch rows (docs/plans/active/MOBILE_PLAN.md Phase 1 section 6) ----------


def _touch_row(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "verdict": _verdict(distance=1.4, rhythm=1.1, place=2.0, compared_features=84),
        "device_type": "touch",
        "line_id": "touch",
    }
    defaults.update(overrides)
    return _row(**defaults)


def test_a_touch_row_stores_rhythm_place_and_total_separately() -> None:
    row = _touch_row()
    assert row["device_type"] == "touch"
    assert row["line_id"] == "touch"
    assert row["rhythm"] == 1.1
    assert row["place"] == 2.0
    assert row["total"] == 1.4
    assert row["compared_features"] == 84


def test_a_touch_rows_outcome_comes_from_the_total_not_from_rhythm_or_place() -> None:
    # Rhythm alone is under the limit and place alone is over it; the
    # distance the limit was applied to decides.
    assert _touch_row(limit_value=1.65)["outcome"] == "pass"
    assert _touch_row(limit_value=1.3)["outcome"] == "fail"


def test_an_unusable_touch_row_has_no_scores() -> None:
    row = _touch_row(
        verdict=_verdict(
            distance=None, ratio=None, pace=None, clue=None, counted=False, passed=None
        ),
    )
    assert row["outcome"] == "unusable"
    assert row["rhythm"] is None and row["place"] is None and row["total"] is None


@pytest.mark.parametrize("mode", ["attack", "self", "grip", "replay"])
def test_a_touch_row_keeps_its_mode(mode: str) -> None:
    assert _touch_row(mode=mode)["mode"] == mode


@pytest.mark.parametrize("same_keyboard", [True, False, None])
def test_a_touch_row_fills_same_keyboard_by_the_same_rule(same_keyboard: bool | None) -> None:
    assert _touch_row(same_keyboard=same_keyboard)["same_keyboard"] is same_keyboard


def test_a_touch_row_has_exactly_the_table_columns_and_nothing_else() -> None:
    # No tap position, no timing: the same fixed set of columns a
    # keyboard row has.
    assert set(_touch_row()) == {column.name for column in ScoreAttempt.__table__.columns}


@pytest.mark.parametrize("screen_size", ["small", "medium", "large", "xlarge", None])
def test_a_touch_row_carries_the_typists_screen_size_bucket(screen_size: str | None) -> None:
    assert _touch_row(screen_size=screen_size)["screen_size"] == screen_size


def test_a_keyboard_row_never_has_a_screen_size() -> None:
    assert _row()["screen_size"] is None
    # Not even if a caller passes one.
    assert _row(screen_size="large")["screen_size"] is None


def test_a_keyboard_row_ignores_rhythm_and_place_on_the_verdict() -> None:
    # A keyboard verdict never has them, but the row must not depend
    # on that: a keyboard row's place is always empty.
    row = _row(verdict=_verdict(distance=2.0, rhythm=1.0, place=3.0))
    assert row["rhythm"] == 2.0
    assert row["place"] is None
    assert row["total"] == 2.0
