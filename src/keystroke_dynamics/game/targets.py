"""Global, non-party-scoped game targets: the simulated practice bots
(always present) and an optional permanent recorded target (e.g. "Can
you pass as Yuliia?" -- docs/plans/done/PARTY_LAUNCH_PLAN.md Part 1 section 7).

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
    build_touch_profiles_and_threshold,
    char_to_code,
    median_notes,
    phrase_from_run,
)
from keystroke_dynamics.game.levels import TOUCH_LEVEL
from keystroke_dynamics.game.place import PlaceKey
from keystroke_dynamics.game.store import Note, Player
from keystroke_dynamics.game.taps import TapEvent, to_key_events
from keystroke_dynamics.scores.target_ids import score_id_for_target

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

#: (slug, label, relative speed, usual sideways offset, usual vertical
#: offset) -- design/typing-twin-touch.html's two simulated tappers,
#: clearly labeled as samples. The offsets are in key widths and
#: heights: where on a key this tapper's thumbs tend to land.
TOUCH_SAMPLE_BOTS: list[tuple[str, str, float, float, float]] = [
    ("speedy-thumbs", "Sample: Speedy Thumbs", 0.75, -0.12, 0.16),
    ("one-finger-pecker", "Sample: One-Finger Pecker", 1.45, 0.1, -0.1),
]


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
    return Player(
        id=id_,
        name=name,
        color=color,
        profile=profile,
        threshold=threshold,
        notes=notes,
        training_line_count=len(runs),
    )


def _synthetic_tap_run(
    phrase: str, slug: str, noise: random.Random, speed: float, bias_x: float, bias_y: float
) -> list[TapEvent]:
    """One simulated tapping of `phrase`, shaped like the mockup's
    sampleRuns(): each key and key pair has this tapper's own usual
    timing and landing spot (fixed by `slug`), and each run wobbles a
    little around it (`noise`). Synthetic input only -- it goes
    through the real touch pipeline like any other line."""

    def habit(what: str) -> float:
        return random.Random(f"{slug}|{what}").random()

    taps: list[TapEvent] = []
    t = 0.0
    for i, ch in enumerate(phrase):
        if i > 0:
            pair = phrase[i - 1] + ch
            t += speed * (120 + 260 * habit(f"gap:{pair}")) * noise.uniform(0.9, 1.1)
        hold = (50 + 50 * habit(f"hold:{ch}")) * noise.uniform(0.9, 1.1)
        code = char_to_code(ch)
        dx = bias_x + (habit(f"x:{ch}") - 0.5) * 0.35 + noise.uniform(-0.06, 0.06)
        dy = bias_y + (habit(f"y:{ch}") - 0.5) * 0.35 + noise.uniform(-0.06, 0.06)
        taps.append(TapEvent(code=code, action="down", t_ms=t, dx=dx, dy=dy))
        taps.append(TapEvent(code=code, action="up", t_ms=t + hold))
    return taps


def _build_touch_target_player(
    id_: str, name: str, color: int, phrase: str, runs: list[list[TapEvent]]
) -> Player:
    profile, place_profile, threshold = build_touch_profiles_and_threshold(phrase, runs)
    return Player(
        id=id_,
        name=name,
        color=color,
        profile=profile,
        place_profile=place_profile,
        threshold=threshold,
        notes=median_notes(phrase, [to_key_events(run) for run in runs]),
        training_line_count=len(runs),
    )


def _touch_sample_targets(phrase: str) -> tuple[Player, ...]:
    targets = []
    for i, (slug, label, speed, bias_x, bias_y) in enumerate(TOUCH_SAMPLE_BOTS):
        noise = random.Random(f"{TOUCH_LEVEL}:{slug}")
        runs = [
            _synthetic_tap_run(phrase, slug, noise, speed, bias_x, bias_y)
            for _ in range(SAMPLE_TRAINING_RUNS)
        ]
        targets.append(
            _build_touch_target_player(f"{SAMPLE_TARGET_ID_PREFIX}{slug}", label, i, phrase, runs)
        )
    return tuple(targets)


@cache
def sample_targets(level: str, phrase: str) -> tuple[Player, ...]:
    """The simulated practice targets for one level's phrase: three
    typists for a keyboard level, two tappers for the touch level.
    Deterministic (seeded by level + bot slug) and cheap enough to
    cache forever -- there's no per-party or per-request variation to
    invalidate on."""
    if level == TOUCH_LEVEL:
        return _touch_sample_targets(phrase)
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


def _decode_place_key(s: str) -> PlaceKey:
    axis, code = s.split("|")
    return ("tap_x" if axis == "tap_x" else "tap_y", code)


def touch_targets_dir() -> Path:
    """Where a permanent touch target is kept: apart from the keyboard
    one, so recording either never overwrites the other. Read from
    TARGETS_DIR on every call, so the two always move together."""
    return TARGETS_DIR / "touch"


def _stats_out(stats: RunningStats) -> dict[str, float]:
    return {"count": stats.count, "mean": stats.mean, "m2": stats.m2}


def save_permanent_touch_target(path: Path, *, name: str, runs: list[list[TapEvent]]) -> None:
    """save_permanent_target for the touch line: the same derived
    shape plus the tap-position profile, and never a raw tap. Callers
    gate this behind settings.debug, as they do save_permanent_target."""
    phrase = phrase_from_run(to_key_events(runs[0]))
    player = _build_touch_target_player("ignored", name, 0, phrase, runs)
    line = {
        "threshold": player.threshold,
        "profile": {_encode_feature_key(k): _stats_out(v) for k, v in player.profile.items()},
        "place_profile": {"|".join(k): _stats_out(v) for k, v in player.place_profile.items()},
        "notes": [{"ch": n.ch, "start_ms": n.start_ms, "dur_ms": n.dur_ms} for n in player.notes],
        "training_line_count": player.training_line_count,
    }
    path.write_text(json.dumps({"name": name, "lines": {TOUCH_LEVEL: line}}, indent=2))


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
            # score_attempts.training_lines (docs/plans/done/PARTY_LAUNCH_PLAN.md
            # section 10) when this target is attacked -- the
            # raw lines themselves are never kept, same as a real
            # player, but the count is cheap to persist.
            "training_line_count": player.training_line_count,
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
    touch = level == TOUCH_LEVEL
    files = sorted((touch_targets_dir() if touch else TARGETS_DIR).glob("*.json"))
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
    # A touch target gets its own id, and so its own score_id, even
    # when it shares a name with the keyboard one.
    slug = name.lower().replace(" ", "-")
    target_id = f"{PERMANENT_TARGET_ID_PREFIX}{'touch-' if touch else ''}{slug}"
    place_profile = {
        _decode_place_key(k): RunningStats(count=v["count"], mean=v["mean"], m2=v["m2"])
        for k, v in line.get("place_profile", {}).items()
    }
    return Player(
        id=target_id,
        name=name,
        color=5,
        profile=profile,
        place_profile=place_profile,
        threshold=line["threshold"],
        notes=notes,
        training_line_count=line.get("training_line_count", 0),
        # This function rebuilds a fresh Player from the file on every
        # call (unlike sample_targets(), which is cached) -- without
        # this, every call would hand out a *different* random
        # score_id, useless for a target_id that score_attempts rows
        # need to stay consistent across the process's life. See
        # scores/target_ids.py.
        score_id=score_id_for_target(target_id),
    )
