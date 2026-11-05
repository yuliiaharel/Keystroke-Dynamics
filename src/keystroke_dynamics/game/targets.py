"""Global, non-party-scoped game targets: the simulated practice bots
(always present) and an optional permanent recorded target (e.g. "Can
you pass as Yuliia?" -- PARTY_LAUNCH_PLAN.md Part 1 section 7).

Neither lives in a Party's own players dict -- Party.players (see
game/store.py) holds only real, party-scoped human players. These are
synthesized or loaded once per level and merged into a party's
rendered view by api/game.py, with stable ids (SAMPLE_TARGET_ID_PREFIX
/ PERMANENT_TARGET_ID_PREFIX) recognized specially wherever a
target_id is resolved for scoring/attack/replay.
"""

from __future__ import annotations

import json
import random
from functools import cache
from pathlib import Path

from keystroke_dynamics.core.events import KeyEvent
from keystroke_dynamics.core.features import FeatureKey
from keystroke_dynamics.core.stats import RunningStats
from keystroke_dynamics.game.enroll import (
    build_profile_and_threshold,
    char_to_code,
    median_notes,
    phrase_from_run,
)
from keystroke_dynamics.game.store import Note, Player

#: Where permanent target files live -- committed to the repo, never
#: raw events (see save_permanent_target). Empty until a recording is
#: made; the game must work fine either way.
TARGETS_DIR = Path(__file__).parent / "targets"

SAMPLE_TARGET_ID_PREFIX = "sample-"
PERMANENT_TARGET_ID_PREFIX = "target-"

#: (slug, label, relative typing speed) -- the same three personalities
#: as the approved mockup's SAMPLES, "clearly labeled" as simulated per
#: the plan. speed scales both hold time and the gap to the next key;
#: >1 is slower.
SAMPLE_BOTS: list[tuple[str, str, float]] = [
    ("quick-fingers", "Sample: Quick Fingers", 0.72),
    ("steady-hands", "Sample: Steady Hands", 1.05),
    ("two-finger-typist", "Sample: Two-Finger Typist", 1.4),
]

#: Training runs per sample bot -- matches the mockup's addSamples().
SAMPLE_TRAINING_RUNS = 6


def _synthetic_run(phrase: str, rng: random.Random, speed: float) -> list[KeyEvent]:
    """One deterministic, speed-scaled typing of `phrase`: the same
    down/hold/gap shape real captured events have. Only the *input* is
    synthetic -- it's still run through the real core.events/
    core.features pipeline (via game.enroll), like any other sample.
    Not a second scoring path.
    """
    events: list[KeyEvent] = []
    t = 0.0
    for i, ch in enumerate(phrase):
        if i > 0:
            t += speed * rng.uniform(70, 240)
        code = char_to_code(ch)
        hold = speed * rng.uniform(45, 105)
        events.append(KeyEvent(code=code, action="down", t_ms=t))
        events.append(KeyEvent(code=code, action="up", t_ms=t + hold))
    return events


def _build_target_player(
    id_: str, name: str, color: int, phrase: str, runs: list[list[KeyEvent]]
) -> Player:
    profile, threshold = build_profile_and_threshold(phrase, runs)
    notes = median_notes(phrase, runs)
    return Player(id=id_, name=name, color=color, profile=profile, threshold=threshold, notes=notes)


@cache
def sample_targets(level: str, phrase: str) -> tuple[Player, ...]:
    """The three simulated practice targets for one level's phrase.
    Deterministic (seeded by level + bot slug) and cheap enough to
    cache forever -- there's no per-party or per-request variation to
    invalidate on."""
    targets = []
    for i, (slug, label, speed) in enumerate(SAMPLE_BOTS):
        rng = random.Random(f"{level}:{slug}")
        runs = [_synthetic_run(phrase, rng, speed) for _ in range(SAMPLE_TRAINING_RUNS)]
        targets.append(
            _build_target_player(f"{SAMPLE_TARGET_ID_PREFIX}{slug}", label, i, phrase, runs)
        )
    return tuple(targets)


def _encode_feature_key(key: FeatureKey) -> str:
    return "|".join(key)


def _decode_feature_key(s: str) -> FeatureKey:
    parts = s.split("|")
    if parts[0] == "hold":
        return ("hold", parts[1])
    return ("flight", parts[1], parts[2])


def save_permanent_target(path: Path, *, name: str, lines: dict[str, list[list[KeyEvent]]]) -> None:
    """Writes a committed permanent-target file: one entry per line
    (word/sentence/long), each holding only a derived profile,
    calibrated threshold, and median notes -- never a raw event or
    timestamp. `lines` maps level -> a list of training runs (each a
    full down/up KeyEvent sequence for that level's phrase), the same
    shape a real player's enrollment produces.

    Callers (the debug-only recording route) are responsible for
    gating this behind settings.debug -- this function itself has no
    opinion on that; it only knows how to turn real training runs into
    the stored shape.
    """
    lines_out: dict[str, object] = {}
    for level, runs in lines.items():
        phrase = phrase_from_run(runs[0])
        player = _build_target_player("ignored", name, 0, phrase, runs)
        lines_out[level] = {
            "threshold": player.threshold,
            "profile": {
                _encode_feature_key(k): {"count": v.count, "mean": v.mean, "m2": v.m2}
                for k, v in player.profile.items()
            },
            "notes": [
                {"ch": n.ch, "start_ms": n.start_ms, "dur_ms": n.dur_ms} for n in player.notes
            ],
        }
    data = {"name": name, "lines": lines_out}
    path.write_text(json.dumps(data, indent=2))


def load_permanent_target(level: str) -> Player | None:
    """Loads the committed permanent-target file's entry for `level`,
    if one exists. None if no file is committed yet, or the file
    doesn't have that level recorded -- in either case the game must
    still work (the plan: "the game must still work without it").
    Never invents data: this only ever returns what was actually
    recorded.
    """
    files = sorted(TARGETS_DIR.glob("*.json"))
    if not files:
        return None
    data = json.loads(files[0].read_text())
    line = data.get("lines", {}).get(level)
    if line is None:
        return None
    name = data["name"]
    profile = {
        _decode_feature_key(k): RunningStats(count=v["count"], mean=v["mean"], m2=v["m2"])
        for k, v in line["profile"].items()
    }
    notes = [Note(ch=n["ch"], start_ms=n["start_ms"], dur_ms=n["dur_ms"]) for n in line["notes"]]
    target_id = f"{PERMANENT_TARGET_ID_PREFIX}{name.lower().replace(' ', '-')}"
    return Player(
        id=target_id,
        name=name,
        color=5,
        profile=profile,
        threshold=line["threshold"],
        notes=notes,
    )
