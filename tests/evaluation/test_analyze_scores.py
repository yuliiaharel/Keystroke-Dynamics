"""evaluation/analyze_scores.py's own computation functions, against
plain constructed Row objects -- no database. See
tests/scores/test_analyze_scores_integration.py for fetch_rows()
itself, against the real scores test database.
"""

from __future__ import annotations

import datetime

from evaluation.analyze_scores import (
    MIN_GROUP_SIZE,
    Row,
    attack_rates_by_keyboard,
    attempts_per_player_and_party,
    distinct_scoring_versions,
    false_reject_and_accept_rates,
    flag_suspicious_bursts,
    keyboard_label,
    pace_bucket,
    rates_by_group,
    rhythm_vs_place,
)

DAY = datetime.date(2026, 1, 1)


def _row(**overrides: object) -> Row:
    defaults: dict[str, object] = {
        "scoring_version": "1",
        "device_type": "keyboard",
        "mode": "self",
        "target_kind": "player",
        "party_id": "party-1",
        "typist_id": "typist-1",
        "created_on": DAY,
        "rhythm": 1.0,
        "place": None,
        "pace": 1.0,
        "outcome": "pass",
    }
    defaults.update(overrides)
    return Row(**defaults)  # type: ignore[arg-type]


# ---------- pace_bucket ----------


def test_pace_bucket_boundaries() -> None:
    assert pace_bucket(None) == "unknown"
    assert pace_bucket(0.84) == "fast"
    assert pace_bucket(0.85) == "in-band"  # inclusive
    assert pace_bucket(1.0) == "in-band"
    assert pace_bucket(1.15) == "in-band"  # inclusive
    assert pace_bucket(1.16) == "slow"


# ---------- false_reject_and_accept_rates ----------


def test_frr_counts_self_mode_rows_above_the_limit() -> None:
    rows = [_row(mode="self", rhythm=r) for r in [0.5, 0.9, 1.0, 1.1, 1.5]]
    result = false_reject_and_accept_rates(rows, limit=1.0)
    frr = next(r for r in result if r.kind == "false reject")
    # 1.1 and 1.5 exceed the limit -> 2 of 5 rejected.
    assert frr.n == 5
    assert frr.rate == 2 / 5


def test_far_counts_attack_mode_rows_at_or_under_the_limit() -> None:
    rows = [_row(mode="attack", rhythm=r) for r in [0.5, 0.9, 1.0, 1.1, 1.5]]
    result = false_reject_and_accept_rates(rows, limit=1.0)
    far = next(r for r in result if r.kind == "false accept")
    # 0.5, 0.9, 1.0 are at or under the limit -> 3 of 5 accepted.
    assert far.n == 5
    assert far.rate == 3 / 5


def test_groups_smaller_than_min_size_are_hidden() -> None:
    rows = [_row(mode="self", rhythm=0.5) for _ in range(MIN_GROUP_SIZE - 1)]
    assert false_reject_and_accept_rates(rows, limit=1.0) == []


def test_unusable_rows_never_count_toward_either_rate() -> None:
    usable = [_row(mode="self", rhythm=0.5) for _ in range(5)]
    unusable = [_row(mode="self", rhythm=None, outcome="unusable") for _ in range(5)]
    result = false_reject_and_accept_rates(usable + unusable, limit=1.0)
    frr = next(r for r in result if r.kind == "false reject")
    assert frr.n == 5  # the 5 unusable rows are excluded entirely


def test_disguise_and_replay_modes_are_excluded_from_far_frr() -> None:
    rows = [_row(mode="disguise", rhythm=0.5) for _ in range(5)] + [
        _row(mode="replay", rhythm=0.5) for _ in range(5)
    ]
    assert false_reject_and_accept_rates(rows, limit=1.0) == []


# ---------- rates_by_group ----------


def test_rates_by_group_slices_by_device_type() -> None:
    keyboard = [_row(mode="attack", device_type="keyboard", rhythm=0.5) for _ in range(5)]
    touch = [_row(mode="attack", device_type="touch", rhythm=5.0) for _ in range(5)]
    result = rates_by_group(
        keyboard + touch,
        limit=1.0,
        group_key=lambda r: r.device_type,
        group_label_prefix="device_type",
    )
    labels = {r.label: r.rate for r in result}
    assert labels["device_type=keyboard, limit 1.0"] == 1.0
    assert labels["device_type=touch, limit 1.0"] == 0.0


# ---------- rhythm_vs_place ----------


def test_rhythm_vs_place_hides_place_with_too_few_values() -> None:
    rows = [_row(rhythm=float(i), place=None) for i in range(10)]
    result = rhythm_vs_place(rows)
    assert result["rhythm"] is not None
    assert result["rhythm"]["n"] == 10
    assert result["place"] is None


def test_rhythm_vs_place_reports_place_once_there_is_enough() -> None:
    rows = [_row(rhythm=1.0, place=float(i)) for i in range(5)]
    result = rhythm_vs_place(rows)
    assert result["place"] is not None
    assert result["place"]["n"] == 5
    assert result["place"]["mean"] == 2.0  # 0,1,2,3,4


# ---------- flag_suspicious_bursts ----------


def test_flags_a_typist_over_the_burst_threshold_in_one_day() -> None:
    from evaluation.analyze_scores import BURST_THRESHOLD_PER_DAY

    busy = [_row(typist_id="t1", party_id=f"p{i}") for i in range(BURST_THRESHOLD_PER_DAY + 1)]
    flags = flag_suspicious_bursts(busy)
    typist_flags = [f for f in flags if f.id_kind == "typist_id"]
    assert len(typist_flags) == 1
    assert typist_flags[0].id_value == "t1"
    assert typist_flags[0].count == BURST_THRESHOLD_PER_DAY + 1


def test_no_flag_under_the_threshold() -> None:
    from evaluation.analyze_scores import BURST_THRESHOLD_PER_DAY

    normal = [_row(typist_id="t1") for _ in range(BURST_THRESHOLD_PER_DAY)]
    assert flag_suspicious_bursts(normal) == []


def test_burst_flag_is_per_day_not_overall() -> None:
    from evaluation.analyze_scores import BURST_THRESHOLD_PER_DAY

    day_a = [_row(typist_id="t1", created_on=DAY) for _ in range(BURST_THRESHOLD_PER_DAY)]
    day_b = [
        _row(typist_id="t1", created_on=DAY + datetime.timedelta(days=1))
        for _ in range(BURST_THRESHOLD_PER_DAY)
    ]
    # Over the threshold combined, but never on one single day.
    assert flag_suspicious_bursts(day_a + day_b) == []


# ---------- attempts_per_player_and_party / distinct_scoring_versions ----------


def test_attempts_per_player_and_party_counts_distinct_ids() -> None:
    rows = [
        _row(typist_id="t1", party_id="p1"),
        _row(typist_id="t1", party_id="p1"),
        _row(typist_id="t2", party_id="p1"),
    ]
    counts = attempts_per_player_and_party(rows)
    assert counts["distinct typists"] == 2
    assert counts["distinct parties"] == 1
    assert counts["total attempts"] == 3


def test_distinct_scoring_versions_sorted() -> None:
    rows = [_row(scoring_version="2"), _row(scoring_version="1")]
    assert distinct_scoring_versions(rows) == ["1", "2"]


# ---------- same keyboard vs different ----------


def test_keyboard_label() -> None:
    assert keyboard_label(True) == "same"
    assert keyboard_label(False) == "different"
    assert keyboard_label(None) == "not recorded"


def test_attack_rates_are_split_by_same_keyboard() -> None:
    # Same keyboard: 5 attacks, 4 at or under the limit -> 4/5 accepted.
    # Different keyboard: 5 attacks, 1 at or under -> 1/5 accepted.
    rows = [
        _row(mode="attack", same_keyboard=True, rhythm=r) for r in [0.5, 0.6, 0.7, 0.8, 2.0]
    ] + [_row(mode="attack", same_keyboard=False, rhythm=r) for r in [0.5, 2.0, 2.1, 2.2, 2.3]]
    result = {r.label: r for r in attack_rates_by_keyboard(rows, limit=1.0)}
    assert set(result) == {"keyboard=same, limit 1.0", "keyboard=different, limit 1.0"}
    assert result["keyboard=same, limit 1.0"].rate == 4 / 5
    assert result["keyboard=different, limit 1.0"].rate == 1 / 5
    assert all(r.kind == "false accept" and r.n == 5 for r in result.values())


def test_rows_from_before_rooms_form_their_own_not_recorded_group() -> None:
    rows = [_row(mode="attack", same_keyboard=None, rhythm=0.5) for _ in range(MIN_GROUP_SIZE)]
    result = attack_rates_by_keyboard(rows, limit=1.0)
    assert [r.label for r in result] == ["keyboard=not recorded, limit 1.0"]


def test_keyboard_split_ignores_self_rows_and_non_player_targets() -> None:
    rows = (
        [_row(mode="self", same_keyboard=True) for _ in range(MIN_GROUP_SIZE)]
        + [
            _row(mode="attack", target_kind="simulated", same_keyboard=None)
            for _ in range(MIN_GROUP_SIZE)
        ]
        + [_row(mode="replay", same_keyboard=None) for _ in range(MIN_GROUP_SIZE)]
    )
    assert attack_rates_by_keyboard(rows, limit=1.0) == []


def test_keyboard_split_hides_a_group_below_the_minimum_size() -> None:
    rows = [_row(mode="attack", same_keyboard=True) for _ in range(MIN_GROUP_SIZE)] + [
        _row(mode="attack", same_keyboard=False) for _ in range(MIN_GROUP_SIZE - 1)
    ]
    assert [r.label for r in attack_rates_by_keyboard(rows, limit=1.0)] == [
        "keyboard=same, limit 1.0"
    ]
