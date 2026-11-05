/**
 * Typing Twin Party: a multiplayer rhythm-matching game built on top
 * of this app's real backend, not a self-contained toy. Every real
 * player's enrollment and every attempt against them is scored by
 * POST /api/profile/samples and POST /api/profile/verify -- the same
 * Argon2id accounts, Postgres-backed profiles, and scaled-Manhattan
 * scoring the rest of the app uses, under a random, disposable
 * account per player (see the privacy note on the page itself).
 *
 * The three "simulated" practice players are explicitly fake data
 * generated in the browser -- they never get a backend account and
 * are always scored locally (localScore/localBuildProfile below),
 * since there is nothing real to protect or measure about them.
 *
 * Attacking another real player works without any new backend
 * capability: the backend only ever lets a session check the
 * currently logged-in account's own profile (see
 * api/deps.py::get_current_user), so this page silently logs in as
 * whichever player is the *target* right before scoring an attempt,
 * regardless of who is physically typing. The account that gets
 * checked is always the one actually logged in -- the same rule
 * every other page on this site follows.
 *
 * Game UI/presentation (rings, piano rolls, sound, the party flow
 * itself) is unchanged from the source file this was ported from.
 * What changed: every score involving a *real* player now comes from
 * the backend instead of this file's own duplicate implementation.
 */

import { addSample, deleteProfile, login, logout, register, verifySample } from "../api";
import type { TypingResult } from "../api";
import { KeystrokeCapture } from "../capture";
import type { CapturedEvent } from "../capture";

type LevelKey = "word" | "sentence" | "long";

const LEVELS: Record<LevelKey, { name: string; blurb: string; phrase: string; rounds: number }> = {
  word: { name: "One word", blurb: "Quick and brutal. About 45 seconds each.", phrase: "nukiae", rounds: 9 },
  sentence: {
    name: "A sentence",
    blurb: "The best party mode. About a minute each.",
    phrase: "quiet rhythm hides in every small habit of your hands",
    rounds: 5,
  },
  long: {
    name: "A long line",
    blurb: "More to measure, more to fake. About 2 minutes each.",
    phrase:
      "every keyboard keeps a quiet record of the hands that use it and those records are surprisingly hard to fake",
    rounds: 4,
  },
};
const MAX_FLIGHT = 2000;
const QWERTY = "qwertyuiopasdfghjklzxcvbnm ";
const label = (c: string): string => (c === " " ? "space" : c);
const esc = (s: string): string =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
const $ = (id: string): HTMLElement | null => document.getElementById(id);

//: Mirrors core/scoring.py's DEFAULT_THRESHOLD -- used only to draw
//: the gauge and render ratios for real (backend-scored) players; the
//: actual match/no_match/insufficient_data decision always comes from
//: the server. Every real player shares this one threshold, unlike
//: bots, which keep their own locally-calibrated one (closer to the
//: original file's per-player calibration, since there's no backend
//: profile to calibrate against for them).
const DISPLAY_THRESHOLD = 1.0724;

/* ---------- Types ---------- */

interface KeyRecord {
  ch: string;
  down: number;
  up: number | null;
  afterError: boolean;
}

interface Run {
  idx: number;
  keys: KeyRecord[];
  errors: number;
  pendingError: boolean;
  held: Record<string, KeyRecord>;
  finished: boolean;
}

interface Note {
  ch: string;
  start: number;
  dur: number;
}

interface LocalStat {
  n: number;
  mean: number;
  m2: number;
}

type Mode = "attack" | "self" | "disguise" | "replay";
type ViewName = "intro" | "name" | "enroll" | "reveal" | "room" | "attack" | "scores" | "how";

interface Player {
  id: string;
  name: string;
  runs: Run[];
  notes: Note[];
  color: number;
  isBot: boolean;
  // Bots only -- see the module docstring on why real players don't
  // get a local profile/threshold at all.
  profile?: Map<string, LocalStat>;
  threshold?: number;
}

interface ScoreOutcome {
  distance: number | null;
  compared: number;
  parts: { k: string; z: number; diff: number }[];
}

interface Verdict {
  good: boolean;
  word: string;
  text: string;
  counted: boolean;
  pass?: boolean;
}

interface Attempt {
  n: number;
  who: string;
  typistId: string;
  targetId: string;
  target: string;
  mode: Mode;
  d: number | null;
  thr: number;
  ratio: number | null;
  word: string;
  counted: boolean;
  pass?: boolean;
}

interface LastResult {
  run: Run;
  res: ScoreOutcome;
  v: Verdict;
  target: Player;
  mode: Mode;
  who: string;
  paceRatio: number;
}

interface State {
  view: ViewName;
  level: LevelKey | null;
  players: Player[];
  attempts: Attempt[];
  typingAs: string | null;
  target: string | null;
  mode: Mode;
  enrollName: string;
  enrollRuns: Run[];
  enrollingPlayerId: string | null;
  run: Run | null;
  last: LastResult | null;
  replaying: number;
  justAdded: string | null;
  confirmNew: boolean;
  nextColor: number;
}

const S: State = {
  view: "intro",
  level: null,
  players: [],
  attempts: [],
  typingAs: null,
  target: null,
  mode: "attack",
  enrollName: "",
  enrollRuns: [],
  enrollingPlayerId: null,
  run: null,
  last: null,
  replaying: 0,
  justAdded: null,
  confirmNew: false,
  nextColor: 0,
};
const phrase = (): string => LEVELS[S.level!].phrase;
const lanes = (p: string): string[] => [...QWERTY].filter((c) => p.includes(c));

/* ---------- Account management (real players only) ---------- */

function randomToken(length: number): string {
  const chars = "abcdefghijklmnopqrstuvwxyz0123456789";
  const bytes = crypto.getRandomValues(new Uint8Array(length));
  return Array.from(bytes, (b) => chars[b % chars.length]!).join("");
}

const accounts = new Map<string, { username: string; password: string }>();
let activeAccountId: string | null = null;

/** Registers a brand-new disposable account for `playerId` and logs
 * into it. Never surfaces a username/password to anyone -- there's
 * nothing to remember, since nothing about this account is reused
 * after this party. */
async function registerAndLogin(playerId: string): Promise<void> {
  const creds = { username: `twin-${randomToken(12)}`, password: randomToken(24) };
  await register(creds.username, creds.password);
  accounts.set(playerId, creds);
  await login(creds.username, creds.password);
  activeAccountId = playerId;
}

/** Switches the active session to `playerId`'s existing account, if
 * it isn't already. This is the only thing that makes "attack" work
 * without any new backend capability: whoever is logged in is whose
 * profile gets checked, so scoring an attempt against a target is
 * just making sure the target is the one logged in first. */
async function ensureActiveAccount(playerId: string): Promise<void> {
  if (activeAccountId === playerId) return;
  const creds = accounts.get(playerId);
  if (!creds) throw new Error(`no backend account registered for player ${playerId}`);
  await login(creds.username, creds.password);
  activeAccountId = playerId;
}

/* ---------- Local scoring (bots only -- see module docstring) ---------- */

function localFeatures(run: Run): Map<string, number> {
  const groups = new Map<string, number[]>();
  const add = (k: string, v: number): void => {
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k)!.push(v);
  };
  run.keys.forEach((r, i) => {
    if (r.up !== null && r.up >= r.down) add(`h:${r.ch}`, r.up - r.down);
    if (i > 0 && !r.afterError) {
      const gap = r.down - run.keys[i - 1]!.down;
      if (gap >= 0 && gap <= MAX_FLIGHT) add(`f:${run.keys[i - 1]!.ch}${r.ch}`, gap);
    }
  });
  const out = new Map<string, number>();
  groups.forEach((v, k) => out.set(k, v.reduce((a, b) => a + b, 0) / v.length));
  return out;
}

function duration(run: Run): number {
  return run.keys[run.keys.length - 1]!.down - run.keys[0]!.down;
}

function localBuildProfile(runs: Run[]): Map<string, LocalStat> {
  const stats = new Map<string, LocalStat>();
  runs.forEach((run) =>
    localFeatures(run).forEach((v, k) => {
      const s = stats.get(k) ?? { n: 0, mean: 0, m2: 0 };
      s.n += 1;
      const d = v - s.mean;
      s.mean += d / s.n;
      s.m2 += d * (v - s.mean);
      stats.set(k, s);
    }),
  );
  return stats;
}

function localSpread(s: LocalStat): number {
  const sd = s.n > 1 ? Math.sqrt(s.m2 / (s.n - 1)) : 0;
  return Math.max(sd, 12, 0.12 * s.mean);
}

function localMinFeatures(profile: Map<string, LocalStat>): number {
  return Math.min(20, Math.floor(profile.size * 0.7));
}

function localScore(run: Run, profile: Map<string, LocalStat>): ScoreOutcome {
  const parts: { k: string; z: number; diff: number }[] = [];
  localFeatures(run).forEach((v, k) => {
    const s = profile.get(k);
    if (!s || s.n < 2) return;
    parts.push({ k, z: Math.abs(v - s.mean) / localSpread(s), diff: v - s.mean });
  });
  if (parts.length < localMinFeatures(profile)) return { distance: null, compared: parts.length, parts };
  return { distance: parts.reduce((a, p) => a + p.z, 0) / parts.length, compared: parts.length, parts };
}

function localCalibrate(runs: Run[]): number {
  const held = runs
    .map((_, i) => localScore(runs[i]!, localBuildProfile(runs.filter((_, j) => j !== i))).distance)
    .filter((d): d is number => d !== null);
  if (!held.length) return 2;
  return Math.min(3.5, Math.max(1.3, Math.max(...held) * 1.2));
}

/* ---------- Capture (real players) ---------- */

const capture = new KeystrokeCapture();

function charToCode(ch: string): string {
  // This game's phrases are lowercase letters and spaces only, so
  // this round-trips reliably back to the physical key code a real
  // keydown would have carried -- needed only for replay, which has
  // no live KeyboardEvent to capture in the first place.
  return ch === " " ? "Space" : `Key${ch.toUpperCase()}`;
}

function sampleFromRun(run: Run): CapturedEvent[] {
  const t0 = run.keys.length ? run.keys[0]!.down : 0;
  const events: CapturedEvent[] = [];
  for (const r of run.keys) {
    const code = charToCode(r.ch);
    events.push({ code, action: "down", t_ms: r.down - t0 });
    if (r.up !== null) events.push({ code, action: "up", t_ms: r.up - t0 });
  }
  // Overlapping presses mean down/up pairs aren't necessarily already
  // in chronological order -- the backend requires non-decreasing
  // timestamps.
  events.sort((a, b) => a.t_ms - b.t_ms);
  return events;
}

/* ---------- Players ---------- */

function medianNotes(runs: Run[]): Note[] {
  const len = runs[0]!.keys.length;
  let t = 0;
  const notes: Note[] = [];
  for (let i = 0; i < len; i++) {
    if (i > 0) t += median(runs.map((r) => r.keys[i]!.down - r.keys[i - 1]!.down));
    notes.push({
      ch: runs[0]!.keys[i]!.ch,
      start: t,
      dur: median(runs.map((r) => (r.keys[i]!.up !== null ? r.keys[i]!.up! - r.keys[i]!.down : 70))),
    });
  }
  return notes;
}

function notesFromRun(run: Run): Note[] {
  const t0 = run.keys.length ? run.keys[0]!.down : 0;
  return run.keys.map((r) => ({ ch: r.ch, start: r.down - t0, dur: r.up !== null ? r.up - r.down : 70 }));
}

function median(a: number[]): number {
  const s = [...a].sort((x, y) => x - y);
  return s.length ? s[Math.floor(s.length / 2)]! : 0;
}

const usualDuration = (p: Player): number => p.runs.reduce((a, r) => a + duration(r), 0) / p.runs.length;

function makeHumanPlayer(name: string, runs: Run[], id: string): Player {
  return { id, name, runs, notes: medianNotes(runs), color: S.nextColor++ % 6, isBot: false };
}

function makeBotPlayer(name: string, runs: Run[]): Player {
  const profile = localBuildProfile(runs);
  return {
    id: `${S.players.length}-${name}`,
    name,
    runs,
    notes: medianNotes(runs),
    color: S.nextColor++ % 6,
    isBot: true,
    profile,
    threshold: localCalibrate(runs),
  };
}

function hash(s: string): number {
  let h = 2166136261;
  for (const c of s) {
    h ^= c.charCodeAt(0);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h;
}

function sampleRuns(text: string, seed: string, speed: number, count: number): Run[] {
  let state = (hash(seed) % 2147483646) + 1;
  const rnd = (): number => (state = (state * 16807) % 2147483647) / 2147483647;
  const unit = (key: string): number => (hash(`${seed}|${key}`) % 1000) / 1000;
  const runs: Run[] = [];
  for (let r = 0; r < count; r++) {
    let t = 0;
    const keys: KeyRecord[] = [];
    [...text].forEach((ch, i) => {
      if (i > 0) t += speed * (70 + 170 * unit(text[i - 1]! + ch)) * (0.9 + rnd() * 0.2);
      const hold = (55 + 60 * unit(ch)) * (0.9 + rnd() * 0.2);
      keys.push({ ch, down: t, up: t + hold, afterError: false });
    });
    runs.push({ idx: keys.length, keys, errors: 0, pendingError: false, held: {}, finished: true });
  }
  return runs;
}

const SAMPLES: [string, number][] = [
  ["Sample: Quick Fingers", 0.72],
  ["Sample: Steady Hands", 1.05],
  ["Sample: Two-Finger Typist", 1.4],
];
function addSamples(): void {
  SAMPLES.forEach(([n, sp]) => S.players.push(makeBotPlayer(n, sampleRuns(phrase(), n, sp!, 6))));
}
const byId = (id: string): Player | undefined => S.players.find((p) => p.id === id);
const humans = (): Player[] => S.players.filter((p) => !p.isBot);

/* ---------- Signature ring ---------- */

interface RingPoint {
  x: number;
  y: number;
  a: number;
  h: number;
}

function ringPoints(notes: Note[]): RingPoint[] {
  const gaps = notes.map((n, i) => (i === 0 ? null : n.start - notes[i - 1]!.start));
  const med = median(gaps.filter((g): g is number => g !== null)) || 1;
  const holdMed = median(notes.map((n) => n.dur)) || 1;
  const N = notes.length;
  const cx = 120;
  const cy = 120;
  const base = 44;
  const scale = 40;
  return notes.map((n, i) => {
    const g = gaps[i] === null ? 1 : Math.min(2.6, gaps[i]! / med);
    const a = -Math.PI / 2 + (i / N) * Math.PI * 2;
    const r = base + g * scale;
    const h = Math.min(2.2, n.dur / holdMed);
    return { x: cx + Math.cos(a) * r, y: cy + Math.sin(a) * r, a, h };
  });
}

function smoothPath(pts: RingPoint[]): string {
  const n = pts.length;
  let d = `M${pts[0]!.x.toFixed(1)} ${pts[0]!.y.toFixed(1)}`;
  for (let i = 0; i < n; i++) {
    const p0 = pts[(i - 1 + n) % n]!;
    const p1 = pts[i]!;
    const p2 = pts[(i + 1) % n]!;
    const p3 = pts[(i + 2) % n]!;
    const c1x = p1.x + (p2.x - p0.x) / 6;
    const c1y = p1.y + (p2.y - p0.y) / 6;
    const c2x = p2.x - (p3.x - p1.x) / 6;
    const c2y = p2.y - (p3.y - p1.y) / 6;
    d += ` C${c1x.toFixed(1)} ${c1y.toFixed(1)} ${c2x.toFixed(1)} ${c2y.toFixed(1)} ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`;
  }
  return `${d}Z`;
}

function ringSVG(notes: Note[], color: number, compareNotes: Note[] | null, name?: string): string {
  const pts = ringPoints(notes);
  const col = `var(--p${color})`;
  let g = `<circle class="ring-guide" cx="120" cy="120" r="84"/>`;
  pts.forEach((p) => {
    const r1 = 22;
    const r2 = r1 + p.h * 10;
    g += `<line class="ring-tick" stroke="${col}" x1="${(120 + Math.cos(p.a) * r1).toFixed(1)}" y1="${(120 + Math.sin(p.a) * r1).toFixed(1)}" x2="${(120 + Math.cos(p.a) * r2).toFixed(1)}" y2="${(120 + Math.sin(p.a) * r2).toFixed(1)}"/>`;
  });
  const d = smoothPath(pts);
  g += `<path class="ring-fill" fill="${col}" d="${d}"/><path class="ring-line" stroke="${col}" d="${d}"/>`;
  if (compareNotes) g += `<path class="ring-compare" d="${smoothPath(ringPoints(compareNotes))}"/>`;
  return `<svg viewBox="0 0 240 240" role="img" aria-label="Typing signature${name ? ` for ${esc(name)}` : ""}. The outer shape shows the gap before each key, and the inner marks show how long each key is held.">${g}</svg>`;
}

/* ---------- Roll ---------- */

function rollSVG(text: string, layers: { notes: Note[]; cls: string; inset?: boolean }[], minEnd?: number): string {
  const L_ = lanes(text);
  const W = 760;
  const L = 44;
  const top = 16;
  const laneH = 13;
  const H = top + L_.length * laneH + 28;
  const end = Math.max(minEnd ?? 0, 1000, ...layers.flatMap((l) => l.notes.map((n) => n.start + n.dur))) * 1.03;
  const x = (ms: number): number => L + (ms / end) * (W - L - 10);
  const step = [500, 1000, 2000, 5000, 10000, 20000, 60000].find((s) => end / s <= 10) ?? 120000;
  let g = "";
  for (let i = 8; i < W; i += 14) g += `<circle class="perf" cx="${i}" cy="6" r="2.5"/>`;
  L_.forEach((c, i) => {
    const y = top + i * laneH;
    g += `<line class="lane-line" x1="${L}" x2="${W - 10}" y1="${y + laneH}" y2="${y + laneH}"/><text class="lane-label" x="${L - 6}" y="${y + 10}" text-anchor="end">${label(c)}</text>`;
  });
  const base = top + L_.length * laneH;
  for (let t = 0; t <= end; t += step) {
    g += `<line class="tick-line" x1="${x(t)}" x2="${x(t)}" y1="${top}" y2="${base}"/><text class="tick-label" x="${x(t)}" y="${base + 15}" text-anchor="middle">${t / 1000}s</text>`;
  }
  layers.forEach((l) =>
    l.notes.forEach((n) => {
      const i = L_.indexOf(n.ch);
      if (i < 0) return;
      const y = top + i * laneH + (l.inset ? 4 : 2);
      const h = laneH - (l.inset ? 8 : 4);
      g += `<rect class="${l.cls}" x="${x(n.start).toFixed(1)}" y="${y}" width="${Math.max(3, x(n.start + n.dur) - x(n.start)).toFixed(1)}" height="${h}" rx="2"/>`;
    }),
  );
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Piano roll. Each row is a key, and each bar shows when it was pressed and how long it was held.">${g}</svg>`;
}

/* ---------- Typing ---------- */

function startRun(): void {
  S.run = { idx: 0, keys: [], errors: 0, pendingError: false, held: {}, finished: false };
  capture.reset();
  drawTyper();
  $("typer")?.focus({ preventScroll: true });
}

function canType(): boolean {
  const t = $("typer");
  return S.run !== null && !S.run.finished && !S.replaying && t !== null && document.activeElement === t;
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && S.run && $("typer") && !S.replaying) {
    e.preventDefault();
    startRun();
    return;
  }
  if (!canType() || e.ctrlKey || e.metaKey || e.altKey || e.key.length !== 1) return;
  e.preventDefault();
  if (e.repeat) return;
  const r = S.run!;
  const text = phrase();
  const expected = text[r.idx];
  if (e.key.toLowerCase() === expected) {
    const rec: KeyRecord = { ch: expected, down: e.timeStamp, up: null, afterError: r.pendingError };
    r.keys.push(rec);
    r.held[e.code] = rec;
    r.pendingError = false;
    r.idx += 1;
    capture.record(e);
    if (r.keys.length === 1) $("result")?.setAttribute("hidden", "");
    if (r.idx === text.length) {
      r.finished = true;
      setTimeout(() => void finishRun(), 260);
    }
    drawTyper();
  } else {
    r.errors += 1;
    r.pendingError = true;
    const t = $("typer");
    t?.classList.remove("oops");
    void t?.offsetWidth;
    t?.classList.add("oops");
    drawTyper(true);
  }
});

document.addEventListener("keyup", (e) => {
  const r = S.run;
  if (!r?.held[e.code]) return;
  capture.record(e);
  r.held[e.code]!.up = e.timeStamp;
  delete r.held[e.code];
});

function showEnrollError(error: unknown): void {
  console.error("Typing Twin Party: failed to save an enrollment line", error);
  const el = $("enroll-error");
  if (el) {
    el.textContent =
      "Couldn't reach the server to save that line. Check your connection and press Esc to try the line again.";
    el.hidden = false;
  }
}

async function finishRun(): Promise<void> {
  const run = S.run;
  if (!run) return;

  if (S.view === "enroll") {
    S.enrollRuns.push(run);
    const cfg = LEVELS[S.level!];
    const isWarmup = S.enrollRuns.length === 1;

    if (!isWarmup) {
      try {
        await ensureActiveAccount(S.enrollingPlayerId!);
        await addSample(capture.sample());
      } catch (error) {
        showEnrollError(error);
        return;
      }
    }

    if (S.enrollRuns.length === cfg!.rounds) {
      const clean = S.enrollRuns.slice(1);
      const player = makeHumanPlayer(S.enrollName, clean, S.enrollingPlayerId!);
      S.players.push(player);
      S.typingAs = player.id;
      S.justAdded = player.id;
      S.run = null;
      S.view = "reveal";
    } else {
      render();
      startRun();
      return;
    }
    render();
    return;
  }

  await judge(run, S.typingAs ? (byId(S.typingAs) ?? null) : null, byId(S.target!)!, S.mode);
  render();
  startRun();
}

function drawTyper(oops?: boolean): void {
  const r = S.run;
  const p = $("phrase");
  if (!p || !r) return;
  const text = phrase();
  const i = r.idx;
  p.innerHTML =
    `<span>${text.slice(0, i)}</span>` +
    (i < text.length
      ? `<span class="cur">${text[i] === " " ? "&nbsp;" : text[i]}</span><span class="todo">${text.slice(i + 1)}</span>`
      : "");
  if (!oops) $("typer")?.classList.remove("oops");
  const typos = $("typos");
  if (typos) typos.textContent = r.errors === 1 ? "1 wrong key" : `${r.errors} wrong keys`;
  const live = $("live-roll");
  if (live) {
    const target = S.view === "attack" ? byId(S.target!) : undefined;
    const layers: { notes: Note[]; cls: string; inset?: boolean }[] = [];
    if (target && S.mode === "attack") layers.push({ notes: target.notes, cls: "n-ghost" });
    layers.push({
      notes: notesFromRun(r),
      cls: target ? "n-b" : "n-a",
      inset: !!target && S.mode === "attack",
    });
    live.innerHTML = rollSVG(text, layers, target ? usualDuration(target) : 0);
  }
}

function typerHTML(hint: string, between?: string, extra?: string): string {
  return `<div class="typer" id="typer" tabindex="0" role="textbox" aria-label="Typing area. Type this line: ${phrase()}">
    <div class="phrase" id="phrase"></div>
    <div class="typer-foot"><span class="blur-note">Click here to type</span><span>${hint}</span><span id="typos"></span></div>
  </div>
  <div class="row"><button class="quiet" id="restart">Restart line (Esc)</button>${extra ?? ""}</div>
  <p class="error" id="enroll-error" hidden></p>
  ${between ?? ""}
  <div class="roll-box" id="live-roll"></div>`;
}

/* ---------- Judging ---------- */

async function judge(run: Run, typist: Player | null, target: Player, mode: Mode): Promise<void> {
  const paceRatio = duration(run) / usualDuration(target);
  const who = typist ? typist.name : "Guest";

  let res: ScoreOutcome;
  let thr: number;
  if (target.isBot) {
    res = localScore(run, target.profile!);
    thr = target.threshold!;
  } else {
    thr = DISPLAY_THRESHOLD;
    try {
      await ensureActiveAccount(target.id);
      const sample = mode === "replay" ? sampleFromRun(run) : capture.sample();
      const result: TypingResult = await verifySample(sample);
      res = {
        distance: result.decision === "insufficient_data" ? null : result.score,
        compared: result.compared_features,
        parts: [], // the backend doesn't return a per-feature breakdown
      };
    } catch {
      res = { distance: null, compared: 0, parts: [] };
    }
  }

  const d = res.distance;
  let v: Verdict;
  if (d === null) {
    v = { good: false, word: "Too messy", text: "Too many wrong keys broke up the rhythm. Try the line again.", counted: false };
  } else if (mode === "self") {
    v =
      d <= thr
        ? { good: true, word: "That's you", text: "This line sits inside your own rhythm range.", counted: true, pass: true }
        : {
            good: false,
            word: "Who are you?",
            text: "It didn't recognize its own typist. That's a false rejection.",
            counted: true,
            pass: false,
          };
  } else if (mode === "disguise") {
    const paceOk = paceRatio >= 0.85 && paceRatio <= 1.15;
    if (!paceOk) {
      v = {
        good: false,
        word: paceRatio < 1 ? "Too fast" : "Too slow",
        text: `Your pace was ${Math.abs(Math.round((paceRatio - 1) * 100))}% off. Disguises must stay within 15% of your usual pace.`,
        counted: false,
      };
    } else {
      v =
        d > thr
          ? { good: true, word: "Disguised!", text: "You kept your pace and still fooled it.", counted: true, pass: false }
          : {
              good: false,
              word: "Still you",
              text: "It saw through the disguise. Try changing which keys you linger on.",
              counted: true,
              pass: true,
            };
    }
  } else if (mode === "replay") {
    v =
      d <= thr
        ? {
            good: false,
            word: "Replay wins",
            text: "A recording of real timing passes, because the rhythm really is theirs. That's why typing rhythm can't be the only thing protecting a login.",
            counted: true,
            pass: true,
          }
        : { good: true, word: "Replay failed", text: "This replay fell outside the limit.", counted: true, pass: false };
  } else {
    v =
      d <= thr
        ? {
            good: false,
            word: "Fooled it!",
            text: `${esc(who)} passed as ${esc(target.name)}. That's a false acceptance.`,
            counted: true,
            pass: true,
          }
        : {
            good: true,
            word: "Caught!",
            text: `It could tell ${esc(who)} isn't ${esc(target.name)}.`,
            counted: true,
            pass: false,
          };
  }

  S.last = { run, res, v, target, mode, who, paceRatio };
  S.attempts.push({
    n: S.attempts.length + 1,
    who,
    typistId: typist ? typist.id : "guest",
    targetId: target.id,
    target: target.name,
    mode,
    d,
    thr,
    ratio: d === null ? null : d / thr,
    word: v.word,
    counted: v.counted,
    pass: v.pass,
  });
  if (v.counted) {
    buzz((mode === "attack" && v.pass) || (mode === "self" && v.pass) || (mode === "disguise" && !v.pass));
  }
}

function buzz(win: boolean): void {
  try {
    const ctx = new AudioContext();
    const t0 = ctx.currentTime + 0.02;
    (win ? [392, 523, 659] : [196, 165]).forEach((f, i) => {
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.type = "triangle";
      o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, t0 + i * 0.1);
      g.gain.exponentialRampToValueAtTime(0.12, t0 + i * 0.1 + 0.01);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + i * 0.1 + 0.16);
      o.connect(g).connect(ctx.destination);
      o.start(t0 + i * 0.1);
      o.stop(t0 + i * 0.1 + 0.18);
    });
  } catch {
    /* Sound is optional. */
  }
}

function playNotes(notes: Note[]): void {
  try {
    const ctx = new AudioContext();
    const t0 = ctx.currentTime + 0.05;
    const scale = [0, 2, 4, 7, 9];
    const L_ = lanes(phrase());
    notes.forEach((n) => {
      const lane = L_.indexOf(n.ch);
      const semis = scale[lane % 5]! + 12 * Math.floor(lane / 5);
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.type = "triangle";
      o.frequency.value = 196 * 2 ** (semis / 12);
      const a = t0 + n.start / 1000;
      const b = a + Math.max(0.08, n.dur / 1000);
      g.gain.setValueAtTime(0.0001, a);
      g.gain.exponentialRampToValueAtTime(0.16, a + 0.01);
      g.gain.exponentialRampToValueAtTime(0.0001, b + 0.05);
      o.connect(g).connect(ctx.destination);
      o.start(a);
      o.stop(b + 0.06);
    });
  } catch {
    /* Sound is optional. */
  }
}

function tellsHTML(res: ScoreOutcome): string {
  return [...res.parts]
    .sort((a, b) => b.z - a.z)
    .slice(0, 3)
    .map((p) => {
      const ms = Math.round(Math.abs(p.diff));
      const dir = p.diff > 0 ? "longer" : "shorter";
      if (p.k[0] === "h") return `<li>Holding <b>${label(p.k[2]!)}</b> took ${ms} ms ${dir} than the profile</li>`;
      return `<li>The gap from <b>${label(p.k[2]!)}</b> to <b>${label(p.k[3]!)}</b> was ${ms} ms ${dir} than the profile</li>`;
    })
    .join("");
}

function gaugeSVG(d: number, thr: number): string {
  const W = 760;
  const end = Math.max(thr * 2, d * 1.15);
  const x = (v: number): number => 10 + (v / end) * (W - 20);
  const px = Math.min(W - 60, Math.max(60, x(d)));
  return `<svg viewBox="0 0 ${W} 72" role="img" aria-label="Distance ${d.toFixed(2)} against a limit of ${thr.toFixed(2)}">
    <text class="g-val" x="${px}" y="14" text-anchor="middle">distance ${d.toFixed(2)}</text>
    <path class="g-mark" d="M${x(d) - 6} 20 h12 l-6 8 z"/>
    <rect class="g-a" x="10" y="30" width="${x(thr) - 10}" height="12" rx="2"/>
    <rect class="g-b" x="${x(thr)}" y="30" width="${W - 10 - x(thr)}" height="12" rx="2"/>
    <line class="g-thr" x1="${x(thr)}" x2="${x(thr)}" y1="26" y2="46"/>
    <text class="g-text" x="10" y="62">0, identical</text>
    <text class="g-text" x="${x(thr)}" y="62" text-anchor="middle">limit ${thr.toFixed(2)}</text>
    <text class="g-text" x="${W - 10}" y="62" text-anchor="end">further away</text>
  </svg>`;
}

/* ---------- Replay ---------- */

function runReplay(): void {
  const target = byId(S.target!)!;
  const source = target.runs[target.runs.length - 1]!;
  const token = ++S.replaying;
  S.mode = "replay";
  S.last = null;
  render();
  S.run = { idx: 0, keys: [], errors: 0, pendingError: false, held: {}, finished: true };
  const t0 = source.keys[0]!.down;
  source.keys.forEach((k, i) =>
    setTimeout(
      () => {
        if (S.replaying !== token || S.view !== "attack") return;
        S.run!.keys.push({ ch: k.ch, down: k.down - t0, up: k.up === null ? null : k.up - t0, afterError: false });
        S.run!.idx = i + 1;
        drawTyper();
        if (i === source.keys.length - 1) {
          setTimeout(() => {
            void (async () => {
              if (S.replaying !== token || S.view !== "attack") return;
              await judge(S.run!, null, target, "replay");
              const a = S.attempts[S.attempts.length - 1]!;
              a.who = "Replay bot";
              a.typistId = "replay";
              S.replaying = 0;
              S.mode = "attack";
              render();
              startRun();
            })();
          }, 300);
        }
      },
      k.down - t0,
    ),
  );
}

/* ---------- Views ---------- */

function introView(): string {
  const rings = SAMPLES.map(([n, sp], i) => {
    const notes = medianNotes(sampleRuns(LEVELS.sentence.phrase, n, sp!, 6));
    return `<div class="ring">${ringSVG(notes, i, null, n)}</div>`;
  }).join("");
  const coarse = window.matchMedia?.("(pointer: coarse)").matches;
  const levels = Object.entries(LEVELS)
    .map(([k, l]) => `<button class="level" data-level="${k}">${l.name}<span>${l.blurb}</span></button>`)
    .join("");
  return `<section class="hero">
      <div class="stack">
        <h1>Everyone types in their own shape.</h1>
        <p>Type a line a few times and see your rhythm drawn as a signature -- scored for real by this app's own backend. Then gather some friends around one keyboard and try to pass as each other.</p>
        ${coarse ? `<div class="notice">Bring a physical keyboard. Phone keyboards don't report when each key goes down and up.</div>` : ""}
        <div class="eyebrow">Pick your line to start a party</div>
        <div class="levels">${levels}</div>
        <p class="small muted">Playing creates a random, disposable account per real player -- see the privacy note below.</p>
      </div>
      <div class="stack">
        <div class="hero-rings">${rings}</div>
        <p class="small muted">Example signatures from simulated typists. Yours will be made from your real timing.</p>
      </div>
    </section>`;
}

function nameView(): string {
  return `<section class="stack" style="max-width:560px">
    <div class="eyebrow">New player</div>
    <h2>Who's typing?</h2>
    <p class="muted">You'll type the line ${LEVELS[S.level!]!.rounds} times. The first one is a warm-up.</p>
    <form id="name-form" class="row end">
      <label for="player-name">Your name<input id="player-name" maxlength="24" autocomplete="off" required></label>
      <button class="primary" type="submit">Start typing</button>
    </form>
    <button class="quiet" id="to-room" style="align-self:flex-start">Skip and see the room</button>
  </section>`;
}

function enrollView(): string {
  const n = S.enrollRuns.length;
  const cfg = LEVELS[S.level!]!;
  const dots = Array.from(
    { length: cfg.rounds },
    (_, i) => `<span class="dot ${i < n ? "ok" : i === n ? "on" : ""}">${i === 0 ? "Warm-up" : i}</span>`,
  ).join("");
  return `<section class="stack">
    <div class="eyebrow">${esc(S.enrollName)}</div>
    <h2>${n === 0 ? "Warm up on this line" : "Same line, your normal rhythm"}</h2>
    <p class="muted">Don't race. If you hit a wrong key, just press the right one.</p>
    <div class="dots" aria-label="Line ${n + 1} of ${cfg.rounds}">${dots}</div>
    ${typerHTML("It advances on its own")}
  </section>`;
}

function traitsHTML(p: Player): string {
  const flights = [...localBuildProfile(p.runs).entries()]
    .filter(([k]) => k[0] === "f")
    .sort((a, b) => a[1].mean - b[1].mean);
  const pair = (k: string): string => `${label(k[2]!)}${k[2] === " " || k[3] === " " ? " → " : ""}${label(k[3]!)}`;
  const holds = [...localBuildProfile(p.runs).entries()].filter(([k]) => k[0] === "h").map(([, s]) => s.mean);
  const wpm = Math.round(phrase().length / 5 / (usualDuration(p) / 60000));
  const tile = (t: string, b: string, s: string): string =>
    `<div class="trait"><span class="eyebrow">${t}</span><b>${b}</b><span class="small muted">${s}</span></div>`;
  const fast = flights[0]!;
  const slow = flights[flights.length - 1]!;
  return `<div class="traits">
    ${tile("Pace", `${wpm} wpm`, "on this line")}
    ${tile("Typical hold", `${Math.round(median(holds))} ms`, "per key")}
    ${tile("Fastest pair", pair(fast[0]), `${Math.round(fast[1].mean)} ms`)}
    ${tile("Slowest pair", pair(slow[0]), `${Math.round(slow[1].mean)} ms`)}
  </div>`;
}

function revealView(): string {
  const p = byId(S.justAdded!)!;
  return `<section class="split">
      <div class="ring">${ringSVG(p.notes, p.color, null, p.name)}</div>
      <div class="stack">
        <div class="eyebrow">${esc(p.name)}'s signature</div>
        <h1 style="font-size:clamp(34px,6vw,52px)">This is how you type.</h1>
        <p>Keys run clockwise from the top. The outer shape bulges where you pause, and the inner marks grow on keys you hold longer.</p>
        <div class="row"><button class="primary" id="to-room">Enter the room</button><button id="hear" data-id="${esc(p.id)}">Hear my rhythm</button></div>
      </div>
    </section>
    ${traitsHTML(p)}
    <div class="roll-box">${rollSVG(phrase(), [{ notes: p.notes, cls: "n-a" }])}</div>`;
}

function roomView(): string {
  const cards = S.players
    .map(
      (p) => `<article class="card">
      <h3>${esc(p.name)}</h3>
      <div class="ring">${ringSVG(p.notes, p.color, null, p.name)}</div>
      <div class="tag">${p.isBot ? "Simulated practice target" : `Limit ${DISPLAY_THRESHOLD.toFixed(2)}`}</div>
      <div class="row"><button class="primary" data-attack="${esc(p.id)}">Attack</button>${p.isBot ? "" : `<button data-self="${esc(p.id)}">Test me</button>`}</div>
    </article>`,
    )
    .join("");
  const add = `<article class="card add"><h3>${humans().length ? "Someone else wants in?" : "Add yourself"}</h3><p class="small muted">Everyone types the same line, so attacks are fair.</p><button class="primary" id="add-player">Add a player</button></article>`;
  return `<section class="stack">
      <div class="row" style="justify-content:space-between"><div class="stack" style="gap:4px"><h2>The room</h2><p class="muted">Line: <span style="font-family:var(--mono)">${phrase()}</span></p></div></div>
      <div class="players">${add}${cards}</div>
      <div class="row">
        <button class="quiet" id="new-party">${S.confirmNew ? "Erase everyone and start over" : "New party"}</button>
        ${S.confirmNew ? `<button class="quiet" id="cancel-new">Keep playing</button>` : ""}
      </div>
    </section>`;
}

function resultHTML(): string {
  const L = S.last;
  if (!L) return "";
  const { res, v, target } = L;
  const compare =
    res.distance !== null
      ? `<div class="split">
      <div class="ring">${ringSVG(target.notes, target.color, notesFromRun(L.run), target.name)}</div>
      <div class="stack">
        <div class="legend"><span><i class="swatch" style="background:var(--p${target.color})"></i>${esc(target.name)}</span><span><i class="swatch" style="background:var(--ink)"></i>This attempt (dashed)</span></div>
        <div class="gauge">${gaugeSVG(res.distance, target.isBot ? target.threshold! : DISPLAY_THRESHOLD)}</div>
        ${res.parts.length ? `<div class="stack" style="gap:6px"><h3>Biggest giveaways</h3><ul class="tells">${tellsHTML(res)}</ul></div>` : ""}
      </div>
    </div>`
      : "";
  return `<section class="result stack" id="result" aria-live="polite">
    <p class="verdict ${v.good ? "v-good" : "v-bad"}">${v.word}</p>
    <p>${v.text}</p>
    ${compare}
  </section>`;
}

function attackView(): string {
  const target = byId(S.target!)!;
  const typist = S.typingAs ? byId(S.typingAs) : undefined;
  const same = typist && typist.id === target.id;
  const opts = (sel: string | null, list: Player[]): string =>
    list.map((p) => `<option value="${esc(p.id)}"${sel === p.id ? " selected" : ""}>${esc(p.name)}</option>`).join("");
  const whoOpts = `<option value="">Guest</option>${opts(S.typingAs, humans())}`;
  const modeBtns = same
    ? `<div class="row"><button id="m-self" class="${S.mode === "self" ? "primary" : ""}">Prove it's you</button><button id="m-disguise" class="${S.mode === "disguise" ? "primary" : ""}">Wear a disguise</button></div>`
    : "";
  const title = same ? (S.mode === "disguise" ? "Fool your own signature" : "Prove it's you") : `Pass as ${esc(target.name)}`;
  const hint = same ? "Type the line" : "Match the pink bars on the roll";
  const replay = !same ? `<button class="quiet" id="replay">Watch a replay attack</button>` : "";
  return `<section class="stack">
      <h2>${title}</h2>
      <div class="row end">
        <label for="who">Who's typing?<select id="who">${whoOpts}</select></label>
        <label for="tgt">Target<select id="tgt">${opts(S.target, S.players)}</select></label>
        ${modeBtns}
      </div>
      ${typerHTML(hint, resultHTML(), replay)}
    </section>`;
}

function scoresView(): string {
  const counted = S.attempts.filter((a) => a.counted);
  const attacks = counted.filter((a) => a.mode === "attack");
  if (!counted.length) {
    return `<section class="stack"><h2>Scores</h2><p>No attempts yet. Attack someone in the room and this page fills in.</p><div class="row"><button class="primary" id="to-room">Go to the room</button></div></section>`;
  }
  const tally = (key: "who" | "target"): [string, { n: number; w: number }][] => {
    const m = new Map<string, { n: number; w: number }>();
    attacks.forEach((a) => {
      const k = a[key];
      const r = m.get(k) ?? { n: 0, w: 0 };
      r.n++;
      if (a.pass) r.w++;
      m.set(k, r);
    });
    return [...m.entries()];
  };
  const bestImp = tally("who").sort((a, b) => b[1].w / b[1].n - a[1].w / a[1].n)[0]!;
  const hardest = tally("target").sort((a, b) => a[1].w / a[1].n - b[1].w / b[1].n)[0]!;
  const closest = attacks.filter((a) => a.ratio !== null).sort((a, b) => a.ratio! - b.ratio!)[0];
  const tile = (t: string, b: string, s: string): string =>
    `<div class="trait"><span class="eyebrow">${t}</span><b>${b}</b><span class="small muted">${s}</span></div>`;
  const board = attacks.length
    ? `<div class="board">
    ${bestImp[1].w ? tile("Best impostor", esc(bestImp[0]), `${bestImp[1].w} of ${bestImp[1].n} attacks passed`) : tile("Best impostor", "Nobody yet", "No attack has passed")}
    ${tile("Hardest to copy", esc(hardest[0]), `${hardest[1].w} of ${hardest[1].n} attacks passed`)}
    ${closest ? tile("Closest call", `${closest.ratio!.toFixed(2)}×`, `${esc(closest.who)} as ${esc(closest.target)}, where 1× is the limit`) : ""}
  </div>`
    : "";
  const typists = [...new Set(attacks.map((a) => a.who))];
  const targets = S.players.filter((p) => attacks.some((a) => a.targetId === p.id));
  const matrix = attacks.length
    ? `<section class="stack"><h3>Who tried to be whom</h3><p class="small muted">Each cell is the attacker's closest attempt. Below 1× means they passed.</p><div class="table-box"><table><thead><tr><th>Typing ↓ / Target →</th>${targets.map((t) => `<th>${esc(t.name)}</th>`).join("")}</tr></thead><tbody>${typists
        .map(
          (w) =>
            `<tr><td>${esc(w)}</td>${targets
              .map((t) => {
                const r = attacks
                  .filter((a) => a.who === w && a.targetId === t.id && a.ratio !== null)
                  .map((a) => a.ratio!);
                if (!r.length) return `<td class="muted">–</td>`;
                const m = Math.min(...r);
                return `<td class="${m <= 1 ? "hit" : "safe"}">${m.toFixed(2)}×${m <= 1 ? " passed" : ""}</td>`;
              })
              .join("")}</tr>`,
        )
        .join("")}</tbody></table></div></section>`
    : "";
  const pts = counted.filter((a) => a.ratio !== null);
  const W = 760;
  const H = 260;
  const l = 44;
  const r = 14;
  const t = 14;
  const b = 38;
  const top = Math.max(2, Math.ceil(Math.max(...pts.map((a) => a.ratio!)) * 2) / 2);
  const X = (i: number): number => (pts.length === 1 ? (l + W - r) / 2 : l + (i / (pts.length - 1)) * (W - l - r));
  const Y = (v: number): number => t + (1 - v / top) * (H - t - b);
  let g = "";
  for (let v = 0; v <= top + 1e-9; v += top > 4 ? 1 : 0.5) {
    g += `<line class="c-axis" x1="${l}" x2="${W - r}" y1="${Y(v)}" y2="${Y(v)}"/><text class="c-text" x="${l - 6}" y="${Y(v) + 4}" text-anchor="end">${v}×</text>`;
  }
  g += `<line class="c-limit" x1="${l}" x2="${W - r}" y1="${Y(1)}" y2="${Y(1)}"/><text class="c-text" x="${W - r}" y="${Y(1) - 5}" text-anchor="end">limit</text>`;
  pts.forEach((a, i) => {
    const x = X(i);
    const y = Y(a.ratio!);
    const title = `<title>${esc(a.who)} as ${esc(a.target)}: ${a.ratio!.toFixed(2)}×, ${esc(a.word)}</title>`;
    if (a.mode === "replay") g += `<rect class="c-replay" x="${x - 5}" y="${y - 5}" width="10" height="10">${title}</rect>`;
    else if (a.mode === "attack") g += `<path class="c-attack" d="M${x} ${y - 7} L${x + 7} ${y + 5} L${x - 7} ${y + 5} Z">${title}</path>`;
    else g += `<circle class="c-own" cx="${x}" cy="${y}" r="5.5">${title}</circle>`;
  });
  g += `<text class="c-text" x="${(l + W - r) / 2}" y="${H - 8}" text-anchor="middle">attempts, oldest to newest</text>`;
  const chart = `<section class="stack"><h3>Every attempt against its limit</h3>
    <div class="legend"><span><svg width="14" height="14" style="vertical-align:-2px"><path class="c-attack" d="M7 1 L13 13 L1 13 Z"/></svg> Attack</span><span><svg width="14" height="14" style="vertical-align:-2px"><circle class="c-own" cx="7" cy="7" r="6"/></svg> Own typing</span><span><svg width="14" height="14" style="vertical-align:-2px"><rect class="c-replay" x="2" y="2" width="10" height="10"/></svg> Replay</span></div>
    <div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Chart of ${pts.length} attempts, each shown as distance relative to the target's limit.">${g}</svg></div></section>`;
  const rows = [...S.attempts]
    .reverse()
    .slice(0, 12)
    .map(
      (a) =>
        `<tr><td>${esc(a.who)}</td><td>${esc(a.target)}</td><td>${{ attack: "Attack", self: "Own typing", disguise: "Disguise", replay: "Replay" }[a.mode]}</td><td>${a.ratio === null ? "n/a" : `${a.ratio.toFixed(2)}×`}</td><td>${esc(a.word)}</td></tr>`,
    )
    .join("");
  return `<section class="stack"><h2>Scores</h2><p class="muted">From this party only. A few attempts make a fun scoreboard, not a measure of accuracy.</p></section>
    ${board}${chart}${matrix}
    <section class="stack"><h3>Latest attempts</h3><div class="table-box"><table><thead><tr><th>Typing</th><th>Target</th><th>Type</th><th>Distance</th><th>Result</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
}

function howView(): string {
  return `<section class="stack">
    <h2>How it works</h2>
    <p>The detector measures two things: how long each key is held, and the time from one key going down to the next. For a real player, this is scored by this app's own backend -- see <a href="/how-it-works">How It Works</a> for the actual method and its measured accuracy. For a simulated practice player, it's scored locally in your browser against made-up data.</p>
    <p>Every real player shares the same limit, ${DISPLAY_THRESHOLD.toFixed(2)} -- the app's own calibrated threshold. Simulated players each get their own limit, from testing their fake training lines against each other.</p>
    <p>Reading a signature: the shape is scaled to each typist's own median gap, so it shows their relative rhythm and not simply their speed. Signatures can look alike, and a distinctive shape doesn't prove anyone is unique.</p>
    <p>This is a game, not security. A few lines of typing aren't enough to protect anything, and a replay shows why rhythm can't be the only check.</p>
    <details><summary>What's real here</summary><div class="stack"><p class="small">Every real player's enrollment and every attempt against them is scored by this app's actual backend, under a random account created just for this party -- see the privacy note at the bottom of the page. The three sample players are simulated: made-up data, scored locally, never touching the backend.</p></div></details>
  </section>`;
}

function renderTabs(): void {
  const tabs = $("tabs");
  if (!tabs) return;
  if (!S.level || S.view === "enroll" || (S.view === "name" && !S.players.length)) {
    tabs.innerHTML = "";
    return;
  }
  const cur = S.view === "scores" ? "scores" : S.view === "how" ? "how" : "room";
  tabs.innerHTML = (
    [
      ["room", "Room"],
      ["scores", "Scores"],
      ["how", "How it works"],
    ] as const
  )
    .map(([k, l]) => `<button data-tab="${k}"${cur === k ? ' aria-current="page"' : ""}>${l}</button>`)
    .join("");
}

function render(): void {
  renderTabs();
  const views: Record<ViewName, () => string> = {
    intro: introView,
    name: nameView,
    enroll: enrollView,
    reveal: revealView,
    room: roomView,
    attack: attackView,
    scores: scoresView,
    how: howView,
  };
  const app = $("app");
  if (app) app.innerHTML = views[S.view]();
  if ($("typer")) drawTyper();
  if (S.view === "name") ($("player-name") as HTMLInputElement | null)?.focus();
}

function go(view: ViewName): void {
  S.replaying = 0;
  S.run = null;
  S.view = view;
  render();
}

function openAttack(targetId: string, mode: Mode): void {
  S.target = targetId;
  S.mode = mode;
  S.last = null;
  S.replaying = 0;
  S.view = "attack";
  render();
  startRun();
}

document.addEventListener("submit", (e) => {
  const form = e.target as HTMLElement;
  if (form.id !== "name-form") return;
  e.preventDefault();
  const input = $("player-name") as HTMLInputElement | null;
  const name = input?.value.trim();
  if (!name) return;
  const playerId = `${S.players.length}-${name}`;
  S.enrollName = name;
  S.enrollRuns = [];
  S.enrollingPlayerId = playerId;
  void registerAndLogin(playerId).catch(() => {
    /* Surfaced at the first addSample call instead. */
  });
  S.view = "enroll";
  render();
  startRun();
});

document.addEventListener("change", (e) => {
  const target = e.target as HTMLElement;
  if (target.id === "who" || target.id === "tgt") {
    const select = target as HTMLSelectElement;
    if (target.id === "who") S.typingAs = select.value || null;
    else S.target = select.value;
    const same = S.typingAs && S.typingAs === S.target;
    S.mode = same ? (S.mode === "disguise" ? "disguise" : "self") : "attack";
    S.last = null;
    S.replaying = 0;
    render();
    startRun();
  }
});

async function resetParty(): Promise<void> {
  // Best-effort: delete every real player's profile. Each delete
  // needs that player's own account to be the active session.
  for (const player of humans()) {
    try {
      await ensureActiveAccount(player.id);
      await deleteProfile();
    } catch {
      /* Best-effort cleanup -- these accounts are disposable either way. */
    }
  }
  if (activeAccountId !== null) {
    try {
      await logout();
    } catch {
      /* ignore */
    }
  }
  accounts.clear();
  activeAccountId = null;
  Object.assign(S, {
    view: "intro",
    level: null,
    players: [],
    attempts: [],
    typingAs: null,
    target: null,
    mode: "attack",
    enrollName: "",
    enrollRuns: [],
    enrollingPlayerId: null,
    run: null,
    last: null,
    replaying: 0,
    justAdded: null,
    confirmNew: false,
    nextColor: 0,
  });
  render();
}

document.addEventListener("click", (e) => {
  const eventTarget = e.target as HTMLElement;
  if (eventTarget.closest("#typer")) {
    $("typer")?.focus({ preventScroll: true });
    return;
  }
  const b = eventTarget.closest("button") as HTMLButtonElement | null;
  if (!b) return;
  if (b.id === "home") {
    if (S.level) go("room");
    return;
  }
  if (b.dataset.level) {
    S.level = b.dataset.level as LevelKey;
    addSamples();
    go("name");
    return;
  }
  if (b.dataset.tab) {
    go(b.dataset.tab as ViewName);
    return;
  }
  if (b.dataset.attack) {
    if (S.typingAs === b.dataset.attack) S.typingAs = null;
    openAttack(b.dataset.attack, "attack");
    return;
  }
  if (b.dataset.self) {
    S.typingAs = b.dataset.self;
    openAttack(b.dataset.self, "self");
    return;
  }
  if (b.id === "to-room") {
    go("room");
    return;
  }
  if (b.id === "add-player") {
    go("name");
    return;
  }
  if (b.id === "restart") {
    if (!S.replaying) startRun();
    return;
  }
  if (b.id === "replay") {
    runReplay();
    return;
  }
  if (b.id === "m-self") {
    S.mode = "self";
    S.last = null;
    render();
    startRun();
    return;
  }
  if (b.id === "m-disguise") {
    S.mode = "disguise";
    S.last = null;
    render();
    startRun();
    return;
  }
  if (b.id === "hear") {
    const id = b.dataset.id;
    if (id) {
      const p = byId(id);
      if (p) playNotes(p.notes);
    }
    return;
  }
  if (b.id === "cancel-new") {
    S.confirmNew = false;
    render();
    return;
  }
  if (b.id === "new-party") {
    if (!S.confirmNew) {
      S.confirmNew = true;
      render();
      return;
    }
    void resetParty();
  }
});

render();
