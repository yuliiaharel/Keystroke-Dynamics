"""scores/recording.py: the consent rule and the score_attempts
column mapping, both pure functions -- no database, no app wiring."""

from __future__ import annotations

from keystroke_dynamics.game.judge import Verdict
from keystroke_dynamics.game.scoring import SCORING_VERSION
from keystroke_dynamics.scores.recording import DEVICE_TYPE, build_score_row, should_record_score


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


# ---------- should_record_score ----------


def test_requires_typist_consent_regardless_of_target() -> None:
    assert (
        should_record_score(typist_consents=False, target_kind="player", target_consents=True)
        is False
    )
    assert (
        should_record_score(typist_consents=False, target_kind="simulated", target_consents=True)
        is False
    )


def test_a_real_player_target_also_needs_their_own_consent() -> None:
    assert (
        should_record_score(typist_consents=True, target_kind="player", target_consents=False)
        is False
    )
    assert (
        should_record_score(typist_consents=True, target_kind="player", target_consents=True)
        is True
    )


def test_simulated_and_permanent_targets_never_need_their_own_consent() -> None:
    assert (
        should_record_score(typist_consents=True, target_kind="simulated", target_consents=False)
        is True
    )
    assert (
        should_record_score(typist_consents=True, target_kind="permanent", target_consents=False)
        is True
    )


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
        "consent_version": "1",
    }
    defaults.update(overrides)
    return build_score_row(**defaults)  # type: ignore[arg-type]


def test_row_carries_the_given_ids_and_version_constants() -> None:
    row = _row()
    assert row["party_id"] == "party-score-id"
    assert row["typist_id"] == "typist-score-id"
    assert row["target_id"] == "target-score-id"
    assert row["scoring_version"] == SCORING_VERSION
    assert row["consent_version"] == "1"
    assert row["device_type"] == DEVICE_TYPE == "keyboard"


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
