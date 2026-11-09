"""evaluation/analyze_scores.py's one database-touching function,
fetch_rows(), against the real scores test database -- and
end_to_end() on known seeded data, matching docs/plans/done/PARTY_LAUNCH_PLAN.md
section 10's own 'Done when' bullet: "evaluation/analyze_scores.py
produces correct results on known test data."
"""

from __future__ import annotations

from evaluation.analyze_scores import (
    analyze,
    false_reject_and_accept_rates,
    fetch_rows,
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
