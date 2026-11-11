"""Read-only analysis of the score_attempts table, saved automatically
(docs/plans/done/PARTY_LAUNCH_PLAN.md section 10). Run with a read-only connection
string -- never the app's own SCORES_DATABASE_URL, which is write-only
by design (scores/db.py, the restricted app database role):

    uv run python -m evaluation.analyze_scores "<read-only connection string>"

IMPORTANT, and printed again at the top of every run: `mode` and every
identity in this table are self-reported by whichever client sent the
request -- nothing here verifies a typist actually is who an attempt
claims, and real play can't be reliably separated from scripted
attempts. These are observed rates on uncontrolled play (and rows
with consent_version "1", from the earlier opt-in checkbox, are
self-selected too), not a controlled benchmark -- NEVER call them this game's (or
this method's) accuracy. See evaluation/README.md for the actual
benchmark that measures the scoring method itself.
"""

from __future__ import annotations

import argparse
import datetime
import statistics
import sys
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from keystroke_dynamics.game.scoring import GAME_MAX_THRESHOLD, GAME_MIN_THRESHOLD
from keystroke_dynamics.scores.models import ScoreAttempt

#: Any group (a limit's FAR/FRR, a device_type slice, a pace bucket,
#: ...) with fewer than this many attempts is hidden from its table
#: entirely, per the plan's own instruction -- never shown with a
#: caveat, never estimated from a smaller n. Its rate stays hidden,
#: but the table is followed by a line naming the group and its size
#: (HiddenGroup), so a missing row is never mistaken for no data.
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
    target_id: str
    #: The limit in effect for this attempt -- the target's own
    #: calibrated limit (game/scoring.py's calibrate_threshold) at the
    #: time it was played.
    limit_value: float
    #: None for rows recorded before rooms existed, and wherever the
    #: question doesn't apply (scores/models.py).
    same_keyboard: bool | None = None


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
        target_id=r.target_id,
        limit_value=r.limit_value,
        same_keyboard=r.same_keyboard,
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


@dataclass(frozen=True)
class HiddenGroup:
    """A group left out of a table for having fewer than
    MIN_GROUP_SIZE attempts. Carries its size, never its rate."""

    group: str
    n: int


def hidden_line(h: HiddenGroup) -> str:
    return (
        f"hidden: {h.group} -- {h.n} attempt(s), fewer than the minimum of "
        f"{MIN_GROUP_SIZE} needed to show a rate"
    )


def false_reject_and_accept_rates(
    rows: list[Row], limit: float, hidden: list[HiddenGroup] | None = None
) -> list[RateRow]:
    """Re-derives, at a hypothetical limit (never the limit actually
    in effect when the row was recorded -- see
    pass_rates_at_own_limit for that), what each self/attack row's
    outcome would have been: rhythm <= limit. disguise/replay rows
    measure a different question (fooling your own detector; a
    recording) and are left out of FAR/FRR.

    hidden: if given, a HiddenGroup is appended for each of the two
    modes that has attempts but fewer than MIN_GROUP_SIZE of them. A
    mode with no attempts at all isn't hidden -- there is nothing to
    hide -- and adds nothing.
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
    elif self_rows and hidden is not None:
        hidden.append(HiddenGroup("self attempts (false reject)", len(self_rows)))
    if len(attack_rows) >= MIN_GROUP_SIZE:
        far = sum(1 for _, v in attack_rows if v <= limit) / len(attack_rows)
        out.append(RateRow(f"limit {limit}", len(attack_rows), far, "false accept"))
    elif attack_rows and hidden is not None:
        hidden.append(HiddenGroup("attack attempts (false accept)", len(attack_rows)))
    return out


def keyboard_label(same_keyboard: bool | None) -> str:
    if same_keyboard is None:
        return "not recorded"
    return "same" if same_keyboard else "different"


def attack_rates_by_keyboard(
    rows: list[Row], limit: float, hidden: list[HiddenGroup] | None = None
) -> list[RateRow]:
    """False acceptance for attacks on real players, split by whether
    the attacker typed on the target's own keyboard or a different
    one -- a different keyboard can change timing on its own, so the
    two shouldn't be read as one rate. Attacks only: a self-mode row
    is same-keyboard by definition."""
    attacks = [r for r in rows if r.mode == "attack" and r.target_kind == "player"]
    return rates_by_group(
        attacks, limit, lambda r: keyboard_label(r.same_keyboard), "keyboard", hidden
    )


def rates_by_group(
    rows: list[Row],
    limit: float,
    group_key: Callable[[Row], str],
    group_label_prefix: str,
    hidden: list[HiddenGroup] | None = None,
) -> list[RateRow]:
    """false_reject_and_accept_rates, sliced by group_key(row) --
    device_type, or pace_bucket(row.pace). hidden: as in
    false_reject_and_accept_rates, with each group's name prefixed."""
    groups: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        groups[group_key(r)].append(r)
    out = []
    for key, group in sorted(groups.items()):
        group_hidden: list[HiddenGroup] = []
        for rate_row in false_reject_and_accept_rates(group, limit, group_hidden):
            label = f"{group_label_prefix}={key}, {rate_row.label}"
            out.append(RateRow(label, rate_row.n, rate_row.rate, rate_row.kind))
        if hidden is not None:
            hidden += [
                HiddenGroup(f"{group_label_prefix}={key}, {h.group}", h.n) for h in group_hidden
            ]
    return out


#: Buckets for the distribution of limits actually given out. The two
#: clamps get their own bucket each: a limit sitting exactly on a
#: clamp was decided by the clamp, not by the player's own typing.
#: The bounds are the current game/scoring.py constants, so a
#: scoring_version with different clamps would need its own buckets.
_CLAMP_TOLERANCE = 1e-9
LIMIT_BUCKET_EDGES = [2.0, 2.5, 3.0]


def limit_bucket(limit_value: float) -> str:
    if limit_value <= GAME_MIN_THRESHOLD + _CLAMP_TOLERANCE:
        return f"at {GAME_MIN_THRESHOLD} (lower clamp)"
    if limit_value >= GAME_MAX_THRESHOLD - _CLAMP_TOLERANCE:
        return f"at {GAME_MAX_THRESHOLD} (upper clamp)"
    lower = GAME_MIN_THRESHOLD
    for edge in LIMIT_BUCKET_EDGES:
        if limit_value < edge:
            return f"{lower} to under {edge}"
        lower = edge
    return f"{lower} to under {GAME_MAX_THRESHOLD}"


def limit_bucket_labels() -> list[str]:
    """Every bucket limit_bucket can return, lowest first."""
    bounds = [GAME_MIN_THRESHOLD, *LIMIT_BUCKET_EDGES, GAME_MAX_THRESHOLD]
    middle = [f"{a} to under {b}" for a, b in zip(bounds, bounds[1:], strict=False)]
    return [
        f"at {GAME_MIN_THRESHOLD} (lower clamp)",
        *middle,
        f"at {GAME_MAX_THRESHOLD} (upper clamp)",
    ]


@dataclass(frozen=True)
class LimitDistribution:
    target_kind: str
    #: Distinct (target_id, limit_value) pairs. The statistics below
    #: count each once, however many attempts were made against it, so
    #: one much-attacked target can't dominate.
    targets: int
    attempts: int
    minimum: float
    median: float
    maximum: float
    #: bucket label (limit_bucket) -> number of targets, every bucket
    #: present even when zero.
    buckets: dict[str, int]


def limit_distributions(
    rows: list[Row], hidden: list[HiddenGroup] | None = None
) -> list[LimitDistribution]:
    """The limits actually in effect (each row's own limit_value),
    one distribution per target_kind: real players' limits come from
    their own enrollment, bots' and the permanent target's from fixed
    data, so they aren't one population. A target_kind with fewer than
    MIN_GROUP_SIZE attempts is hidden (and reported through `hidden`,
    if given)."""
    by_kind: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        by_kind[r.target_kind].append(r)

    out = []
    for kind, group in sorted(by_kind.items()):
        if len(group) < MIN_GROUP_SIZE:
            if hidden is not None:
                hidden.append(HiddenGroup(f"target_kind={kind}", len(group)))
            continue
        limits = [limit for _, limit in sorted({(r.target_id, r.limit_value) for r in group})]
        counts = Counter(limit_bucket(v) for v in limits)
        out.append(
            LimitDistribution(
                target_kind=kind,
                targets=len(limits),
                attempts=len(group),
                minimum=min(limits),
                median=statistics.median(limits),
                maximum=max(limits),
                buckets={label: counts[label] for label in limit_bucket_labels()},
            )
        )
    return out


@dataclass(frozen=True)
class OwnLimitRate:
    mode: str
    #: Scorable attempts only (rhythm is not None).
    n: int
    at_or_under: int
    rate: float


def pass_rates_at_own_limit(
    rows: list[Row], hidden: list[HiddenGroup] | None = None
) -> list[OwnLimitRate]:
    """What actually happened, as opposed to
    false_reject_and_accept_rates' hypothetical limits: per mode, the
    share of scorable attempts whose rhythm was at or under the limit
    in effect for that attempt (its own limit_value). For "attack"
    that share is the observed false acceptance; for "self" it is one
    minus the observed false rejection. "disguise" and "replay" are
    listed too, but ask a different question (see
    false_reject_and_accept_rates). A mode with fewer than
    MIN_GROUP_SIZE scorable attempts is hidden (and reported through
    `hidden`, if given)."""
    by_mode: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for r in rows:
        if r.rhythm is not None:
            by_mode[r.mode].append((r.rhythm, r.limit_value))

    out = []
    for mode, pairs in sorted(by_mode.items()):
        if len(pairs) < MIN_GROUP_SIZE:
            if hidden is not None:
                hidden.append(HiddenGroup(f"mode={mode}", len(pairs)))
            continue
        at_or_under = sum(1 for rhythm, limit in pairs if rhythm <= limit)
        out.append(OwnLimitRate(mode, len(pairs), at_or_under, at_or_under / len(pairs)))
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


def _print_table(
    title: str,
    headers: list[str],
    body: list[list[str]],
    hidden: list[HiddenGroup] | None = None,
) -> None:
    """hidden: groups left out of `body` for being too small, each
    printed once under the table (a limit sweep reports the same
    group once per limit)."""
    print(f"\n### {title}")
    if not body:
        print("(no group has at least 5 attempts)")
    else:
        widths = [max(len(h), *(len(row[i]) for row in body)) for i, h in enumerate(headers)]
        print(" | ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True)))
        print("-+-".join("-" * w for w in widths))
        for row in body:
            print(" | ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)))
    for h in dict.fromkeys(hidden or []):
        print(hidden_line(h))


def analyze(rows: list[Row]) -> None:
    for version in distinct_scoring_versions(rows):
        version_rows = [r for r in rows if r.scoring_version == version]
        header = f"scoring_version {version} -- {len(version_rows)} attempt(s)"
        print(f"\n{'=' * 60}\n{header}\n{'=' * 60}")

        hidden: list[HiddenGroup] = []
        distributions = limit_distributions(version_rows, hidden)
        _print_table(
            "Limits actually given (each attempt's own limit_value, counted once per target)",
            ["target_kind", "targets", "attempts", "min", "median", "max"],
            [
                [
                    d.target_kind,
                    str(d.targets),
                    str(d.attempts),
                    f"{d.minimum:.3f}",
                    f"{d.median:.3f}",
                    f"{d.maximum:.3f}",
                ]
                for d in distributions
            ],
            hidden,
        )
        _print_table(
            "Limits actually given, by range",
            ["target_kind", "limit", "targets", "share"],
            [
                [d.target_kind, label, str(count), f"{count / d.targets:.3f}"]
                for d in distributions
                for label, count in d.buckets.items()
            ],
            hidden,
        )

        hidden = []
        _print_table(
            "Real pass rate: rhythm at or under the attempt's own limit_value "
            "(attack = observed false acceptance; self = 1 - observed false rejection)",
            ["mode", "n", "at or under own limit", "rate"],
            [
                [o.mode, str(o.n), str(o.at_or_under), f"{o.rate:.3f}"]
                for o in pass_rates_at_own_limit(version_rows, hidden)
            ],
            hidden,
        )

        hidden = []
        rate_table: list[list[str]] = []
        for limit in CANDIDATE_LIMITS:
            for rr in false_reject_and_accept_rates(version_rows, limit, hidden):
                rate_table.append([rr.label, rr.kind, str(rr.n), f"{rr.rate:.3f}"])
        _print_table(
            "False rejection / false acceptance across hypothetical limits",
            ["limit", "kind", "n", "rate"],
            rate_table,
            hidden,
        )

        hidden = []
        device_table: list[list[str]] = []
        for limit in CANDIDATE_LIMITS:
            for rr in rates_by_group(
                version_rows, limit, lambda r: r.device_type, "device_type", hidden
            ):
                device_table.append([rr.label, rr.kind, str(rr.n), f"{rr.rate:.3f}"])
        _print_table(
            "False rejection / false acceptance by device_type",
            ["group, limit", "kind", "n", "rate"],
            device_table,
            hidden,
        )

        hidden = []
        pace_table: list[list[str]] = []
        for limit in CANDIDATE_LIMITS:
            for rr in rates_by_group(
                version_rows, limit, lambda r: pace_bucket(r.pace), "pace", hidden
            ):
                pace_table.append([rr.label, rr.kind, str(rr.n), f"{rr.rate:.3f}"])
        _print_table(
            "False rejection / false acceptance by pace bucket "
            "(in-band is docs/plans/done/PARTY_LAUNCH_PLAN.md's 0.85x-1.15x)",
            ["group, limit", "kind", "n", "rate"],
            pace_table,
            hidden,
        )

        hidden = []
        keyboard_table: list[list[str]] = []
        for limit in CANDIDATE_LIMITS:
            for rr in attack_rates_by_keyboard(version_rows, limit, hidden):
                keyboard_table.append([rr.label, rr.kind, str(rr.n), f"{rr.rate:.3f}"])
        _print_table(
            "False acceptance of attacks on players, same keyboard vs different",
            ["group, limit", "kind", "n", "rate"],
            keyboard_table,
            hidden,
        )

        rvp = rhythm_vs_place(version_rows)
        rvp_table = [
            [dim, str(s["n"]), f"{s['mean']:.3f}", f"{s['median']:.3f}"]
            for dim, s in rvp.items()
            if s is not None
        ]
        rvp_counts = {
            "rhythm": sum(1 for r in version_rows if r.rhythm is not None),
            "place": sum(1 for r in version_rows if r.place is not None),
        }
        _print_table(
            "Rhythm compared with Place",
            ["dimension", "n", "mean", "median"],
            rvp_table,
            [
                HiddenGroup(f"dimension={dim}", rvp_counts[dim])
                for dim, s in rvp.items()
                if s is None and rvp_counts[dim] > 0
            ],
        )

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
