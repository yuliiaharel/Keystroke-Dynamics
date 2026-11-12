/**
 * Typing Twin Party: the anonymous, no-database party game
 * (docs/plans/done/PARTY_LAUNCH_PLAN.md Part 1), played in a room that
 * other browsers can join by its link
 * (docs/plans/active/ROOMS_PLAN.md Phase 3). Every score -- a real player's own
 * limit, a sample bot's, the permanent target's -- comes from the
 * backend's /api/game/* endpoints (api/game.py); nothing here
 * duplicates core/scoring.py. The only thing computed in the browser
 * is the three decorative sample rings shown before any party exists
 * (introRings/sampleRuns/medianNotesLocal below) -- pure drawing
 * data, never scored, never sent anywhere.
 *
 * Presentation (rings, piano rolls, sound, the party flow itself) is
 * unchanged from the approved mockup
 * (design/typing-twin-party.html). What's different from that file:
 * every real score is a round trip to the server instead of a local
 * calculation, and a signed session cookie -- not anything typed in
 * a form -- is what the server trusts to know which room this
 * browser is in, and which of its players are this browser's own.
 *
 * The page's URL is /r/<code> whenever a room is on screen, and the
 * home path otherwise. It only ever replaces the current history
 * entry: there's one screen here, not pages to go back through.
 */

import { analyticsPrivacyNote, startAnalytics } from "../analytics";
import * as gameApi from "../game-api";
import type { AttemptView, Level, Mode as ApiMode, NoteView, PartyView, PlayerView } from "../game-api";
import { KeystrokeCapture } from "../capture";
import { watchRoom } from "../live";
import type { LiveRoom } from "../live";
import { formatCode, joinFailure, roomCodeFromPath, roomLink, roomPath, sameCode } from "../room";
import type { CapturedEvent } from "../capture";
import { scoresMemoHTML } from "../scores-memo";
import { traitsFromNotes } from "../traits";
import type { PairTiming } from "../traits";

const LEVELS: Record<Level, { name: string; blurb: string; rounds: number }> = {
  sentence: { name: "A sentence", blurb: "The best party mode. About a minute each.", rounds: 5 },
  long: { name: "A long line", blurb: "More to measure, more to fake. About 2 minutes each.", rounds: 4 },
};
// Mirrors game/levels.py -- only used for the decorative intro rings,
// drawn before any party (and therefore any server-known phrase)
// exists. Every other view uses S.party.phrase, the server's own.
const INTRO_PHRASE = "quiet rhythm hides in every small habit of your hands";

const QWERTY = "qwertyuiopasdfghjklzxcvbnm ";
const label = (c: string): string => (c === " " ? "space" : c);
const esc = (s: string): string =>
  String(s).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!,
  );
const $ = (id: string): HTMLElement | null => document.getElementById(id);

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

type ViewName = "intro" | "name" | "enroll" | "reveal" | "room" | "attack" | "scores" | "how";

interface LastResult {
  run: Run;
  attempt: AttemptView;
  text: string;
  target: PlayerView;
  //: From the response's own `clue` (game/judge.py's _clue()) --
  //: not attempt.pace's sibling, since clue (like verdict_text) is
  //: this-response-only, never persisted history. Null exactly when
  //: attempt.distance is null ("Too messy").
  clue: string | null;
}

/** A full-page state for a room link that hasn't become a room on
 * screen: still opening, waiting for an answer to "leave your current
 * room?", or refused. (A link to a room that's gone uses partyGone,
 * the same page a room shows when it ends under you.) */
type Gate =
  | { kind: "opening" }
  | { kind: "switch"; code: string; current: PartyView }
  | { kind: "locked" | "full" | "rate-limited" | "failed"; code: string };

/** The one question the room view may be asking before it acts. */
type Confirm = { kind: "leave" | "new" | "lock" | "unlock" | "end" } | { kind: "remove"; playerId: string };

interface State {
  view: ViewName;
  level: Level | null;
  party: PartyView | null;
  typingAs: string | null;
  target: string | null;
  mode: ApiMode;
  enrollName: string;
  enrollRuns: Run[];
  run: Run | null;
  last: LastResult | null;
  replaying: number;
  justAddedId: string | null;
  confirm: Confirm | null;
  //: Set when the clipboard refused the room link, so it's shown to
  //: copy by hand instead.
  showLink: boolean;
  gate: Gate | null;
  partyGone: boolean;
  renamingId: string | null;
  busy: boolean;
  error: string | null;
}

/** A function, not a constant: enrollRuns must be a fresh array each time. */
function initialState(): State {
  return {
    view: "intro",
    level: null,
    party: null,
    typingAs: null,
    target: null,
    mode: "attack",
    enrollName: "",
    enrollRuns: [],
    run: null,
    last: null,
    replaying: 0,
    justAddedId: null,
    confirm: null,
    showLink: false,
    gate: null,
    partyGone: false,
    renamingId: null,
    busy: false,
    error: null,
  };
}

const S: State = initialState();

const phrase = (): string => S.party?.phrase ?? "";
const lanes = (p: string): string[] => [...QWERTY].filter((c) => p.includes(c));
const allEntities = (): PlayerView[] => (S.party ? [...S.party.players, ...S.party.targets] : []);
const byId = (id: string): PlayerView | undefined => allEntities().find((p) => p.id === id);
const humans = (): PlayerView[] => S.party?.players ?? [];
/** Enrolled on this browser. Only these can be typed as, renamed, or
 * deleted from here; the server enforces it, this just doesn't offer
 * what would be refused. */
const mine = (p: PlayerView): boolean => p.owner_member_id !== null && p.owner_member_id === S.party?.member_id;
const myPlayers = (): PlayerView[] => humans().filter(mine);

/** Phone keyboards don't report when each key goes down and up, so a
 * phone can join a room and watch, but not type
 * (docs/plans/active/MOBILE_PLAN.md is what changes that). */
const onPhone = (): boolean => window.matchMedia?.("(pointer: coarse)").matches ?? false;

/** Where the game lives when no room is on screen: "/" in public
 * mode, "/party" beside the account pages (api/pages.py's PARTY_PATH). */
const HOME_PATH = document.body.dataset.home ?? "/";

function showUrl(path: string): void {
  if (location.pathname !== path) history.replaceState(null, "", path);
}

function median(a: number[]): number {
  const s = [...a].sort((x, y) => x - y);
  return s.length ? s[Math.floor(s.length / 2)]! : 0;
}

/* ---------- Capture ---------- */

const capture = new KeystrokeCapture();

function notesFromRun(run: Run): NoteView[] {
  const t0 = run.keys.length ? run.keys[0]!.down : 0;
  return run.keys.map((r) => ({
    ch: r.ch,
    start_ms: r.down - t0,
    dur_ms: r.up !== null ? r.up - r.down : 70,
  }));
}

function usualDurationMs(p: PlayerView): number {
  const last = p.notes[p.notes.length - 1];
  return last ? last.start_ms + last.dur_ms : 0;
}

/* ---------- Decorative sample rings (intro only -- see module docstring) ---------- */

function hashSeed(s: string): number {
  let h = 2166136261;
  for (const c of s) {
    h ^= c.charCodeAt(0);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h;
}

function decorativeNotes(text: string, seed: string, speed: number, count: number): NoteView[] {
  let state = (hashSeed(seed) % 2147483646) + 1;
  const rnd = (): number => (state = (state * 16807) % 2147483647) / 2147483647;
  const unit = (key: string): number => (hashSeed(`${seed}|${key}`) % 1000) / 1000;
  const runs: { ch: string; down: number; up: number }[][] = [];
  for (let r = 0; r < count; r++) {
    let t = 0;
    const keys: { ch: string; down: number; up: number }[] = [];
    [...text].forEach((ch, i) => {
      if (i > 0) t += speed * (70 + 170 * unit(text[i - 1]! + ch)) * (0.9 + rnd() * 0.2);
      const hold = (55 + 60 * unit(ch)) * (0.9 + rnd() * 0.2);
      keys.push({ ch, down: t, up: t + hold });
    });
    runs.push(keys);
  }
  const len = runs[0]!.length;
  let t = 0;
  const notes: NoteView[] = [];
  for (let i = 0; i < len; i++) {
    if (i > 0) t += median(runs.map((r) => r[i]!.down - r[i - 1]!.down));
    notes.push({ ch: runs[0]![i]!.ch, start_ms: t, dur_ms: median(runs.map((r) => r[i]!.up - r[i]!.down)) });
  }
  return notes;
}

const INTRO_SAMPLES: [string, number][] = [
  ["Quick Fingers", 0.72],
  ["Steady Hands", 1.05],
  ["Two-Finger Typist", 1.4],
];

/* ---------- Signature ring (verbatim from the mockup) ---------- */

interface RingPoint {
  x: number;
  y: number;
  a: number;
  h: number;
}

function ringPoints(notes: NoteView[]): RingPoint[] {
  const gaps = notes.map((n, i) => (i === 0 ? null : n.start_ms - notes[i - 1]!.start_ms));
  const med = median(gaps.filter((g): g is number => g !== null)) || 1;
  const holdMed = median(notes.map((n) => n.dur_ms)) || 1;
  const N = notes.length;
  const cx = 120;
  const cy = 120;
  const base = 44;
  const scale = 40;
  return notes.map((n, i) => {
    const g = gaps[i] === null ? 1 : Math.min(2.6, gaps[i]! / med);
    const a = -Math.PI / 2 + (i / N) * Math.PI * 2;
    const r = base + g * scale;
    const h = Math.min(2.2, n.dur_ms / holdMed);
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

function ringSVG(notes: NoteView[], color: number, compareNotes: NoteView[] | null, name?: string): string {
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

/* ---------- Roll (verbatim from the mockup) ---------- */

function rollSVG(text: string, layers: { notes: NoteView[]; cls: string; inset?: boolean }[], minEnd?: number): string {
  const L_ = lanes(text);
  const W = 760;
  const L = 44;
  const top = 16;
  const laneH = 13;
  const H = top + L_.length * laneH + 28;
  const end = Math.max(minEnd ?? 0, 1000, ...layers.flatMap((l) => l.notes.map((n) => n.start_ms + n.dur_ms))) * 1.03;
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
      g += `<rect class="${l.cls}" x="${x(n.start_ms).toFixed(1)}" y="${y}" width="${Math.max(3, x(n.start_ms + n.dur_ms) - x(n.start_ms)).toFixed(1)}" height="${h}" rx="2"/>`;
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

function showError(message: string): void {
  S.error = message;
  render();
}

async function finishRun(): Promise<void> {
  const run = S.run;
  if (!run) return;

  if (S.view === "enroll") {
    S.enrollRuns.push(run);
    const cfg = LEVELS[S.level!];
    const isWarmup = S.enrollRuns.length === 1;

    // The warm-up line isn't kept as training data -- same rule as
    // the account-based version and the approved mockup. Each kept
    // run's own capture.sample() must be read now, before the next
    // startRun() calls capture.reset() and discards it.
    if (!isWarmup) {
      enrollSamples.push(capture.sample());
    }

    if (S.enrollRuns.length === cfg.rounds) {
      S.busy = true;
      render();
      try {
        const player = await gameApi.createPlayer(S.enrollName || null, enrollSamples);
        S.enrollRuns = [];
        enrollSamples.length = 0;
        S.typingAs = player.id;
        S.justAddedId = player.id;
        S.run = null;
        S.view = "reveal";
        await refreshParty();
      } catch (error) {
        S.busy = false;
        if (gameApi.isRoomGone(error)) {
          S.partyGone = true;
          render();
          return;
        }
        showError("Couldn't save your enrollment. Press Esc to try the current line again.");
        return;
      }
      S.busy = false;
      render();
      return;
    }
    render();
    startRun();
    return;
  }

  await submitRunAsAttempt(run);
  render();
  startRun();
}

//: Per-line CapturedEvent[] collected during enrollment, in parallel
//: with S.enrollRuns (which keeps the richer Run shape for the
//: reveal view's local-only traits display). Cleared on submit or
//: reset -- never kept beyond this one enrollment.
const enrollSamples: CapturedEvent[][] = [];

async function submitRunAsAttempt(run: Run): Promise<void> {
  const target = byId(S.target!);
  if (!target) return;
  const mode = S.mode === "replay" ? "attack" : S.mode;
  try {
    const resp = await gameApi.submitAttempt({
      typistId: S.typingAs,
      targetId: target.id,
      mode,
      events: capture.sample(),
      clientAttemptId: crypto.randomUUID(),
    });
    S.last = {
      run,
      attempt: resp.attempt,
      text: resp.verdict_text,
      target,
      clue: resp.clue,
    };
    await refreshParty();
  } catch (error) {
    if (gameApi.isRoomGone(error)) {
      S.partyGone = true;
      return;
    }
    showError("Couldn't reach the server to score that attempt. Press Esc to try again.");
  }
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
    const layers: { notes: NoteView[]; cls: string; inset?: boolean }[] = [];
    if (target && S.mode === "attack") layers.push({ notes: target.notes, cls: "n-ghost" });
    layers.push({
      notes: notesFromRun(r),
      cls: target ? "n-b" : "n-a",
      inset: !!target && S.mode === "attack",
    });
    live.innerHTML = rollSVG(text, layers, target ? usualDurationMs(target) : 0);
  }
}

function typerHTML(hint: string, between?: string, extra?: string): string {
  if (onPhone()) {
    // The line and the roll still show (a replay draws on both), but
    // there's nothing to focus and nothing listens for keys.
    return `<div class="typer" style="cursor:default">
    <div class="phrase" id="phrase"></div>
    <div class="typer-foot"><span class="blur-note">Join from a computer to play</span></div>
  </div>
  ${extra ? `<div class="row">${extra}</div>` : ""}
  ${between ?? ""}
  <div class="roll-box" id="live-roll"></div>`;
  }
  return `<div class="typer" id="typer" tabindex="0" role="textbox" aria-label="Typing area. Type this line: ${phrase()}">
    <div class="phrase" id="phrase"></div>
    <div class="typer-foot"><span class="blur-note">Click here to type</span><span>${hint}</span><span id="typos"></span></div>
  </div>
  <div class="row"><button class="quiet" id="restart">Restart line (Esc)</button>${extra ?? ""}</div>
  <p class="error" id="run-error" hidden></p>
  ${between ?? ""}
  <div class="roll-box" id="live-roll"></div>`;
}

/* ---------- Sound (unchanged from the mockup) ---------- */

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

function playNotes(notes: NoteView[]): void {
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
      const a = t0 + n.start_ms / 1000;
      const b = a + Math.max(0.08, n.dur_ms / 1000);
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

/* ---------- Replay: server-driven, animated from its response's notes ---------- */

async function runReplay(): Promise<void> {
  const target = byId(S.target!);
  if (!target) return;
  const token = ++S.replaying;
  S.mode = "replay";
  S.last = null;
  S.busy = true;
  render();

  let resp;
  try {
    resp = await gameApi.submitReplay(target.id);
  } catch (error) {
    S.busy = false;
    S.mode = "attack";
    if (gameApi.isRoomGone(error)) {
      S.partyGone = true;
    } else {
      showError("Couldn't reach the server to run the replay.");
    }
    render();
    return;
  }
  S.busy = false;

  const notes = resp.notes;
  S.run = { idx: 0, keys: [], errors: 0, pendingError: false, held: {}, finished: true };
  const t0 = notes.length ? notes[0]!.start_ms : 0;
  notes.forEach((n, i) =>
    setTimeout(
      () => {
        if (S.replaying !== token || S.view !== "attack") return;
        S.run!.keys.push({ ch: n.ch, down: n.start_ms - t0, up: n.start_ms + n.dur_ms - t0, afterError: false });
        S.run!.idx = i + 1;
        drawTyper();
        if (i === notes.length - 1) {
          setTimeout(() => {
            if (S.replaying !== token || S.view !== "attack") return;
            S.last = {
              run: S.run!,
              attempt: resp.attempt,
              text: resp.verdict_text,
              target,
              clue: resp.clue,
            };
            if (resp.attempt.counted) {
              buzz(resp.attempt.mode === "replay" && resp.attempt.passed === true);
            }
            S.replaying = 0;
            S.mode = "attack";
            void refreshParty();
            render();
            startRun();
          }, 300);
        }
      },
      n.start_ms - t0,
    ),
  );
}

/* ---------- Server round trips ---------- */

async function refreshParty(): Promise<void> {
  try {
    S.party = await gameApi.getRoom();
  } catch (error) {
    if (gameApi.isRoomGone(error)) {
      S.partyGone = true;
    }
  }
}

/* ---------- Live updates (docs/plans/active/ROOMS_PLAN.md Phase 2) ---------- */

let live: LiveRoom | null = null;

function stopLive(): void {
  live?.stop();
  live = null;
}

/** Call whenever this browser has just got itself a room. */
function startLive(): void {
  stopLive();
  live = watchRoom<PartyView>({
    fetchRoom: gameApi.getRoom,
    currentVersion: () => S.party?.version ?? null,
    isGone: gameApi.isRoomGone,
    onRoom: (party) => {
      S.party = party;
      // The host can remove a player from under the browser that was
      // typing as them, or under the question about removing them.
      if (S.typingAs !== null && !byId(S.typingAs)) S.typingAs = null;
      if (S.confirm?.kind === "remove" && !byId(S.confirm.playerId)) S.confirm = null;
      // Only the two views that are nothing but the shared room are
      // redrawn under the person looking at them. Anywhere else
      // (typing a line, a name, a rename) a redraw would interrupt
      // them; those views read S.party the next time they draw.
      const showsOnlyTheRoom = S.view === "room" || S.view === "scores";
      if (showsOnlyTheRoom && S.renamingId === null && !S.busy) render();
    },
    onGone: () => {
      live = null;
      S.partyGone = true;
      render();
    },
  });
}

function resetState(): void {
  stopLive();
  Object.assign(S, initialState());
  enrollSamples.length = 0;
}

/** Puts a room this browser belongs to on screen, at its own URL. */
function enterRoom(party: PartyView, view: ViewName): void {
  S.party = party;
  S.level = party.level;
  S.partyGone = false;
  S.gate = null;
  S.view = view;
  showUrl(roomPath(party.code));
  startLive();
}

/** The first thing a browser new to a room sees: the name step, or
 * the room itself where it can't type. */
const firstView = (): ViewName => (onPhone() ? "room" : "name");

async function startRoom(level: Level): Promise<void> {
  S.busy = true;
  S.error = null;
  render();
  try {
    // The server takes this browser out of any room it was in, once
    // the new one exists.
    const party = await gameApi.createRoom(level);
    resetState();
    enterRoom(party, firstView());
  } catch {
    S.confirm = null;
    S.error = "Couldn't start a room right now. Try again in a moment.";
  }
  S.busy = false;
  render();
}

/** Opening /r/<code>: straight into the room for a browser that's
 * already in it, a question first for one that's in a different
 * room, and a join for everyone else. */
async function openRoomLink(code: string): Promise<void> {
  S.gate = { kind: "opening" };
  render();
  let current: PartyView | null = null;
  try {
    current = await gameApi.getRoom();
  } catch (error) {
    if (!gameApi.isRoomGone(error)) {
      S.gate = { kind: "failed", code };
      render();
      return;
    }
  }
  if (current && sameCode(current.code, code)) {
    enterRoom(current, "room");
    render();
    return;
  }
  if (current) {
    S.gate = { kind: "switch", code, current };
    render();
    return;
  }
  await joinByLink(code, false);
}

async function joinByLink(code: string, leaveCurrent: boolean): Promise<void> {
  S.gate = { kind: "opening" };
  render();
  try {
    const party = await gameApi.joinRoom(code, leaveCurrent);
    resetState();
    enterRoom(party, firstView());
  } catch (error) {
    const failure = joinFailure(gameApi.errorStatus(error));
    if (failure === "gone") {
      S.gate = null;
      S.partyGone = true;
    } else {
      S.gate = { kind: failure, code };
    }
  }
  render();
}

/** Leaving and ending both finish at the start page. `request` is
 * whichever of the two the server should carry out. */
async function closeRoom(request: () => Promise<void>, failure: string): Promise<void> {
  try {
    await request();
  } catch (error) {
    // Already gone is as good as done. Anything else, the room is
    // still there and this browser is still in it.
    if (!gameApi.isRoomGone(error)) {
      S.confirm = null;
      showError(failure);
      return;
    }
  }
  resetState();
  showUrl(HOME_PATH);
  render();
}

async function doLockRoom(locked: boolean): Promise<void> {
  S.confirm = null;
  try {
    S.party = await gameApi.lockRoom(locked);
  } catch (error) {
    if (gameApi.isRoomGone(error)) S.partyGone = true;
    else S.error = locked ? "Couldn't lock the room. Try again." : "Couldn't unlock the room. Try again.";
  }
  render();
}

async function copyRoomLink(button: HTMLButtonElement): Promise<void> {
  if (!S.party) return;
  try {
    await navigator.clipboard.writeText(roomLink(location.origin, S.party.code));
    button.textContent = "Link copied";
    setTimeout(() => {
      if (button.isConnected) button.textContent = "Copy link";
    }, 2000);
  } catch {
    // No clipboard here (an older browser, or permission refused):
    // show the link to copy by hand.
    S.showLink = true;
    render();
    ($("room-link") as HTMLInputElement | null)?.select();
  }
}

function answerConfirm(): void {
  const c = S.confirm;
  if (!c) return;
  if (c.kind === "remove") {
    S.confirm = null;
    void doDeletePlayer(c.playerId);
  } else if (c.kind === "lock" || c.kind === "unlock") {
    void doLockRoom(c.kind === "lock");
  } else if (c.kind === "leave") {
    void closeRoom(gameApi.leaveRoom, "Couldn't leave the room. Try again.");
  } else if (c.kind === "end") {
    void closeRoom(gameApi.endRoom, "Couldn't end the room. Try again.");
  } else if (S.level) {
    void startRoom(S.level);
  }
}

async function doDeletePlayer(id: string): Promise<void> {
  try {
    await gameApi.deletePlayer(id);
    if (S.typingAs === id) S.typingAs = null;
    await refreshParty();
  } catch (error) {
    if (gameApi.isRoomGone(error)) S.partyGone = true;
    else S.error = "Couldn't remove that player. Try again.";
  }
  render();
}

async function doRenamePlayer(id: string, name: string): Promise<void> {
  try {
    await gameApi.renamePlayer(id, name);
    S.renamingId = null;
    await refreshParty();
  } catch (error) {
    if (gameApi.isRoomGone(error)) {
      S.partyGone = true;
    } else {
      S.error = "That name didn't work -- try a different one.";
    }
  }
  render();
}

/* ---------- Views ---------- */

function introView(): string {
  const rings = INTRO_SAMPLES.map(
    ([n, sp], i) => `<div class="ring">${ringSVG(decorativeNotes(INTRO_PHRASE, n, sp!, 6), i, null, n)}</div>`,
  ).join("");
  const coarse = onPhone();
  return `<section class="hero">
      <div class="stack">
        <h1>Everyone types in their own shape.</h1>
        <p>Type a line a few times and see your rhythm drawn as a signature -- scored for real by this app's own backend. Then share your room's link, or gather some friends around one keyboard, and try to pass as each other.</p>
        ${coarse ? `<div class="notice">Best on a computer. Phone keyboards don't report when each key goes down and up -- you can still look around and watch a replay attack without typing.</div>` : ""}
        <div class="row">
          <button class="primary" data-level="sentence">Start a party</button>
        </div>
        <button class="quiet" data-level="long" style="align-self:flex-start">Want a challenge? Try a long line</button>
        ${S.error ? `<p class="error">${esc(S.error)}</p>` : ""}
      </div>
      <div class="stack">
        <div class="hero-rings">${rings}</div>
        <p class="small muted">Example signatures from simulated typists. Yours will be made from your real timing.</p>
      </div>
    </section>`;
}

function nameView(): string {
  if (onPhone()) {
    return `<section class="stack" style="max-width:560px">
    <div class="eyebrow">New player</div>
    <h2>Join from a computer to play</h2>
    <p class="muted">Phone keyboards don't report when each key goes down and up, so a signature can't be made here. You can still watch the room and its scores, and run a replay attack.</p>
    <div class="row"><button class="primary" id="to-room">See the room</button></div>
  </section>`;
  }
  return `<section class="stack" style="max-width:560px">
    <div class="eyebrow">New player</div>
    <h2>Who's typing?</h2>
    <p class="muted">You'll type the line ${LEVELS[S.level!].rounds} times. The first one is a warm-up. Keep the suggested name, type your own, or shuffle for another.</p>
    <form id="name-form" class="stack">
      <div class="row end">
        <label for="player-name">Your name<input id="player-name" maxlength="24" autocomplete="off"></label>
        <button type="button" class="quiet" id="shuffle-name" title="Pick another name">Shuffle</button>
        <button class="primary" type="submit">Start typing</button>
      </div>
    </form>
    ${scoresMemoHTML(S.party?.scores_enabled ?? false)}
    ${humans().length ? `<button class="quiet" id="to-room" style="align-self:flex-start">Skip and see the room</button>` : ""}
  </section>`;
}

//: The name the name field was last pre-filled with, so that focusing
//: the field selects a suggestion but never a name the person typed.
let suggestedName = "";
//: Counts suggestName calls, so an answer that arrives after a newer
//: request (two quick shuffles) is dropped.
let suggestionRequests = 0;

/** Puts a generated name in the name field. The first suggestion on
 * arriving at the step (`replace` false) never overwrites what the
 * person has already typed or cleared; a shuffle always replaces. */
async function suggestName(replace: boolean): Promise<void> {
  if (!$("player-name")) return;
  const request = ++suggestionRequests;
  let name: string;
  try {
    name = await gameApi.suggestName();
  } catch {
    // Deliberately quiet: the field keeps what it has, and a name
    // left blank is still generated by the server on enrollment.
    return;
  }
  // Looked up again: the view may have been redrawn, or left, meanwhile.
  const input = $("player-name") as HTMLInputElement | null;
  if (!input || request !== suggestionRequests) return;
  if (!replace && (input.value !== "" || input.dataset.edited)) return;
  suggestedName = name;
  input.value = name;
  if (replace) input.focus();
  if (document.activeElement === input) input.select();
}

function enrollView(): string {
  const n = S.enrollRuns.length;
  const cfg = LEVELS[S.level!];
  const dots = Array.from(
    { length: cfg.rounds },
    (_, i) => `<span class="dot ${i < n ? "ok" : i === n ? "on" : ""}">${i === 0 ? "Warm-up" : i}</span>`,
  ).join("");
  return `<section class="stack">
    <div class="eyebrow">${esc(S.enrollName || "New player")}</div>
    <h2>${n === 0 ? "Warm up on this line" : "Same line, your normal rhythm"}</h2>
    <p class="muted">Don't race. If you hit a wrong key, just press the right one.</p>
    <div class="dots" aria-label="Line ${n + 1} of ${cfg.rounds}">${dots}</div>
    ${S.busy ? `<p class="muted">Saving...</p>` : typerHTML("It advances on its own")}
    ${S.error ? `<p class="error">${esc(S.error)}</p>` : ""}
  </section>`;
}

/** A dash stands in for any stat the player's notes can't support. */
function traitsHTML(p: PlayerView): string {
  const t = traitsFromNotes(p.notes);
  const pairLabel = (pair: string): string => `${label(pair[0]!)} → ${label(pair[1]!)}`;
  const tile = (title: string, big: string, small: string): string =>
    `<div class="trait"><span class="eyebrow">${title}</span><b>${big}</b><span class="small muted">${small}</span></div>`;
  const pairTile = (title: string, timing: PairTiming | null): string =>
    timing
      ? tile(title, pairLabel(timing.pair), `${Math.round(timing.gapMs)} ms`)
      : tile(title, "–", "between keys");
  return `<div class="traits">
    ${tile("Pace", t.wpm === null ? "–" : `${t.wpm} wpm`, "on this line")}
    ${tile("Typical hold", t.typicalHoldMs === null ? "–" : `${t.typicalHoldMs} ms`, "per key")}
    ${pairTile("Fastest pair", t.fastest)}
    ${pairTile("Slowest pair", t.slowest)}
  </div>`;
}

function revealView(): string {
  const p = byId(S.justAddedId!)!;
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

function targetTag(p: PlayerView): string {
  if (p.kind === "sample") return "Simulated practice target";
  if (p.kind === "target") return "A real recorded signature";
  return `Limit ${p.threshold.toFixed(2)}`;
}

function attackButtonLabel(p: PlayerView): string {
  return p.kind === "target" ? `Can you pass as ${esc(p.name)}?` : "Attack";
}

function confirmHTML(): string {
  const c = S.confirm;
  if (!c) return "";
  const alone = S.party?.member_count === 1;
  const mineLeave = myPlayers().length ? " Your players leave with you." : "";
  const [question, yes, no]: [string, string, string] =
    c.kind === "remove"
      ? [`Remove ${esc(byId(c.playerId)?.name ?? "this player")} from the room?`, "Remove", "Cancel"]
      : c.kind === "lock"
        ? ["Lock the room? Nobody new can join with the link until you unlock it.", "Lock room", "Cancel"]
        : c.kind === "unlock"
          ? ["Unlock the room? Anyone with the link can join again.", "Unlock room", "Cancel"]
          : c.kind === "end"
            ? ["End the room for everyone? Every player, signature, and score in it is erased.", "End room", "Cancel"]
            : c.kind === "leave"
              ? [
                  alone
                    ? "Leave this room? You're the only one here, so the room ends."
                    : `Leave this room?${mineLeave}`,
                  "Leave room",
                  "Stay",
                ]
              : [
                  alone
                    ? "Start a new room? You're the only one here, so this room ends."
                    : `Leave this room and start a new one?${mineLeave}`,
                  "Start a new room",
                  "Stay",
                ];
  return `<div class="notice stack" id="confirm" role="group" aria-label="Confirm">
      <p>${question}</p>
      <div class="row"><button class="primary" id="confirm-yes">${yes}</button><button class="quiet" id="confirm-no">${no}</button></div>
    </div>`;
}

function playerCardHTML(p: PlayerView): string {
  const own = mine(p);
  const renameForm =
    S.renamingId === p.id
      ? `<form class="row" data-rename-form="${esc(p.id)}">
           <input name="name" maxlength="24" value="${esc(p.name)}" autocomplete="off">
           <button class="quiet" type="submit">Save</button>
         </form>`
      : "";
  // Rename and delete are the owner's. The host can remove anyone's
  // player, after being asked.
  const controls =
    p.kind !== "player"
      ? ""
      : own
        ? `<button class="quiet" data-rename="${esc(p.id)}">Rename</button><button class="quiet" data-delete="${esc(p.id)}">Delete me</button>`
        : S.party?.is_host
          ? `<button class="quiet" data-remove="${esc(p.id)}">Remove</button>`
          : "";
  const keyboard =
    p.kind === "player" ? `<div class="tag" data-keyboard>${own ? "On this keyboard" : "On another keyboard"}</div>` : "";
  const removing = S.confirm?.kind === "remove" && S.confirm.playerId === p.id;
  return `<article class="card">
      <h3>${esc(p.name)}</h3>
      <div class="ring">${ringSVG(p.notes, p.color, null, p.name)}</div>
      <div class="tag">${targetTag(p)}</div>
      ${keyboard}
      <div class="row"><button class="primary" data-attack="${esc(p.id)}">${attackButtonLabel(p)}</button>${own ? `<button data-self="${esc(p.id)}">Test me</button>` : ""}</div>
      <div class="row">${controls}</div>
      ${renameForm}
      ${removing ? confirmHTML() : ""}
    </article>`;
}

function roomHeaderHTML(party: PartyView): string {
  return `<div class="room-head">
        <div class="stack" style="gap:4px"><h2>The room</h2><p class="muted">Line: <span style="font-family:var(--mono)">${phrase()}</span></p></div>
        <div class="stack" style="gap:4px">
          <span class="eyebrow">Room code${party.locked ? " · locked" : ""}</span>
          <div class="row"><b class="room-code" id="room-code">${esc(formatCode(party.code))}</b><button id="copy-link">Copy link</button></div>
        </div>
      </div>
      ${S.showLink ? `<label for="room-link">Copy this link<input id="room-link" readonly value="${esc(roomLink(location.origin, party.code))}"></label>` : ""}
      <p class="small muted" id="room-note">Anyone with this link can join and see names and signatures.${party.locked ? " The room is locked, so nobody new can join right now." : ""}</p>`;
}

function roomView(): string {
  const party = S.party;
  if (!party) return "";
  const cards = [...humans(), ...party.targets].map(playerCardHTML).join("");
  const add = `<article class="card add"><h3>${myPlayers().length ? "Someone else wants in?" : "Add yourself"}</h3><p class="small muted">Everyone types the same line, so attacks are fair.</p><button class="primary" id="add-player">Add a player</button></article>`;
  const hostControls = party.is_host
    ? `<button class="quiet" id="lock-room">${party.locked ? "Unlock room" : "Lock room"}</button><button class="quiet" id="end-room">End room for everyone</button>`
    : "";
  return `<section class="stack">
      ${roomHeaderHTML(party)}
      ${onPhone() ? `<div class="notice">Join from a computer to play. Here you can watch the room and run a replay attack.</div>` : ""}
      <div class="players">${add}${cards}</div>
      ${S.error ? `<p class="error">${esc(S.error)}</p>` : ""}
      <div class="row">
        <button class="quiet" id="leave-room">Leave room</button>
        <button class="quiet" id="new-room">New room</button>
        ${hostControls}
      </div>
      ${S.confirm && S.confirm.kind !== "remove" ? confirmHTML() : ""}
    </section>`;
}

function resultHTML(): string {
  const L = S.last;
  if (!L) return "";
  const { attempt, text, target, clue } = L;
  const good = attempt.mode === "attack" ? attempt.passed === false : attempt.passed === true;
  // Pace and a one-line clue, shown on every scoreable result
  // (docs/plans/done/PARTY_LAUNCH_PLAN.md section 8, following
  // design/typing-twin-touch.html) -- hidden together with the
  // distance gauge below on a "Too messy" result, where
  // attempt.distance/pace and clue are all null: there's no honest
  // clue to give about a line that broke up before it could be
  // scored at all.
  const details =
    attempt.distance !== null && attempt.pace !== null
      ? `<h3 id="clue">${esc(clue ?? "")}</h3>
    <div class="trait"><span class="eyebrow">Pace</span><b>${attempt.pace.toFixed(2)}&times;</b><span class="small muted">${esc(target.name)}'s usual time, where 1&times; is the same speed</span></div>
    <div class="split">
      <div class="ring">${ringSVG(target.notes, target.color, notesFromRun(L.run), target.name)}</div>
      <div class="stack">
        <div class="legend"><span><i class="swatch" style="background:var(--p${target.color})"></i>${esc(target.name)}</span><span><i class="swatch" style="background:var(--ink)"></i>This attempt (dashed)</span></div>
        <div class="gauge">${gaugeSVG(attempt.distance, attempt.threshold)}</div>
      </div>
    </div>`
      : "";
  const keyboardNote =
    attempt.same_keyboard === false
      ? `<p class="small muted" id="keyboard-note">Different keyboard: this wasn't typed on the keyboard ${esc(target.name)} enrolled on, which can change timing.</p>`
      : "";
  return `<section class="result stack" id="result" aria-live="polite">
    <p class="verdict ${good ? "v-good" : "v-bad"}">${esc(attempt.word)}</p>
    <p>${esc(text)}</p>
    ${keyboardNote}
    ${details}
  </section>`;
}

function attackView(): string {
  const target = byId(S.target!);
  if (!target) return roomView();
  const typist = S.typingAs ? byId(S.typingAs) : undefined;
  const same = typist && typist.id === target.id;
  const opts = (sel: string | null, list: PlayerView[]): string =>
    list.map((p) => `<option value="${esc(p.id)}"${sel === p.id ? " selected" : ""}>${esc(p.name)}</option>`).join("");
  // Only this browser's own players: the server refuses anyone else's.
  const whoOpts = `<option value="">Guest</option>${opts(S.typingAs, myPlayers())}`;
  const modeBtns = same
    ? `<div class="row"><button id="m-self" class="${S.mode === "self" ? "primary" : ""}">Prove it's you</button><button id="m-disguise" class="${S.mode === "disguise" ? "primary" : ""}">Wear a disguise</button></div>`
    : "";
  const title = same ? (S.mode === "disguise" ? "Fool your own signature" : "Prove it's you") : `Pass as ${esc(target.name)}`;
  const hint = same ? "Type the line" : "Match the pink bars on the roll";
  const replay = !same ? `<button class="quiet" id="replay" ${S.busy ? "disabled" : ""}>Watch a replay attack</button>` : "";
  return `<section class="stack">
      <h2>${title}</h2>
      <div class="row end">
        <label for="who">Who's typing?<select id="who">${whoOpts}</select></label>
        <label for="tgt">Target<select id="tgt">${opts(S.target, [...humans(), ...(S.party?.targets ?? [])])}</select></label>
        ${modeBtns}
      </div>
      ${typerHTML(hint, resultHTML(), replay)}
      ${S.error ? `<p class="error">${esc(S.error)}</p>` : ""}
      ${scoresMemoHTML(S.party?.scores_enabled ?? false)}
    </section>`;
}

function scoresView(): string {
  const attempts = S.party?.attempts ?? [];
  const counted = attempts.filter((a) => a.counted);
  const attacks = counted.filter((a) => a.mode === "attack");
  if (!counted.length) {
    return `<section class="stack"><h2>Scores</h2><p>No attempts yet. Attack someone in the room and this page fills in.</p><div class="row"><button class="primary" id="to-room">Go to the room</button></div></section>`;
  }
  const tally = (key: "typist_name" | "target_name"): [string, { n: number; w: number }][] => {
    const m = new Map<string, { n: number; w: number }>();
    attacks.forEach((a) => {
      const k = a[key];
      const r = m.get(k) ?? { n: 0, w: 0 };
      r.n++;
      if (a.passed) r.w++;
      m.set(k, r);
    });
    return [...m.entries()];
  };
  const bestImp = tally("typist_name").sort((a, b) => b[1].w / b[1].n - a[1].w / a[1].n)[0];
  const hardest = tally("target_name").sort((a, b) => a[1].w / a[1].n - b[1].w / b[1].n)[0];
  const closest = attacks.filter((a) => a.ratio !== null).sort((a, b) => a.ratio! - b.ratio!)[0];
  const tile = (t: string, b: string, s: string): string =>
    `<div class="trait"><span class="eyebrow">${t}</span><b>${b}</b><span class="small muted">${s}</span></div>`;
  const board =
    attacks.length && bestImp && hardest
      ? `<div class="board">
    ${bestImp[1].w ? tile("Best impostor", esc(bestImp[0]), `${bestImp[1].w} of ${bestImp[1].n} attacks passed`) : tile("Best impostor", "Nobody yet", "No attack has passed")}
    ${tile("Hardest to copy", esc(hardest[0]), `${hardest[1].w} of ${hardest[1].n} attacks passed`)}
    ${closest ? tile("Closest call", `${closest.ratio!.toFixed(2)}×`, `${esc(closest.typist_name)} as ${esc(closest.target_name)}, where 1× is the limit`) : ""}
  </div>`
      : "";
  const rows = [...attempts]
    .reverse()
    .slice(0, 12)
    .map(
      (a: AttemptView) =>
        `<tr><td>${esc(a.typist_name)}</td><td>${esc(a.target_name)}</td><td>${{ attack: "Attack", self: "Own typing", disguise: "Disguise", replay: "Replay" }[a.mode]}${a.same_keyboard === false ? ` <span class="small muted">· different keyboard</span>` : ""}</td><td>${a.pace === null ? "n/a" : `${a.pace.toFixed(2)}&times;`}</td><td>${a.ratio === null ? "n/a" : `${a.ratio.toFixed(2)}×`}</td><td>${esc(a.word)}</td></tr>`,
    )
    .join("");
  return `<section class="stack"><h2>Scores</h2><p class="muted">From this room only, and shared by everyone in it. A few attempts make a fun scoreboard, not a measure of accuracy.</p></section>
    ${board}
    <section class="stack"><h3>Latest attempts</h3><div class="table-box"><table><thead><tr><th>Typing</th><th>Target</th><th>Type</th><th>Pace</th><th>Distance</th><th>Result</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
}

function howView(): string {
  // The approved mockup's own How It Works content (design/typing-twin-party.html's
  // howView()), kept here rather than linking out to the old account
  // system's separate /how-it-works page -- that page doesn't exist
  // in public mode, and this game has no account-system dependency
  // either way. The mockup's own "What's in this mockup" aside (about
  // its local-only JS simulation) is replaced with this game's actual
  // privacy disclosure, since every player here -- real or simulated
  // -- is genuinely scored by the backend, not a local approximation.
  return `<section class="stack">
    <h2>How it works</h2>
    <p>The detector measures two things: how long each key is held, and the time from one key going down to the next. For each timing, it works out how far your line is from a player's profile, measured in that timing's usual variation. The average is the distance. This method is called scaled Manhattan distance, scored by this app's own backend for every player -- real or simulated.</p>
    <p>Each player's limit comes from testing each of their training lines against the others. Below the limit, the typing passes as them. The scoring here is tuned for a handful of training lines instead of a full benchmark profile, so treat the limits as party tuning, not this app's measured accuracy.</p>
    <p>Reading a signature: the shape is scaled to each typist's own median gap, so it shows their relative rhythm and not simply their speed. Signatures can look alike, and a distinctive shape doesn't prove anyone is unique.</p>
    <p>This is a game, not security. A few lines of typing aren't enough to protect anything, and a replay -- run on the server from the target's typical timing, not a secret recording -- shows why rhythm can't be the only check.</p>
    <details>
      <summary>Privacy</summary>
      <div class="stack">
        <p class="small">A room's link is its only key. Anyone who has the link can join, and everyone in the room sees every player's name, signature, and scores. The host can lock the room to stop new people joining.</p>
        <p class="small">Key timing and key identity for the room's line are sent to the server for scoring. Raw keystrokes are discarded right after scoring -- the server keeps a player's timing statistics in memory until they're deleted or removed. Everything in a room disappears when the room ends, expires, or the app restarts. Anything typed outside the game line isn't accepted.</p>
        ${
          S.party?.scores_enabled
            ? `<p class="small">Scores are saved automatically, for every attempt. This site saves a few numbers about each result -- pace, how close it came to the limit, and whether it passed -- never your name, your keystrokes, or your IP address. Your attempts in this room are grouped under a random ID that isn't linked to your name. <b>Delete me</b>, <b>Leave room</b>, and <b>New room</b> remove your stored numbers while the room still exists, and the host ending the room removes everyone's; once a room expires, they can no longer be matched back to you at all, so they can no longer be deleted on request either.</p>`
            : `<p class="small">Nothing from this room is written to a database.</p>`
        }
        ${analyticsPrivacyNote()}
      </div>
    </details>
  </section>`;
}

function startOwnHTML(primary: boolean): string {
  return `<button${primary ? ' class="primary"' : ""} id="start-own" ${S.busy ? "disabled" : ""}>Start your own room</button>`;
}

/** One page for a room that ended, expired, or was lost to a restart,
 * and for a link that never was a room: the server answers them all
 * alike, so the page can't tell them apart and doesn't pretend to. */
function partyGoneView(): string {
  return `<section class="stack">
    <h2>This room has ended</h2>
    <p class="muted">A room ends when its host ends it, when it sits idle too long, or when the app restarts. A link that was never a room looks the same. Its names, signatures, and scores went with it.</p>
    <div class="row">${startOwnHTML(true)}</div>
    ${S.error ? `<p class="error">${esc(S.error)}</p>` : ""}
  </section>`;
}

function gateView(gate: Gate): string {
  if (gate.kind === "opening") {
    return `<section class="stack"><h2>Opening the room...</h2></section>`;
  }
  if (gate.kind === "switch") {
    return `<section class="stack">
    <h2>Leave your current room and join this one?</h2>
    <p class="muted">You're in room <span style="font-family:var(--mono)">${esc(formatCode(gate.current.code))}</span>. A browser is in one room at a time, and the players you added there leave with you.</p>
    <div class="row"><button class="primary" id="switch-join">Leave and join</button><button id="switch-stay">Stay in my room</button></div>
  </section>`;
  }
  const [title, text] = {
    locked: ["This room is locked", "Its host has stopped new people joining for now. Ask them to unlock it, then try again."],
    full: ["This room is full", "It already has as many browsers in it as a room can hold."],
    "rate-limited": ["Too many tries", "Wait a minute, then try again."],
    failed: ["Couldn't open the room", "Check your connection, then try again."],
  }[gate.kind];
  return `<section class="stack">
    <h2>${title}</h2>
    <p class="muted">${text}</p>
    <div class="row"><button class="primary" id="retry-join">Try again</button>${startOwnHTML(false)}</div>
    ${S.error ? `<p class="error">${esc(S.error)}</p>` : ""}
  </section>`;
}

function renderTabs(): void {
  const tabs = $("tabs");
  if (!tabs) return;
  if (!S.level || S.gate || S.partyGone || S.view === "enroll" || (S.view === "name" && !humans().length)) {
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
  const app = $("app");
  if (!app) return;
  if (S.gate) {
    app.innerHTML = gateView(S.gate);
    return;
  }
  if (S.partyGone) {
    app.innerHTML = partyGoneView();
    return;
  }
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
  app.innerHTML = views[S.view]();
  if ($("phrase")) drawTyper();
  if (S.view === "name") {
    ($("player-name") as HTMLInputElement | null)?.focus();
    void suggestName(false);
  }
}

function go(view: ViewName): void {
  S.replaying = 0;
  S.run = null;
  S.error = null;
  S.confirm = null;
  S.view = view;
  render();
}

function openAttack(targetId: string, mode: ApiMode): void {
  S.target = targetId;
  S.mode = mode;
  S.last = null;
  S.replaying = 0;
  S.error = null;
  S.view = "attack";
  render();
  startRun();
}

document.addEventListener("submit", (e) => {
  const form = e.target as HTMLElement;
  if (form.id === "name-form") {
    e.preventDefault();
    const input = $("player-name") as HTMLInputElement | null;
    S.enrollName = input?.value.trim() ?? "";
    S.enrollRuns = [];
    enrollSamples.length = 0;
    S.error = null;
    S.view = "enroll";
    render();
    startRun();
    return;
  }
  const renameId = (form as HTMLFormElement).dataset.renameForm;
  if (renameId) {
    e.preventDefault();
    const input = form.querySelector("input[name=name]") as HTMLInputElement | null;
    const name = input?.value.trim();
    if (name) void doRenamePlayer(renameId, name);
  }
});

document.addEventListener("input", (e) => {
  const target = e.target as HTMLElement;
  if (target.id === "player-name") target.dataset.edited = "true";
});

// Typing over a suggested name replaces it in one go.
document.addEventListener("focusin", (e) => {
  const target = e.target as HTMLElement;
  if (target.id !== "player-name") return;
  const input = target as HTMLInputElement;
  if (input.value !== "" && input.value === suggestedName) input.select();
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

document.addEventListener("click", (e) => {
  const eventTarget = e.target as HTMLElement;
  if (eventTarget.closest("#typer")) {
    $("typer")?.focus({ preventScroll: true });
    return;
  }
  const b = eventTarget.closest("button") as HTMLButtonElement | null;
  if (!b) return;
  if (b.id === "start-own") {
    void startRoom("sentence");
    return;
  }
  if (b.id === "retry-join" && S.gate && S.gate.kind !== "opening") {
    void openRoomLink(S.gate.code);
    return;
  }
  if (b.id === "switch-join" && S.gate?.kind === "switch") {
    void joinByLink(S.gate.code, true);
    return;
  }
  if (b.id === "switch-stay" && S.gate?.kind === "switch") {
    enterRoom(S.gate.current, "room");
    render();
    return;
  }
  if (b.id === "copy-link") {
    void copyRoomLink(b);
    return;
  }
  if (b.id === "confirm-yes") {
    answerConfirm();
    return;
  }
  if (b.id === "confirm-no") {
    S.confirm = null;
    render();
    return;
  }
  const asks: Record<string, Confirm> = {
    "leave-room": { kind: "leave" },
    "new-room": { kind: "new" },
    "lock-room": { kind: S.party?.locked ? "unlock" : "lock" },
    "end-room": { kind: "end" },
  };
  const ask = b.dataset.remove ? ({ kind: "remove", playerId: b.dataset.remove } as const) : asks[b.id];
  if (ask) {
    S.error = null;
    S.confirm = ask;
    render();
    return;
  }
  if (b.id === "home") {
    if (S.level) go("room");
    return;
  }
  if (b.dataset.level) {
    void startRoom(b.dataset.level as Level);
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
  if (b.dataset.delete) {
    void doDeletePlayer(b.dataset.delete);
    return;
  }
  if (b.dataset.rename) {
    S.renamingId = b.dataset.rename;
    render();
    return;
  }
  if (b.id === "to-room") {
    go("room");
    return;
  }
  if (b.id === "shuffle-name") {
    void suggestName(true);
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
    void runReplay();
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
});

// A room link opens its room. Anywhere else, show the page right away
// (the intro view needs no network request), then check in the
// background whether this browser is already in a room (e.g. a page
// reload) -- docs/plans/done/PARTY_LAUNCH_PLAN.md Part 1 section 8:
// "Show the page right away, even if a request is slow."
const linkCode = roomCodeFromPath(location.pathname);
if (linkCode !== null) {
  void openRoomLink(linkCode);
} else {
  render();
  void (async () => {
    try {
      enterRoom(await gameApi.getRoom(), "room");
      render();
    } catch {
      /* Not in a room -- the intro view already showing is correct. */
    }
  })();
}

// Visitor counting, only when the page was served with the GoatCounter
// snippet (see ../analytics.ts). Last, so it can never hold up the game.
startAnalytics();
