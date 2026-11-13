/**
 * Drawing and describing where a touch player's taps land
 * (docs/plans/active/MOBILE_PLAN.md Phase 2 section 3), from the
 * per-key averages and spreads the room sends (PlayerView.tap_map)
 * and, on a result, from the line that was just tapped in this
 * browser. Display only: the score always comes from the server.
 */

import type { NoteView, TapPointView } from "./game-api";
import type { Tap } from "./tap-line";
import { codeFor } from "./tap-line";

const ROWS = ["qwertyuiop", "asdfghjkl", "zxcvbnm"];
/** One letter key in the drawing, in SVG units. */
const KEY = 38;
const GAP = 2;
/** The scorer's floor on a position's spread (game/touch_scoring.py's
 * TOUCH_MIN_PLACE_STD). Mirrored only so the shaded area and the
 * giveaways read the same way the score does. */
const MIN_PLACE_SPREAD = 0.08;
/** The scorer's floors on a timing's spread (game/scoring.py). */
const MIN_TIMING_SPREAD_MS = 12;
const MIN_TIMING_SPREAD_RATIO = 0.12;
/** A gap longer than this is a pause, which the scorer skips too. */
const MAX_GAP_MS = 2000;

const label = (ch: string): string => (ch === " " ? "space" : ch);
const esc = (s: string): string =>
  s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] ?? c);

interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

function keyBoxes(): Map<string, Box> {
  const boxes = new Map<string, Box>();
  ROWS.forEach((row, r) => {
    const offset = (400 - row.length * (KEY + GAP)) / 2;
    [...row].forEach((c, i) => boxes.set(c, { x: offset + i * (KEY + GAP), y: 4 + r * (KEY + GAP), w: KEY, h: KEY }));
  });
  boxes.set(" ", { x: 80, y: 4 + 3 * (KEY + GAP), w: 240, h: KEY });
  return boxes;
}

/** Where one line's taps landed on each key: the average, as the
 * scorer takes it. x is null for the space bar, which is too wide for
 * side-to-side position to mean anything. */
export interface KeySpot {
  x: number | null;
  y: number;
}

export function spotsFromTaps(taps: readonly Tap[]): Map<string, KeySpot> {
  const sums = new Map<string, { x: number; y: number; n: number }>();
  for (const tap of taps) {
    const s = sums.get(tap.code) ?? { x: 0, y: 0, n: 0 };
    s.x += tap.dx;
    s.y += tap.dy;
    s.n += 1;
    sums.set(tap.code, s);
  }
  const spots = new Map<string, KeySpot>();
  sums.forEach((s, code) => spots.set(code, { x: code === "Space" ? null : s.x / s.n, y: s.y / s.n }));
  return spots;
}

/** A replay lands every tap on the target's own average. */
export function spotsFromTapMap(points: readonly TapPointView[]): Map<string, KeySpot> {
  return new Map(points.map((p) => [p.code, { x: p.x, y: p.y }]));
}

const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));

/**
 * The keyboard, with a dot at the average tap on each key of the line
 * and a shaded area for its usual variation. `attempt` adds a square
 * where one line's taps landed.
 */
export function tapMapSVG(
  points: readonly TapPointView[],
  color: number,
  phrase: string,
  attempt: ReadonlyMap<string, KeySpot> | null,
  name?: string,
): string {
  const byCode = new Map(points.map((p) => [p.code, p]));
  const col = `var(--p${color})`;
  let g = "";
  keyBoxes().forEach((b, c) => {
    const used = phrase.includes(c);
    g += `<rect class="${used ? "m-key" : "m-off"}" x="${b.x}" y="${b.y}" width="${b.w}" height="${b.h}" rx="4"/>`;
    if (!used) return;
    const cx = b.x + b.w / 2;
    const cy = b.y + b.h / 2;
    g += `<text class="m-label" x="${b.x + 3}" y="${b.y + 9}">${label(c)}</text>`;
    g += `<path class="m-center" d="M${cx - 3} ${cy} h6 M${cx} ${cy - 3} v6"/>`;
    const p = byCode.get(codeFor(c));
    if (p) {
      const px = cx + (p.x ?? 0) * KEY;
      const py = cy + p.y * KEY;
      const rx = p.x_spread === null ? 4 : clamp(Math.max(p.x_spread, MIN_PLACE_SPREAD) * KEY, 2.5, 14);
      const ry = clamp(Math.max(p.y_spread, MIN_PLACE_SPREAD) * KEY, 2.5, 14);
      g += `<ellipse cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" rx="${rx.toFixed(1)}" ry="${ry.toFixed(1)}" fill="${col}" opacity=".3"/><circle cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="2.6" fill="${col}"/>`;
    }
    const a = attempt?.get(codeFor(c));
    if (a) {
      g += `<rect class="m-attempt" x="${(cx + (a.x ?? 0) * KEY - 2).toFixed(1)}" y="${(cy + a.y * KEY - 2).toFixed(1)}" width="4" height="4"/>`;
    }
  });
  const who = name ? ` for ${esc(name)}` : "";
  const overlay = attempt ? " Each square is where this attempt landed." : "";
  return `<svg viewBox="0 0 400 168" role="img" aria-label="Tap map${who}. For each key of the line, the dot is the average tap and the shaded area is its usual variation.${overlay}">${g}</svg>`;
}

/** How far a player's taps sit from the key centers on average, in
 * key widths (positive is right) and heights (positive is low). Null
 * with no tap map to read. */
export function leans(points: readonly TapPointView[]): { side: number | null; height: number | null } {
  const mean = (values: number[]): number | null =>
    values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
  return {
    side: mean(points.map((p) => p.x).filter((x): x is number => x !== null)),
    height: mean(points.map((p) => p.y)),
  };
}

export interface Giveaway {
  kind: "hold" | "gap" | "x" | "y";
  /** The key, or the two keys of a gap, as characters of the line. */
  keys: string;
  /** Milliseconds for a hold or gap; a fraction of a key for x or y. */
  diff: number;
  /** The difference in units of the target's usual variation. Only
   * for ranking: the browser has the target's typical line and tap
   * map, not their timing spreads, so this is a guide and never the
   * score. */
  size: number;
}

/**
 * What stood out most in one tapped line against a target's typical
 * line (`notes`, the same median timing their ring is drawn from) and
 * tap map. The largest `count`, biggest first.
 */
export function giveaways(
  taps: readonly Tap[],
  notes: readonly NoteView[],
  points: readonly TapPointView[],
  count = 3,
): Giveaway[] {
  const found: Giveaway[] = [];
  const timingScale = (usual: number): number => Math.max(MIN_TIMING_SPREAD_MS, MIN_TIMING_SPREAD_RATIO * Math.abs(usual));
  const average = (values: number[]): number => values.reduce((a, b) => a + b, 0) / values.length;

  // Timing, averaged per key and per pair of keys, as the scorer keys it.
  const holds = new Map<string, { mine: number[]; usual: number[] }>();
  const gaps = new Map<string, { mine: number[]; usual: number[] }>();
  const add = (into: Map<string, { mine: number[]; usual: number[] }>, key: string, mine: number, usual: number): void => {
    const entry = into.get(key) ?? { mine: [], usual: [] };
    entry.mine.push(mine);
    entry.usual.push(usual);
    into.set(key, entry);
  };
  taps.forEach((tap, i) => {
    const note = notes[i];
    if (!note || note.ch !== tap.ch) return;
    if (tap.up !== null) add(holds, tap.ch, tap.up - tap.down, note.dur_ms);
    const before = taps[i - 1];
    const noteBefore = notes[i - 1];
    if (!before || !noteBefore || tap.afterError) return;
    const gap = tap.down - before.down;
    if (gap <= MAX_GAP_MS) add(gaps, before.ch + tap.ch, gap, note.start_ms - noteBefore.start_ms);
  });
  const timing = (kind: "hold" | "gap", into: Map<string, { mine: number[]; usual: number[] }>): void => {
    into.forEach((entry, keys) => {
      const usual = average(entry.usual);
      const diff = average(entry.mine) - usual;
      found.push({ kind, keys, diff, size: Math.abs(diff) / timingScale(usual) });
    });
  };
  timing("hold", holds);
  timing("gap", gaps);

  // Position, per key.
  const byCode = new Map(points.map((p) => [p.code, p]));
  const chOf = new Map(taps.map((t) => [t.code, t.ch]));
  spotsFromTaps(taps).forEach((spot, code) => {
    const usual = byCode.get(code);
    const ch = chOf.get(code);
    if (!usual || ch === undefined) return;
    if (spot.x !== null && usual.x !== null && usual.x_spread !== null) {
      const diff = spot.x - usual.x;
      found.push({ kind: "x", keys: ch, diff, size: Math.abs(diff) / Math.max(usual.x_spread, MIN_PLACE_SPREAD) });
    }
    const diff = spot.y - usual.y;
    found.push({ kind: "y", keys: ch, diff, size: Math.abs(diff) / Math.max(usual.y_spread, MIN_PLACE_SPREAD) });
  });

  return found
    .filter((g) => Number.isFinite(g.size) && g.size > 0)
    .sort((a, b) => b.size - a.size)
    .slice(0, count);
}

/** One giveaway as a sentence, with the keys in bold. The keys are
 * single characters of the game's own line, so nothing needs escaping. */
export function giveawayHTML(g: Giveaway): string {
  const first = `<b>${label(g.keys[0] ?? "")}</b>`;
  if (g.kind === "hold") {
    return `Held ${first} ${Math.round(Math.abs(g.diff))} ms ${g.diff > 0 ? "longer" : "shorter"}`;
  }
  if (g.kind === "gap") {
    return `The gap from ${first} to <b>${label(g.keys[1] ?? "")}</b> was ${Math.round(Math.abs(g.diff))} ms ${g.diff > 0 ? "longer" : "shorter"}`;
  }
  const percent = Math.round(Math.abs(g.diff) * 100);
  if (g.kind === "x") return `Tapped ${first} ${percent}% of a key further ${g.diff > 0 ? "right" : "left"}`;
  return `Tapped ${first} ${percent}% of a key ${g.diff > 0 ? "lower" : "higher"}`;
}
