"""Sample bot targets and the optional permanent-target file: that
sample bots are deterministic, labeled, and actually scorable; that a
permanent target round-trips through the committed JSON shape with no
raw events in it; and that the game works with no permanent target at
all -- "Before a recording exists, the game must still work without
it" (docs/plans/done/PARTY_LAUNCH_PLAN.md Part 1 section 7)."""

from __future__ import annotations

import json
import random

from keystroke_dynamics.core.events import KeyEvent, pair_presses
from keystroke_dynamics.core.features import extract_features
from keystroke_dynamics.game.enroll import char_to_code
from keystroke_dynamics.game.scoring import GAME_MAX_THRESHOLD, GAME_MIN_THRESHOLD, score_sample
from keystroke_dynamics.game.targets import (
    PERMANENT_TARGET_ID_PREFIX,
    SAMPLE_TARGET_ID_PREFIX,
    _synthetic_run,
    load_permanent_target,
    sample_targets,
    save_permanent_target,
)

PHRASE = "quiet rhythm hides in every small habit of your hands"
LONG_PHRASE = (
    "every keyboard keeps a quiet record of the hands that use it "
    "and those records are surprisingly hard to fake"
)


def test_sample_targets_returns_the_three_labeled_bots() -> None:
    targets = sample_targets("sentence", PHRASE)
    assert len(targets) == 3
    assert all(t.name.startswith("Sample: ") for t in targets)  # clearly labeled as simulated
    assert all(t.id.startswith(SAMPLE_TARGET_ID_PREFIX) for t in targets)
    assert len({t.id for t in targets}) == 3  # distinct ids


def test_sample_targets_have_a_distinct_stable_score_id() -> None:
    # Never derived from the game-facing id (docs/plans/done/PARTY_LAUNCH_PLAN.md
    # section 10), and stable across calls -- sample_targets() is
    # cached, so these are the same objects every time, not a fresh
    # random id per call.
    first = sample_targets("sentence", PHRASE)
    second = sample_targets("sentence", PHRASE)
    assert len({t.score_id for t in first}) == 3
    assert all(t.score_id != t.id for t in first)
    assert [t.score_id for t in first] == [t.score_id for t in second]


def test_sample_targets_have_their_training_line_count() -> None:
    for target in sample_targets("sentence", PHRASE):
        assert target.training_line_count == 6  # SAMPLE_TRAINING_RUNS


def test_sample_targets_is_deterministic() -> None:
    first = sample_targets("long", LONG_PHRASE)
    second = sample_targets("long", LONG_PHRASE)
    assert first == second  # same objects (cached) or at least equal data


def test_sample_targets_differ_per_level() -> None:
    long_targets = sample_targets("long", LONG_PHRASE)
    sentence_targets = sample_targets("sentence", PHRASE)
    assert long_targets[0].profile != sentence_targets[0].profile


def test_sample_targets_calibrated_threshold_is_within_the_clamp() -> None:
    for target in sample_targets("sentence", PHRASE):
        assert GAME_MIN_THRESHOLD <= target.threshold <= GAME_MAX_THRESHOLD


def test_a_sample_bot_can_be_attacked_and_scored() -> None:
    # A fresh attempt typed in that same bot's own style must actually
    # be scorable against it -- not INSUFFICIENT_DATA.
    target = sample_targets("long", LONG_PHRASE)[0]
    rng = random.Random("long:quick-fingers:probe")
    run = _synthetic_run(LONG_PHRASE, rng, speed=0.72)
    sample = extract_features(pair_presses(run))
    result = score_sample(sample, target.profile, phrase=LONG_PHRASE, threshold=target.threshold)
    assert result.score is not None


# ---------- permanent target ----------

#: Not a game level's real phrase -- these tests need one with no
#: repeated letters, so each (hold/flight) feature key appears
#: exactly once per run and RunningStats.count folds to exactly the
#: number of runs, not some higher multiple.
DISTINCT_PHRASE = "bridge"


def _record_a_run(phrase: str, hold_ms: float, gap_ms: float) -> list[KeyEvent]:
    events: list[KeyEvent] = []
    t = 0.0
    for i, ch in enumerate(phrase):
        if i > 0:
            t += gap_ms
        code = char_to_code(ch)
        events.append(KeyEvent(code=code, action="down", t_ms=t))
        events.append(KeyEvent(code=code, action="up", t_ms=t + hold_ms))
    return events


def test_load_permanent_target_returns_none_with_no_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("keystroke_dynamics.game.targets.TARGETS_DIR", tmp_path)
    assert load_permanent_target("sentence") is None


def test_save_and_load_permanent_target_round_trips(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("keystroke_dynamics.game.targets.TARGETS_DIR", tmp_path)
    runs = [_record_a_run(DISTINCT_PHRASE, hold_ms=80.0 + i, gap_ms=150.0 + i) for i in range(5)]
    save_permanent_target(tmp_path / "yuliia.json", name="Yuliia", lines={"sentence": runs})

    target = load_permanent_target("sentence")
    assert target is not None
    assert target.name == "Yuliia"
    assert target.id == f"{PERMANENT_TARGET_ID_PREFIX}yuliia"
    assert GAME_MIN_THRESHOLD <= target.threshold <= GAME_MAX_THRESHOLD
    assert len(target.notes) == len(DISTINCT_PHRASE)
    assert target.training_line_count == 5

    # load_permanent_target() rebuilds a fresh Player from the file on
    # every call, unlike sample_targets()'s caching -- score_id must
    # still come back the same both times, or score_attempts rows
    # would scatter this one target across different target_ids.
    again = load_permanent_target("sentence")
    assert again is not None
    assert again.score_id == target.score_id
    assert target.score_id != target.id


def test_permanent_target_file_holds_no_raw_events(tmp_path) -> None:
    # 5 training runs go in; the stored shape must hold only each
    # feature's aggregated stats (one RunningStats per key, not 5
    # per-run values) and one median note per key position -- never
    # a per-run list that would let the 5 individual runs be
    # reconstructed.
    runs = [_record_a_run(DISTINCT_PHRASE, hold_ms=80.0 + i, gap_ms=150.0 + i) for i in range(5)]
    path = tmp_path / "yuliia.json"
    save_permanent_target(path, name="Yuliia", lines={"sentence": runs})

    raw = json.loads(path.read_text())
    assert set(raw.keys()) == {"name", "lines"}
    line = raw["lines"]["sentence"]
    # training_line_count is just an int (score_attempts.training_lines,
    # docs/plans/done/PARTY_LAUNCH_PLAN.md section 10) -- not a raw event either.
    assert set(line.keys()) == {"threshold", "profile", "notes", "training_line_count"}
    assert line["training_line_count"] == 5
    for stats in line["profile"].values():
        assert set(stats.keys()) == {"count", "mean", "m2"}
        assert stats["count"] == 5  # folded, not a list of 5 raw values
    for note in line["notes"]:
        assert set(note.keys()) == {"ch", "start_ms", "dur_ms"}  # one value, not 5


def test_load_permanent_target_returns_none_for_an_unrecorded_level(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("keystroke_dynamics.game.targets.TARGETS_DIR", tmp_path)
    runs = [_record_a_run(PHRASE, hold_ms=80.0 + i, gap_ms=150.0 + i) for i in range(5)]
    save_permanent_target(tmp_path / "yuliia.json", name="Yuliia", lines={"sentence": runs})

    assert load_permanent_target("long") is None


def test_the_game_still_works_with_no_permanent_target(tmp_path, monkeypatch) -> None:
    # The actual requirement behind all of the above: a party on any
    # level, with zero permanent targets committed, must still have a
    # fully playable set of sample targets to attack.
    monkeypatch.setattr("keystroke_dynamics.game.targets.TARGETS_DIR", tmp_path)
    assert load_permanent_target("sentence") is None
    assert len(sample_targets("sentence", PHRASE)) == 3
