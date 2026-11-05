"""Sample bot targets and the optional permanent-target file: that
sample bots are deterministic, labeled, and actually scorable; that a
permanent target round-trips through the committed JSON shape with no
raw events in it; and that the game works with no permanent target at
all -- "Before a recording exists, the game must still work without
it" (PARTY_LAUNCH_PLAN.md Part 1 section 7)."""

from __future__ import annotations

import json
import random

from keystroke_dynamics.core.events import KeyEvent, pair_presses
from keystroke_dynamics.core.features import extract_features
from keystroke_dynamics.game.scoring import GAME_MAX_THRESHOLD, GAME_MIN_THRESHOLD, score_sample
from keystroke_dynamics.game.targets import (
    PERMANENT_TARGET_ID_PREFIX,
    SAMPLE_TARGET_ID_PREFIX,
    _char_to_code,
    _synthetic_run,
    load_permanent_target,
    sample_targets,
    save_permanent_target,
)

PHRASE = "quiet rhythm hides in every small habit of your hands"


def test_sample_targets_returns_the_three_labeled_bots() -> None:
    targets = sample_targets("sentence", PHRASE)
    assert len(targets) == 3
    assert all(t.name.startswith("Sample: ") for t in targets)  # clearly labeled as simulated
    assert all(t.id.startswith(SAMPLE_TARGET_ID_PREFIX) for t in targets)
    assert len({t.id for t in targets}) == 3  # distinct ids


def test_sample_targets_is_deterministic() -> None:
    first = sample_targets("word", "nukiae")
    second = sample_targets("word", "nukiae")
    assert first == second  # same objects (cached) or at least equal data


def test_sample_targets_differ_per_level() -> None:
    word_targets = sample_targets("word", "nukiae")
    sentence_targets = sample_targets("sentence", PHRASE)
    assert word_targets[0].profile != sentence_targets[0].profile


def test_sample_targets_calibrated_threshold_is_within_the_clamp() -> None:
    for target in sample_targets("sentence", PHRASE):
        assert GAME_MIN_THRESHOLD <= target.threshold <= GAME_MAX_THRESHOLD


def test_a_sample_bot_can_be_attacked_and_scored() -> None:
    # A fresh attempt typed in that same bot's own style must actually
    # be scorable against it -- not INSUFFICIENT_DATA.
    target = sample_targets("word", "nukiae")[0]
    rng = random.Random("word:quick-fingers:probe")
    run = _synthetic_run("nukiae", rng, speed=0.72)
    sample = extract_features(pair_presses(run))
    result = score_sample(sample, target.profile, phrase="nukiae", threshold=target.threshold)
    assert result.score is not None


def test_char_to_code_round_trips_through_space() -> None:
    assert _char_to_code(" ") == "Space"
    assert _char_to_code("a") == "KeyA"


# ---------- permanent target ----------


def _record_a_run(phrase: str, hold_ms: float, gap_ms: float) -> list[KeyEvent]:
    events: list[KeyEvent] = []
    t = 0.0
    for i, ch in enumerate(phrase):
        if i > 0:
            t += gap_ms
        code = _char_to_code(ch)
        events.append(KeyEvent(code=code, action="down", t_ms=t))
        events.append(KeyEvent(code=code, action="up", t_ms=t + hold_ms))
    return events


def test_load_permanent_target_returns_none_with_no_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("keystroke_dynamics.game.targets.TARGETS_DIR", tmp_path)
    assert load_permanent_target("word") is None


def test_save_and_load_permanent_target_round_trips(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("keystroke_dynamics.game.targets.TARGETS_DIR", tmp_path)
    runs = [_record_a_run("nukiae", hold_ms=80.0 + i, gap_ms=150.0 + i) for i in range(5)]
    save_permanent_target(tmp_path / "yuliia.json", name="Yuliia", lines={"word": runs})

    target = load_permanent_target("word")
    assert target is not None
    assert target.name == "Yuliia"
    assert target.id == f"{PERMANENT_TARGET_ID_PREFIX}yuliia"
    assert GAME_MIN_THRESHOLD <= target.threshold <= GAME_MAX_THRESHOLD
    assert len(target.notes) == len("nukiae")


def test_permanent_target_file_holds_no_raw_events(tmp_path) -> None:
    # 5 training runs go in; the stored shape must hold only each
    # feature's aggregated stats (one RunningStats per key, not 5
    # per-run values) and one median note per key position -- never
    # a per-run list that would let the 5 individual runs be
    # reconstructed.
    runs = [_record_a_run("nukiae", hold_ms=80.0 + i, gap_ms=150.0 + i) for i in range(5)]
    path = tmp_path / "yuliia.json"
    save_permanent_target(path, name="Yuliia", lines={"word": runs})

    raw = json.loads(path.read_text())
    assert set(raw.keys()) == {"name", "lines"}
    line = raw["lines"]["word"]
    assert set(line.keys()) == {"threshold", "profile", "notes"}
    for stats in line["profile"].values():
        assert set(stats.keys()) == {"count", "mean", "m2"}
        assert stats["count"] == 5  # folded, not a list of 5 raw values
    for note in line["notes"]:
        assert set(note.keys()) == {"ch", "start_ms", "dur_ms"}  # one value, not 5


def test_load_permanent_target_returns_none_for_an_unrecorded_level(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("keystroke_dynamics.game.targets.TARGETS_DIR", tmp_path)
    runs = [_record_a_run("nukiae", hold_ms=80.0 + i, gap_ms=150.0 + i) for i in range(5)]
    save_permanent_target(tmp_path / "yuliia.json", name="Yuliia", lines={"word": runs})

    assert load_permanent_target("sentence") is None


def test_the_game_still_works_with_no_permanent_target(tmp_path, monkeypatch) -> None:
    # The actual requirement behind all of the above: a party on any
    # level, with zero permanent targets committed, must still have a
    # fully playable set of sample targets to attack.
    monkeypatch.setattr("keystroke_dynamics.game.targets.TARGETS_DIR", tmp_path)
    assert load_permanent_target("word") is None
    assert len(sample_targets("word", "nukiae")) == 3
