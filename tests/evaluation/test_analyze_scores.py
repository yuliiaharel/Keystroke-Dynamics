"""evaluation/analyze_scores.py's own computation functions, against
plain constructed Row objects -- no database. See
tests/scores/test_analyze_scores_integration.py for fetch_rows()
itself, against the real scores test database.
"""

from __future__ import annotations

import datetime

import pytest

from evaluation.analyze_scores import (
    MIN_GROUP_SIZE,
    HiddenGroup,
    Row,
    analyze,
    attack_rates_by_keyboard,
    attempts_per_player_and_party,
    distinct_scoring_versions,
    false_reject_and_accept_rates,
    flag_suspicious_bursts,
    hidden_line,
    keyboard_label,
    limit_bucket,
    limit_bucket_labels,
    limit_distributions,
    pace_bucket,
    pass_rates_at_own_limit,
    rates_by_group,
    rhythm_vs_place,
    upper_clamp_for,
)
from keystroke_dynamics.game.scoring import GAME_MAX_THRESHOLD, GAME_MIN_THRESHOLD

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
        "target_id": "target-1",
        "limit_value": 2.0,
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


# ---------- limits actually given ----------


@pytest.mark.parametrize(
    ("limit_value", "upper_clamp", "expected"),
    [
        # scoring_version 1: limits clamped to 1.3-3.5.
        (GAME_MIN_THRESHOLD, 3.5, "at 1.3 (lower clamp)"),
        (1.31, 3.5, "1.3 to under 2.0"),
        (1.99, 3.5, "1.3 to under 2.0"),
        (2.0, 3.5, "2.0 to under 2.5"),
        (2.5, 3.5, "2.5 to under 3.0"),
        (3.0, 3.5, "3.0 to under 3.5"),
        (3.49, 3.5, "3.0 to under 3.5"),
        (3.5, 3.5, "at 3.5 (upper clamp)"),
        # scoring_version 2: 1.3-2.0, so 2.0 is now the clamp itself.
        (GAME_MIN_THRESHOLD, 2.0, "at 1.3 (lower clamp)"),
        (1.99, 2.0, "1.3 to under 2.0"),
        (2.0, 2.0, "at 2.0 (upper clamp)"),
    ],
)
def test_limit_bucket_boundaries(limit_value: float, upper_clamp: float, expected: str) -> None:
    assert limit_bucket(limit_value, upper_clamp) == expected
    assert expected in limit_bucket_labels(upper_clamp)


def test_each_scoring_version_is_bucketed_by_its_own_upper_clamp() -> None:
    assert upper_clamp_for("1") == 3.5
    assert upper_clamp_for("2") == GAME_MAX_THRESHOLD == 2.0
    assert limit_bucket_labels(upper_clamp_for("2")) == [
        "at 1.3 (lower clamp)",
        "1.3 to under 2.0",
        "at 2.0 (upper clamp)",
    ]


def test_limit_distribution_counts_each_target_once() -> None:
    # Target a is attacked 4 times, b and c once each: 6 attempts, but
    # the statistics are over the 3 targets' limits, not the 6 rows.
    rows = (
        [_row(target_id="a", limit_value=1.3) for _ in range(4)]
        + [_row(target_id="b", limit_value=2.2)]
        + [_row(target_id="c", limit_value=3.5)]
    )
    (dist,) = limit_distributions(rows, upper_clamp=3.5)
    assert dist.target_kind == "player"
    assert dist.targets == 3
    assert dist.attempts == 6
    assert (dist.minimum, dist.median, dist.maximum) == (1.3, 2.2, 3.5)
    assert dist.buckets == {
        "at 1.3 (lower clamp)": 1,
        "1.3 to under 2.0": 0,
        "2.0 to under 2.5": 1,
        "2.5 to under 3.0": 0,
        "3.0 to under 3.5": 0,
        "at 3.5 (upper clamp)": 1,
    }


def test_limit_distribution_is_split_by_target_kind() -> None:
    rows = [_row(target_kind="player", target_id=f"p{i}", limit_value=3.0) for i in range(5)] + [
        _row(target_kind="simulated", target_id=f"s{i}", limit_value=1.5) for i in range(5)
    ]
    by_kind = {d.target_kind: d for d in limit_distributions(rows)}
    assert by_kind["player"].median == 3.0
    assert by_kind["simulated"].median == 1.5


def test_limit_distribution_hides_a_small_target_kind_and_says_so() -> None:
    rows = [_row(target_kind="permanent") for _ in range(MIN_GROUP_SIZE - 1)]
    hidden: list[HiddenGroup] = []
    assert limit_distributions(rows, hidden) == []
    assert hidden == [HiddenGroup("target_kind=permanent", MIN_GROUP_SIZE - 1)]


# ---------- real pass rate at each attempt's own limit ----------


def test_pass_rate_uses_each_attempts_own_limit() -> None:
    # The same rhythm (2.0) passes under a 3.5 limit and fails under a
    # 1.3 one -- no single hypothetical limit reproduces this.
    rows = [_row(mode="attack", rhythm=2.0, limit_value=3.5) for _ in range(3)] + [
        _row(mode="attack", rhythm=2.0, limit_value=1.3) for _ in range(2)
    ]
    (attack,) = pass_rates_at_own_limit(rows)
    assert (attack.mode, attack.n, attack.at_or_under) == ("attack", 5, 3)
    assert attack.rate == 3 / 5


def test_pass_rate_counts_a_rhythm_exactly_at_the_limit_as_passing() -> None:
    rows = [_row(mode="self", rhythm=2.0, limit_value=2.0) for _ in range(5)]
    (own,) = pass_rates_at_own_limit(rows)
    assert own.rate == 1.0


def test_pass_rate_is_reported_per_mode() -> None:
    rows = [_row(mode="self", rhythm=1.0, limit_value=2.0) for _ in range(5)] + [
        _row(mode="attack", rhythm=3.0, limit_value=2.0) for _ in range(5)
    ]
    rates = {o.mode: o.rate for o in pass_rates_at_own_limit(rows)}
    assert rates == {"self": 1.0, "attack": 0.0}


def test_pass_rate_ignores_unusable_rows_and_hides_a_small_mode() -> None:
    rows = [_row(mode="attack", rhythm=1.0) for _ in range(MIN_GROUP_SIZE - 1)] + [
        _row(mode="attack", rhythm=None, outcome="unusable") for _ in range(5)
    ]
    hidden: list[HiddenGroup] = []
    assert pass_rates_at_own_limit(rows, hidden) == []
    # 4 scorable attempts, not 9: the unusable rows don't count.
    assert hidden == [HiddenGroup("mode=attack", MIN_GROUP_SIZE - 1)]


# ---------- hidden groups are reported, not silently dropped ----------


def test_hidden_line_gives_the_size_and_the_reason() -> None:
    line = hidden_line(HiddenGroup("mode=attack", 3))
    assert line == (
        "hidden: mode=attack -- 3 attempt(s), fewer than the minimum of 5 needed to show a rate"
    )


def test_far_frr_reports_which_mode_was_hidden() -> None:
    rows = [_row(mode="self", rhythm=0.5) for _ in range(MIN_GROUP_SIZE)] + [
        _row(mode="attack", rhythm=0.5) for _ in range(MIN_GROUP_SIZE - 1)
    ]
    hidden: list[HiddenGroup] = []
    result = false_reject_and_accept_rates(rows, limit=1.0, hidden=hidden)
    assert [r.kind for r in result] == ["false reject"]
    assert hidden == [HiddenGroup("attack attempts (false accept)", MIN_GROUP_SIZE - 1)]


def test_a_mode_with_no_attempts_is_not_reported_as_hidden() -> None:
    rows = [_row(mode="self", rhythm=0.5) for _ in range(MIN_GROUP_SIZE)]
    hidden: list[HiddenGroup] = []
    false_reject_and_accept_rates(rows, limit=1.0, hidden=hidden)
    assert hidden == []


def test_rates_by_group_names_the_hidden_group() -> None:
    rows = [_row(mode="attack", device_type="keyboard") for _ in range(MIN_GROUP_SIZE)] + [
        _row(mode="attack", device_type="touch") for _ in range(2)
    ]
    hidden: list[HiddenGroup] = []
    result = rates_by_group(rows, 1.0, lambda r: r.device_type, "device_type", hidden)
    assert [r.label for r in result] == ["device_type=keyboard, limit 1.0"]
    assert hidden == [HiddenGroup("device_type=touch, attack attempts (false accept)", 2)]


def test_analyze_prints_each_hidden_group_once_with_the_reason(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # 5 self attempts (shown) and 3 attack attempts (hidden), like a
    # table of real scores too small to give an attack rate.
    rows = [_row(mode="self", rhythm=1.0) for _ in range(5)] + [
        _row(mode="attack", rhythm=1.0) for _ in range(3)
    ]
    analyze(rows)
    out = capsys.readouterr().out

    # Once per table it is hidden from, not once per swept limit.
    sweep_line = hidden_line(HiddenGroup("attack attempts (false accept)", 3))
    assert out.count(sweep_line + "\n") == 1
    assert hidden_line(HiddenGroup("mode=attack", 3)) in out
    assert hidden_line(HiddenGroup("keyboard=not recorded, attack attempts (false accept)", 3)) in (
        out
    )
    # The shown group is still shown, and nothing is hidden for it.
    assert "hidden: self attempts" not in out
    assert "hidden: mode=self" not in out


def test_analyze_prints_the_limit_distribution_and_the_real_pass_rate(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rows = [
        _row(mode="attack", target_id=f"t{i}", rhythm=2.0, limit_value=limit)
        for i, limit in enumerate([1.3, 1.3, 3.5, 3.5, 3.5])
    ]
    analyze(rows)
    out = capsys.readouterr().out
    assert "Limits actually given" in out
    assert "player      | at 3.5 (upper clamp) | 3       | 0.600" in out
    assert "Real pass rate" in out
    # 2.0 is under the three 3.5 limits and over the two 1.3 ones.
    assert "attack | 5 | 3                     | 0.600" in out


def test_analyze_buckets_version_2_limits_against_the_2_0_clamp(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rows = [
        _row(scoring_version="2", target_id=f"t{i}", limit_value=limit)
        for i, limit in enumerate([1.3, 1.6, 2.0, 2.0, 2.0])
    ]
    analyze(rows)
    out = capsys.readouterr().out
    assert "player      | at 2.0 (upper clamp) | 3       | 0.600" in out
    assert "3.5" not in out.split("### Real pass rate")[0]
