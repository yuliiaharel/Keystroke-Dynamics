/**
 * Typing Twin Party: the anonymous, no-database party game
 * (PARTY_LAUNCH_PLAN.md Part 1). Every score -- a real player's own
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
 * a form -- is what the server trusts to know which party this
 * browser owns.
 */

import * as gameApi from "../game-api";
import type { AttemptView, Level, Mode as ApiMode, NoteView, PartyView, PlayerView } from "../game-api";
import { KeystrokeCapture } from "../capture";
import type { CapturedEvent } from "../capture";
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

interface State {
  view: ViewName;
  level: Level | null;
  party: PartyView | null;
  typingAs: string | null;
  target: string | null;
  mode: ApiMode;
  enrollName: string;
  //: PARTY_LAUNCH_PLAN.md section 10's opt-in, captured once at the
  //: name-form submit (before enrollment typing starts) and sent with
  //: createPlayer -- never pre-checked, never required.
  enrollShareScores: boolean;
  //: The same opt-in for a Guest attacker (no enrolled Player to
  //: have opted in at creation time), shown in attackView() and sent
  //: with every attempt while typingAs stays null.
  guestSharesScores: boolean;
  enrollRuns: Run[];
  run: Run | null;
  last: LastResult | null;
  replaying: number;
  justAddedId: string | null;
  confirmNew: boolean;
  partyGone: boolean;
  renamingId: string | null;
  busy: boolean;
  error: string | null;
}

const S: State = {
  view: "intro",
  level: null,
  party: null,
  typingAs: null,
  target: null,
  mode: "attack",
  enrollName: "",
  enrollShareScores: false,
  guestSharesScores: false,
  enrollRuns: [],
  run: null,
  last: null,
  replaying: 0,
  justAddedId: null,
  confirmNew: false,
  partyGone: false,
  renamingId: null,
  busy: false,
  error: null,
};

const phrase = (): string => S.party?.phrase ?? "";
const lanes = (p: string): string[] => [...QWERTY].filter((c) => p.includes(c));
const allEntities = (): PlayerView[] => (S.party ? [...S.party.players, ...S.party.targets] : []);
const byId = (id: string): PlayerView | undefined => allEntities().find((p) => p.id === id);
const humans = (): PlayerView[] => S.party?.players ?? [];

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
        const player = await gameApi.createPlayer(
          S.enrollName || null,
          enrollSamples,
          S.enrollShareScores,
        );
        S.enrollRuns = [];
        enrollSamples.length = 0;
        S.typingAs = player.id;
        S.justAddedId = player.id;
        S.run = null;
        S.view = "reveal";
        await refreshParty();
      } catch (error) {
        S.busy = false;
        if (gameApi.isPartyGone(error)) {
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
      guestSharesScores: S.guestSharesScores,
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
    if (gameApi.isPartyGone(error)) {
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
    if (gameApi.isPartyGone(error)) {
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
    S.party = await gameApi.getParty();
  } catch (error) {
    if (gameApi.isPartyGone(error)) {
      S.partyGone = true;
    }
  }
}

async function startParty(level: Level): Promise<void> {
  S.busy = true;
  S.error = null;
  render();
  try {
    S.party = await gameApi.createParty(level);
    S.level = level;
    S.partyGone = false;
    S.view = "name";
  } catch {
    S.error = "Couldn't start a party right now. Try again in a moment.";
  }
  S.busy = false;
  render();
}

async function doResetParty(): Promise<void> {
  try {
    await gameApi.resetParty();
  } catch {
    /* Best-effort -- the party is going away either way. */
  }
  Object.assign(S, {
    view: "intro",
    level: null,
    party: null,
    typingAs: null,
    target: null,
    mode: "attack",
    enrollName: "",
    enrollShareScores: false,
    guestSharesScores: false,
    enrollRuns: [],
    run: null,
    last: null,
    replaying: 0,
    justAddedId: null,
    confirmNew: false,
    partyGone: false,
    renamingId: null,
    busy: false,
    error: null,
  });
  enrollSamples.length = 0;
  render();
}

async function doDeletePlayer(id: string): Promise<void> {
  try {
    await gameApi.deletePlayer(id);
    if (S.typingAs === id) S.typingAs = null;
    await refreshParty();
  } catch (error) {
    if (gameApi.isPartyGone(error)) S.partyGone = true;
  }
  render();
}

async function doRenamePlayer(id: string, name: string): Promise<void> {
  try {
    await gameApi.renamePlayer(id, name);
    S.renamingId = null;
    await refreshParty();
  } catch (error) {
    if (gameApi.isPartyGone(error)) {
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
  const coarse = window.matchMedia?.("(pointer: coarse)").matches;
  return `<section class="hero">
      <div class="stack">
        <h1>Everyone types in their own shape.</h1>
        <p>Type a line a few times and see your rhythm drawn as a signature -- scored for real by this app's own backend. Then gather some friends around one keyboard and try to pass as each other.</p>
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

function shareScoresCheckboxHTML(id: string, checked: boolean): string {
  // Not shown at all unless the server says collection is actually
  // on (PartyView.scores_enabled) -- never inferred any other way,
  // and never pre-checked (PARTY_LAUNCH_PLAN.md section 10).
  if (!S.party?.scores_enabled) return "";
  return `<label style="display:flex;gap:8px;align-items:flex-start;font-weight:400;max-width:48ch">
    <input type="checkbox" id="${id}" ${checked ? "checked" : ""} style="margin-top:3px">
    <span><b>${esc(S.party.consent_label)}</b><br><span class="small muted">${esc(S.party.consent_explanation)}</span></span>
  </label>`;
}

function nameView(): string {
  return `<section class="stack" style="max-width:560px">
    <div class="eyebrow">New player</div>
    <h2>Who's typing?</h2>
    <p class="muted">You'll type the line ${LEVELS[S.level!].rounds} times. The first one is a warm-up. Leave the name blank for a generated one.</p>
    <form id="name-form" class="stack">
      <div class="row end">
        <label for="player-name">Your name (optional)<input id="player-name" maxlength="24" autocomplete="off"></label>
        <button class="primary" type="submit">Start typing</button>
      </div>
      ${shareScoresCheckboxHTML("enroll-share-scores", S.enrollShareScores)}
    </form>
    ${humans().length ? `<button class="quiet" id="to-room" style="align-self:flex-start">Skip and see the room</button>` : ""}
  </section>`;
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

function playerCardHTML(p: PlayerView): string {
  const renameForm =
    S.renamingId === p.id
      ? `<form class="row" data-rename-form="${esc(p.id)}">
           <input name="name" maxlength="24" value="${esc(p.name)}" autocomplete="off">
           <button class="quiet" type="submit">Save</button>
         </form>`
      : "";
  const controls =
    p.kind === "player"
      ? `<button class="quiet" data-rename="${esc(p.id)}">Rename</button><button class="quiet" data-delete="${esc(p.id)}">Delete me</button>`
      : "";
  return `<article class="card">
      <h3>${esc(p.name)}</h3>
      <div class="ring">${ringSVG(p.notes, p.color, null, p.name)}</div>
      <div class="tag">${targetTag(p)}</div>
      <div class="row"><button class="primary" data-attack="${esc(p.id)}">${attackButtonLabel(p)}</button>${p.kind === "player" ? `<button data-self="${esc(p.id)}">Test me</button>` : ""}</div>
      <div class="row">${controls}</div>
      ${renameForm}
    </article>`;
}

function roomView(): string {
  const cards = [...humans(), ...(S.party?.targets ?? [])].map(playerCardHTML).join("");
  const add = `<article class="card add"><h3>${humans().length ? "Someone else wants in?" : "Add yourself"}</h3><p class="small muted">Everyone types the same line, so attacks are fair.</p><button class="primary" id="add-player">Add a player</button></article>`;
  const coarse = window.matchMedia?.("(pointer: coarse)").matches;
  return `<section class="stack">
      <div class="row" style="justify-content:space-between"><div class="stack" style="gap:4px"><h2>The room</h2><p class="muted">Line: <span style="font-family:var(--mono)">${phrase()}</span></p></div></div>
      ${coarse ? `<div class="notice">Best on a computer -- you can still watch a replay attack without typing.</div>` : ""}
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
  const { attempt, text, target, clue } = L;
  const good = attempt.mode === "attack" ? attempt.passed === false : attempt.passed === true;
  // Pace and a one-line clue, shown on every scoreable result
  // (PARTY_LAUNCH_PLAN.md section 8, following
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
  return `<section class="result stack" id="result" aria-live="polite">
    <p class="verdict ${good ? "v-good" : "v-bad"}">${esc(attempt.word)}</p>
    <p>${esc(text)}</p>
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
  const whoOpts = `<option value="">Guest</option>${opts(S.typingAs, humans())}`;
  const modeBtns = same
    ? `<div class="row"><button id="m-self" class="${S.mode === "self" ? "primary" : ""}">Prove it's you</button><button id="m-disguise" class="${S.mode === "disguise" ? "primary" : ""}">Wear a disguise</button></div>`
    : "";
  const title = same ? (S.mode === "disguise" ? "Fool your own signature" : "Prove it's you") : `Pass as ${esc(target.name)}`;
  const hint = same ? "Type the line" : "Match the pink bars on the roll";
  const replay = !same ? `<button class="quiet" id="replay" ${S.busy ? "disabled" : ""}>Watch a replay attack</button>` : "";
  // "for a Guest before their first attack" (PARTY_LAUNCH_PLAN.md
  // section 10) -- not shown once a real enrolled player is typing;
  // their own choice from enrollment is what's authoritative then.
  const guestConsent = !S.typingAs ? shareScoresCheckboxHTML("guest-share-scores", S.guestSharesScores) : "";
  return `<section class="stack">
      <h2>${title}</h2>
      <div class="row end">
        <label for="who">Who's typing?<select id="who">${whoOpts}</select></label>
        <label for="tgt">Target<select id="tgt">${opts(S.target, [...humans(), ...(S.party?.targets ?? [])])}</select></label>
        ${modeBtns}
      </div>
      ${guestConsent}
      ${typerHTML(hint, resultHTML(), replay)}
      ${S.error ? `<p class="error">${esc(S.error)}</p>` : ""}
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
        `<tr><td>${esc(a.typist_name)}</td><td>${esc(a.target_name)}</td><td>${{ attack: "Attack", self: "Own typing", disguise: "Disguise", replay: "Replay" }[a.mode]}</td><td>${a.pace === null ? "n/a" : `${a.pace.toFixed(2)}&times;`}</td><td>${a.ratio === null ? "n/a" : `${a.ratio.toFixed(2)}×`}</td><td>${esc(a.word)}</td></tr>`,
    )
    .join("");
  return `<section class="stack"><h2>Scores</h2><p class="muted">From this party only. A few attempts make a fun scoreboard, not a measure of accuracy.</p></section>
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
        <p class="small">Key timing and key identity for this party's line are sent to the server for scoring. Raw timings are discarded right after scoring -- the server keeps a player's timing statistics in memory until they delete themselves, or the party expires or the app restarts. Everyone playing in this same party can see names and signatures. Anything typed outside the game line isn't accepted.</p>
        ${
          S.party?.scores_enabled
            ? `<p class="small">Sharing scores is optional, off by default, and never required to play. If you opt in, this stores a few numbers about a result -- pace, how close it came to the limit, and whether it passed -- never your name, your keystrokes, or your IP address. Your attempts in this party are grouped under a random ID that isn't linked to your name. <b>Delete me</b> and <b>New party</b> remove those stored numbers while the party still exists; once a party ends, they can no longer be matched back to you at all, so they can no longer be deleted on request either.</p>`
            : `<p class="small">Nothing from this party is written to a database.</p>`
        }
      </div>
    </details>
  </section>`;
}

function partyGoneView(): string {
  return `<section class="stack">
    <h2>This party is gone</h2>
    <p class="muted">The server restarted or this party's idle time ran out. Nothing about it was kept beyond that, by design.</p>
    <button class="primary" id="start-over">Start a new party</button>
  </section>`;
}

function renderTabs(): void {
  const tabs = $("tabs");
  if (!tabs) return;
  if (!S.level || S.partyGone || S.view === "enroll" || (S.view === "name" && !humans().length)) {
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
  if ($("typer")) drawTyper();
  if (S.view === "name") ($("player-name") as HTMLInputElement | null)?.focus();
}

function go(view: ViewName): void {
  S.replaying = 0;
  S.run = null;
  S.error = null;
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
    const shareScores = $("enroll-share-scores") as HTMLInputElement | null;
    S.enrollShareScores = shareScores?.checked ?? false;
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
  } else if (target.id === "guest-share-scores") {
    // No render()/startRun() -- unlike who/tgt, this doesn't change
    // what's being typed, just the opt-in sent with the next attempt.
    S.guestSharesScores = (target as HTMLInputElement).checked;
  }
});

document.addEventListener("click", (e) => {
  const eventTarget = e.target as HTMLElement;
  if (eventTarget.closest("#typer")) {
    $("typer")?.focus({ preventScroll: true });
    return;
  }
  if (eventTarget.id === "start-over") {
    void doResetParty();
    return;
  }
  const b = eventTarget.closest("button") as HTMLButtonElement | null;
  if (!b) return;
  if (b.id === "home") {
    if (S.level) go("room");
    return;
  }
  if (b.dataset.level) {
    void startParty(b.dataset.level as Level);
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
    void doResetParty();
  }
});

// Show the page right away (the intro view needs no network request),
// then check in the background whether this session already owns a
// party (e.g. a page reload) -- PARTY_LAUNCH_PLAN.md Part 1 section
// 8: "Show the page right away, even if a request is slow."
render();
void (async () => {
  try {
    const party = await gameApi.getParty();
    S.party = party;
    S.level = party.level;
    S.view = "room";
    render();
  } catch {
    /* No active party yet -- the intro view already showing is correct. */
  }
})();
