"""evaluation/analyze_scores.py's one database-touching function,
fetch_rows(), against the real scores test database -- and
end_to_end() on known seeded data, matching docs/plans/done/PARTY_LAUNCH_PLAN.md
section 10's own 'Done when' bullet: "evaluation/analyze_scores.py
produces correct results on known test data."
"""

from __future__ import annotations

from evaluation.analyze_scores import (
    analyze,
    attack_rates_by_keyboard,
    false_reject_and_accept_rates,
    fetch_rows,
    rhythm_and_place_by_group,
)
from keystroke_dynamics.scores.writer import _write_batch
from tests.scores.conftest import SCORES_TEST_DATABASE_URL
from tests.scores.test_db_role import _values


def test_fetch_rows_round_trips_real_rows(scores_db_session) -> None:
    rows = [_values(scoring_version="fetch-test") for _ in range(3)]
    _write_batch(rows, [])

    fetched = [r for r in fetch_rows(SCORES_TEST_DATABASE_URL) if r.scoring_version == "fetch-test"]
    assert len(fetched) == 3
    assert {r.outcome for r in fetched} == {"pass"}


def test_analyze_produces_correct_rates_on_known_seeded_data(scores_db_session, capsys) -> None:
    # 5 self-mode rows, 2 of them above the limit -> FRR 2/5 at that
    # exact limit. 5 attack-mode rows, 3 at or under -> FAR 3/5.
    # scoring_version is unique to this test so other tests' rows
    # (and other test runs against the same shared database) can
    # never pollute this count.
    version = "analyze-known-data"
    rows = [
        _values(scoring_version=version, mode="self", rhythm=r, outcome="pass")
        for r in [0.5, 0.9, 1.0, 1.1, 1.5]
    ] + [
        _values(scoring_version=version, mode="attack", rhythm=r, outcome="pass")
        for r in [0.5, 0.9, 1.0, 1.1, 1.5]
    ]
    _write_batch(rows, [])

    fetched = [r for r in fetch_rows(SCORES_TEST_DATABASE_URL) if r.scoring_version == version]
    assert len(fetched) == 10

    result = false_reject_and_accept_rates(fetched, limit=1.0)
    frr = next(r for r in result if r.kind == "false reject")
    far = next(r for r in result if r.kind == "false accept")
    assert frr.n == 5
    assert frr.rate == 2 / 5
    assert far.n == 5
    assert far.rate == 3 / 5

    # analyze() itself must run end to end on this data and print
    # something -- not raise, and not silently produce nothing.
    analyze(fetched)
    output = capsys.readouterr().out
    assert version in output
    assert "false reject" in output
    assert "false accept" in output


def test_fetch_rows_carries_same_keyboard_into_the_keyboard_split(scores_db_session) -> None:
    version = "analyze-same-keyboard"
    rows = [
        _values(scoring_version=version, mode="attack", rhythm=0.5, same_keyboard=True)
        for _ in range(5)
    ] + [
        _values(scoring_version=version, mode="attack", rhythm=2.0, same_keyboard=False)
        for _ in range(5)
    ]
    _write_batch(rows, [])

    fetched = [r for r in fetch_rows(SCORES_TEST_DATABASE_URL) if r.scoring_version == version]
    assert sorted(r.same_keyboard for r in fetched) == [False] * 5 + [True] * 5

    rates = {r.label: r.rate for r in attack_rates_by_keyboard(fetched, limit=1.0)}
    assert rates == {"keyboard=same, limit 1.0": 1.0, "keyboard=different, limit 1.0": 0.0}


def test_fetch_rows_carries_touch_scores_into_the_rhythm_and_place_split(scores_db_session) -> None:
    version = "analyze-touch"
    touch = {"device_type": "touch", "line_id": "touch", "mode": "attack"}
    rows = [
        _values(
            scoring_version=version, **touch, rhythm=1.0, place=0.5, total=0.8, same_keyboard=True
        )
        for _ in range(5)
    ] + [
        _values(
            scoring_version=version, **touch, rhythm=2.0, place=3.0, total=2.3, same_keyboard=False
        )
        for _ in range(5)
    ]
    _write_batch(rows, [])

    fetched = [r for r in fetch_rows(SCORES_TEST_DATABASE_URL) if r.scoring_version == version]
    assert len(fetched) == 10
    assert {r.total for r in fetched} == {0.8, 2.3}

    means = {(s.keyboard, s.dimension): s.mean for s in rhythm_and_place_by_group(fetched)}
    assert means == {
        ("same", "rhythm"): 1.0,
        ("same", "place"): 0.5,
        ("different", "rhythm"): 2.0,
        ("different", "place"): 3.0,
    }
    # Judged on total: 0.8 passes a limit of 1.3, 2.3 doesn't.
    (far,) = false_reject_and_accept_rates(fetched, limit=1.3)
    assert far.rate == 0.5
