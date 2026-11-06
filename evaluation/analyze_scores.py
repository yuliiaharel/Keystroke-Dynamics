"""Read-only analysis of the opt-in score_attempts table
(PARTY_LAUNCH_PLAN.md section 10). Run with a read-only connection
string -- never the app's own SCORES_DATABASE_URL, which is write-only
by design (scores/db.py, the restricted app database role):

    uv run python -m evaluation.analyze_scores "<read-only connection string>"

IMPORTANT, and printed again at the top of every run: `mode` and every
identity in this table are self-reported by whichever client sent the
request -- nothing here verifies a typist actually is who an attempt
claims, and real play can't be reliably separated from scripted
attempts. These are observed rates on a self-selected, opted-in
sample, not a controlled benchmark -- NEVER call them this game's (or
this method's) accuracy. See evaluation/README.md for the actual
benchmark that measures the scoring method itself.
"""

from __future__ import annotations

import argparse
import datetime
import sys
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from keystroke_dynamics.scores.models import ScoreAttempt

#: Any group (a limit's FAR/FRR, a device_type slice, a pace bucket,
#: ...) with fewer than this many attempts is hidden from its table
#: entirely, per the plan's own instruction -- never shown with a
#: caveat, never estimated from a smaller n.
MIN_GROUP_SIZE = 5

#: Candidate limits swept for the false-reject/false-accept table --
#: game/scoring.py's own calibration range, not an arbitrary one.
CANDIDATE_LIMITS = [round(1.3 + 0.1 * i, 2) for i in range(23)]  # 1.3 .. 3.5

#: Same band game/judge.py's disguise gate and clue use -- "attacks
#: within 0.85x to 1.15x" is this exact range, not a separately chosen
#: one.
IN_PACE_BAND = (0.85, 1.15)

#: More than this many attempts from one typist_id or party_id on one
#: calendar day (created_on has no time of day -- see
#: scores/models.py) is flagged as a possible scripted burst. Provisional,
#: and reported as a flag to look into, never as a verdict -- a human
#: reviewing this output decides what a burst actually means.
BURST_THRESHOLD_PER_DAY = 50


@dataclass(frozen=True)
class Row:
    """The handful of columns this script actually uses, not the full
    ORM row -- keeps the computation functions below testable with
    plain data, no database required."""

    scoring_version: str
    device_type: str
    mode: str
    target_kind: str
    party_id: str
    typist_id: str
    created_on: datetime.date
    rhythm: float | None
    place: float | None
    pace: float | None
    outcome: str


def _row_from_orm(r: ScoreAttempt) -> Row:
    return Row(
        scoring_version=r.scoring_version,
        device_type=r.device_type,
        mode=r.mode,
        target_kind=r.target_kind,
        party_id=r.party_id,
        typist_id=r.typist_id,
        created_on=r.created_on,
        rhythm=r.rhythm,
        place=r.place,
        pace=r.pace,
        outcome=r.outcome,
    )


def fetch_rows(connection_string: str) -> list[Row]:
    """The only function in this script that touches a database --
    everything else takes plain Row objects, so a read-only connection
    string is the only credential this script ever needs."""
    engine = create_engine(connection_string)
    with Session(engine) as session:
        return [_row_from_orm(r) for r in session.execute(select(ScoreAttempt)).scalars()]


def distinct_scoring_versions(rows: list[Row]) -> list[str]:
    return sorted({r.scoring_version for r in rows})


def pace_bucket(pace: float | None) -> str:
    if pace is None:
        return "unknown"
    if pace < IN_PACE_BAND[0]:
        return "fast"
    if pace > IN_PACE_BAND[1]:
        return "slow"
    return "in-band"


@dataclass(frozen=True)
class RateRow:
    label: str
    n: int
    rate: float
    #: What `rate` means for this row -- "false reject" (self-mode,
    #: fraction that would have been rejected) or "false accept"
    #: (attack-mode, fraction that would have passed).
    kind: str


def false_reject_and_accept_rates(rows: list[Row], limit: float) -> list[RateRow]:
    """Re-derives, at a hypothetical limit (never the limit actually
    in effect when the row was recorded -- limit_value isn't even
    fetched here), what each self/attack row's outcome would have
    been: rhythm <= limit. disguise/replay rows measure a different
    question (fooling your own detector; a recording) and are left to
    their own tables instead of folded into FAR/FRR.
    """
    # rhythm_values pairs each usable row with its rhythm already
    # narrowed to float (not float | None) -- mypy can't carry that
    # narrowing through a plain `r.rhythm is not None` filter alone
    # once self_rows/attack_rows are built from a second comprehension.
    rhythm_values = [(r, r.rhythm) for r in rows if r.rhythm is not None]
    self_rows = [(r, v) for r, v in rhythm_values if r.mode == "self"]
    attack_rows = [(r, v) for r, v in rhythm_values if r.mode == "attack"]

    out = []
    if len(self_rows) >= MIN_GROUP_SIZE:
        frr = sum(1 for _, v in self_rows if v > limit) / len(self_rows)
        out.append(RateRow(f"limit {limit}", len(self_rows), frr, "false reject"))
    if len(attack_rows) >= MIN_GROUP_SIZE:
        far = sum(1 for _, v in attack_rows if v <= limit) / len(attack_rows)
        out.append(RateRow(f"limit {limit}", len(attack_rows), far, "false accept"))
    return out


def rates_by_group(
    rows: list[Row], limit: float, group_key: Callable[[Row], str], group_label_prefix: str
) -> list[RateRow]:
    """false_reject_and_accept_rates, sliced by group_key(row) --
    device_type, or pace_bucket(row.pace)."""
    groups: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        groups[group_key(r)].append(r)
    out = []
    for key, group in sorted(groups.items()):
        for rate_row in false_reject_and_accept_rates(group, limit):
            label = f"{group_label_prefix}={key}, {rate_row.label}"
            out.append(RateRow(label, rate_row.n, rate_row.rate, rate_row.kind))
    return out


def rhythm_vs_place(rows: list[Row]) -> dict[str, dict[str, float] | None]:
    """Basic descriptive stats for each, independently -- not a
    correlation (there's no row today with both a meaningful rhythm
    and a meaningful place to correlate; place stays null until the
    touch version exists -- see game/judge.py's _clue() docstring).
    None for a dimension with fewer than MIN_GROUP_SIZE values."""

    def stats(values: list[float]) -> dict[str, float] | None:
        if len(values) < MIN_GROUP_SIZE:
            return None
        sorted_values = sorted(values)
        n = len(sorted_values)
        return {
            "n": n,
            "mean": sum(sorted_values) / n,
            "median": sorted_values[n // 2],
        }

    rhythms = [r.rhythm for r in rows if r.rhythm is not None]
    places = [r.place for r in rows if r.place is not None]
    return {"rhythm": stats(rhythms), "place": stats(places)}


@dataclass(frozen=True)
class BurstFlag:
    id_kind: str  # "typist_id" or "party_id"
    id_value: str
    day: datetime.date
    count: int


def flag_suspicious_bursts(rows: list[Row]) -> list[BurstFlag]:
    """More than BURST_THRESHOLD_PER_DAY attempts from one typist_id
    or party_id on one calendar day. created_on has no time of day,
    so this is the finest resolution available -- a flag to look into
    by hand, never a verdict (mode and identity are self-reported;
    see the module docstring)."""
    by_typist: Counter[tuple[str, datetime.date]] = Counter()
    by_party: Counter[tuple[str, datetime.date]] = Counter()
    for r in rows:
        by_typist[(r.typist_id, r.created_on)] += 1
        by_party[(r.party_id, r.created_on)] += 1

    flags = [
        BurstFlag("typist_id", typist_id, day, count)
        for (typist_id, day), count in by_typist.items()
        if count > BURST_THRESHOLD_PER_DAY
    ]
    flags += [
        BurstFlag("party_id", party_id, day, count)
        for (party_id, day), count in by_party.items()
        if count > BURST_THRESHOLD_PER_DAY
    ]
    return flags


def attempts_per_player_and_party(rows: list[Row]) -> dict[str, int]:
    return {
        "distinct typists": len({r.typist_id for r in rows}),
        "distinct parties": len({r.party_id for r in rows}),
        "total attempts": len(rows),
    }


def _print_table(title: str, headers: list[str], body: list[list[str]]) -> None:
    print(f"\n### {title}")
    if not body:
        print("(no group has at least 5 attempts)")
        return
    widths = [max(len(h), *(len(row[i]) for row in body)) for i, h in enumerate(headers)]
    print(" | ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True)))
    print("-+-".join("-" * w for w in widths))
    for row in body:
        print(" | ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)))


def analyze(rows: list[Row]) -> None:
    for version in distinct_scoring_versions(rows):
        version_rows = [r for r in rows if r.scoring_version == version]
        header = f"scoring_version {version} -- {len(version_rows)} attempt(s)"
        print(f"\n{'=' * 60}\n{header}\n{'=' * 60}")

        rate_table: list[list[str]] = []
        for limit in CANDIDATE_LIMITS:
            for rr in false_reject_and_accept_rates(version_rows, limit):
                rate_table.append([rr.label, rr.kind, str(rr.n), f"{rr.rate:.3f}"])
        _print_table(
            "False rejection / false acceptance across limits",
            ["limit", "kind", "n", "rate"],
            rate_table,
        )

        device_table: list[list[str]] = []
        for limit in CANDIDATE_LIMITS:
            for rr in rates_by_group(version_rows, limit, lambda r: r.device_type, "device_type"):
                device_table.append([rr.label, rr.kind, str(rr.n), f"{rr.rate:.3f}"])
        _print_table(
            "False rejection / false acceptance by device_type",
            ["group, limit", "kind", "n", "rate"],
            device_table,
        )

        pace_table: list[list[str]] = []
        for limit in CANDIDATE_LIMITS:
            for rr in rates_by_group(version_rows, limit, lambda r: pace_bucket(r.pace), "pace"):
                pace_table.append([rr.label, rr.kind, str(rr.n), f"{rr.rate:.3f}"])
        _print_table(
            "False rejection / false acceptance by pace bucket "
            "(in-band is PARTY_LAUNCH_PLAN.md's 0.85x-1.15x)",
            ["group, limit", "kind", "n", "rate"],
            pace_table,
        )

        rvp = rhythm_vs_place(version_rows)
        rvp_table = [
            [dim, str(s["n"]), f"{s['mean']:.3f}", f"{s['median']:.3f}"]
            for dim, s in rvp.items()
            if s is not None
        ]
        _print_table("Rhythm compared with Place", ["dimension", "n", "mean", "median"], rvp_table)

        counts = attempts_per_player_and_party(version_rows)
        _print_table(
            "Attempts per player and per party",
            ["measure", "value"],
            [[k, str(v)] for k, v in counts.items()],
        )

        flags = flag_suspicious_bursts(version_rows)
        _print_table(
            f"Suspicious bursts (>{BURST_THRESHOLD_PER_DAY} attempts, one id, one day)",
            ["id_kind", "id_value", "day", "count"],
            [[f.id_kind, f.id_value, str(f.day), str(f.count)] for f in flags],
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "connection_string",
        help="Read-only connection string for the scores database -- never the app's "
        "own SCORES_DATABASE_URL.",
    )
    args = parser.parse_args(argv)

    print(__doc__)
    rows = fetch_rows(args.connection_string)
    if not rows:
        print("No rows at all yet.")
        return
    analyze(rows)


if __name__ == "__main__":
    main(sys.argv[1:])
