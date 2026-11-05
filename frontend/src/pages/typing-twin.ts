/**
 * Typing Twin: a rhythm-matching game built on top of this app's real
 * backend, not a self-contained toy. Enrollment sends samples to
 * POST /api/profile/samples; every attempt is scored live by
 * POST /api/profile/verify -- the same Argon2id accounts, Postgres-
 * backed profiles, and scaled-Manhattan scoring the rest of the app
 * uses, under a random, disposable account created just for this
 * play session (see the privacy note on the page itself).
 *
 * Game UI/presentation (the piano-roll drawing, sound, phrase
 * matching) is unchanged from the original index.html this was
 * ported from. What changed: the profile/scoring/threshold math that
 * file computed itself is gone, replaced by calls to ../api, which
 * talks to the real scoring engine in core/scoring.py.
 */

import { addSample, deleteProfile, login, logout, register, verifySample } from "../api";
import type { TypingResult } from "../api";
import { KeystrokeCapture } from "../capture";

const PHRASE = "quiet rhythm hides in every small habit of your hands";
const ROUNDS = 5; // Round 1 is a warm-up and isn't sent to the server.
const MAX_PACE_DEVIATION = 0.15;
const QWERTY = "qwertyuiopasdfghjklzxcvbnm ";
const LANES = [...QWERTY].filter((c) => PHRASE.includes(c));
const label = (c: string): string => (c === " " ? "space" : c);

//: Mirrors core/scoring.py's DEFAULT_THRESHOLD -- used only to draw
//: the gauge; the actual match/no_match/insufficient_data decision
//: always comes from the server's response, never computed here.
const DISPLAY_THRESHOLD = 1.0724;

type Mode = "self" | "disguise" | "friend";
type ViewName = "intro" | "enroll" | "reveal" | "play";

const MODES: Record<Mode, { name: string; blurb: string }> = {
  self: { name: "Be yourself", blurb: "Type normally. Does it recognize you?" },
  disguise: { name: "Wear a disguise", blurb: "Fool it at your usual pace, within 15%." },
  friend: { name: "Hand to a friend", blurb: "Can they copy your roll and pass as you?" },
};

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
  sample: ReturnType<KeystrokeCapture["sample"]>;
}

interface Verdict {
  good: boolean;
  title: string;
  text: string;
  counted: boolean;
  win?: boolean;
}

interface AttemptRecord {
  mode: Mode;
  score: number | null;
  paceRatio: number;
  title: string;
  counted: boolean;
  win?: boolean;
}

interface LastResult {
  run: Run;
  result: TypingResult | null;
  paceRatio: number;
  v: Verdict;
  mode: Mode;
}

interface State {
  view: ViewName;
  runs: Run[];
  mode: Mode;
  attempts: AttemptRecord[];
  last: LastResult | null;
  run: Run | null;
  busy: boolean;
}

const S: State = { view: "intro", runs: [], mode: "self", attempts: [], last: null, run: null, busy: false };
const $ = (id: string): HTMLElement | null => document.getElementById(id);

/* ---------- Ephemeral account ---------- */

function randomToken(length: number): string {
  const chars = "abcdefghijklmnopqrstuvwxyz0123456789";
  const bytes = crypto.getRandomValues(new Uint8Array(length));
  return Array.from(bytes, (b) => chars[b % chars.length]!).join("");
}

let accountReady: Promise<void> | null = null;

/** Registers and logs in a random, disposable account on first call;
 * later calls return the same (already-resolved, once it settles)
 * promise. Never surfaces a username/password to the player -- there
 * is nothing to remember, since nothing about this account is reused
 * after this play session. */
function ensureAccount(): Promise<void> {
  if (accountReady === null) {
    const username = `twin-${randomToken(12)}`;
    const password = randomToken(24);
    accountReady = register(username, password).then(() => login(username, password).then(() => undefined));
  }
  return accountReady;
}

/* ---------- Capture ---------- */

const capture = new KeystrokeCapture();

/* ---------- Roll drawing (unchanged from the original) ---------- */

interface Note {
  ch: string;
  start: number;
  dur: number;
}

function notesFromRun(run: Run): Note[] {
  const t0 = run.keys.length ? run.keys[0]!.down : 0;
  return run.keys.map((r) => ({ ch: r.ch, start: r.down - t0, dur: r.up !== null ? r.up - r.down : 70 }));
}

function median(a: number[]): number {
  const s = [...a].sort((x, y) => x - y);
  return s.length ? s[Math.floor(s.length / 2)]! : 0;
}

function notesFromProfile(): Note[] {
  let t = 0;
  return [...PHRASE].map((ch, i) => {
    if (i > 0) {
      t += median(S.runs.map((r) => r.keys[i]!.down - r.keys[i - 1]!.down));
    }
    const dur = median(S.runs.map((r) => (r.keys[i]!.up !== null ? r.keys[i]!.up! - r.keys[i]!.down : 70)));
    const note = { ch, start: t, dur };
    return note;
  });
}

function exampleNotes(): Note[] {
  let seed = 7;
  let t = 0;
  const rnd = (): number => (seed = (seed * 16807) % 2147483647) / 2147483647;
  return [...PHRASE].map((ch) => {
    const n = { ch, start: t, dur: 55 + rnd() * 75 };
    t += ch === " " ? 230 + rnd() * 90 : 80 + rnd() * 150;
    return n;
  });
}

function rollSVG(layers: { notes: Note[]; cls: string; inset?: boolean }[], minEnd?: number): string {
  const W = 760;
  const L = 44;
  const top = 16;
  const laneH = 13;
  const H = top + LANES.length * laneH + 28;
  const end = Math.max(minEnd ?? 0, 1000, ...layers.flatMap((l) => l.notes.map((n) => n.start + n.dur))) * 1.03;
  const x = (ms: number): number => L + (ms / end) * (W - L - 10);
  const step = [1000, 2000, 5000, 10000, 20000, 60000].find((s) => end / s <= 10) ?? 120000;
  let g = "";
  for (let i = 8; i < W; i += 14) g += `<circle class="perf" cx="${i}" cy="6" r="2.5"/>`;
  LANES.forEach((c, i) => {
    const y = top + i * laneH;
    g += `<line class="lane-line" x1="${L}" x2="${W - 10}" y1="${y + laneH}" y2="${y + laneH}"/><text class="lane-label" x="${L - 6}" y="${y + 10}" text-anchor="end">${label(c)}</text>`;
  });
  const base = top + LANES.length * laneH;
  for (let t = 0; t <= end; t += step) {
    g += `<line class="tick-line" x1="${x(t)}" x2="${x(t)}" y1="${top}" y2="${base}"/><text class="tick-label" x="${x(t)}" y="${base + 15}" text-anchor="middle">${t / 1000}s</text>`;
  }
  layers.forEach((l) =>
    l.notes.forEach((n) => {
      const i = LANES.indexOf(n.ch);
      if (i < 0) return;
      const y = top + i * laneH + (l.inset ? 4 : 2);
      const h = laneH - (l.inset ? 8 : 4);
      g += `<rect class="${l.cls}" x="${x(n.start).toFixed(1)}" y="${y}" width="${Math.max(3, x(n.start + n.dur) - x(n.start)).toFixed(1)}" height="${h}" rx="2"/>`;
    }),
  );
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Piano roll of key presses over time. Each row is a key and each bar shows how long it was held.">${g}</svg>`;
}

/* ---------- Typing ---------- */

function startRun(): void {
  S.run = { idx: 0, keys: [], errors: 0, pendingError: false, held: {}, finished: false, sample: [] };
  capture.reset();
  drawTyper();
  focusTyper();
}

function focusTyper(): void {
  $("typer")?.focus({ preventScroll: true });
}

function canType(): boolean {
  const t = $("typer");
  return S.run !== null && !S.run.finished && t !== null && document.activeElement === t;
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && S.run && $("typer")) {
    e.preventDefault();
    startRun();
    return;
  }
  if (!canType() || e.ctrlKey || e.metaKey || e.altKey || e.key.length !== 1) return;
  e.preventDefault();
  if (e.repeat) return;
  const r = S.run!;
  const expected = PHRASE[r.idx];
  if (e.key.toLowerCase() === expected) {
    const rec: KeyRecord = { ch: expected, down: e.timeStamp, up: null, afterError: r.pendingError };
    r.keys.push(rec);
    if (r.keys.length === 1) $("result")?.setAttribute("hidden", ""); // Clear the last verdict once typing starts.
    r.held[e.code] = rec;
    r.pendingError = false;
    r.idx += 1;
    capture.record(e);
    if (r.idx === PHRASE.length) {
      r.finished = true;
      setTimeout(() => void finishRun(), 260); // Allow a moment for the final key to come up.
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

async function finishRun(): Promise<void> {
  const run = S.run;
  if (!run) return;
  run.sample = capture.sample();

  if (S.view === "enroll") {
    S.runs.push(run);
    const isWarmup = S.runs.length === 1;
    const isLast = S.runs.length === ROUNDS;

    if (!isWarmup) {
      S.busy = true;
      try {
        await ensureAccount();
        await addSample(run.sample);
      } catch (error) {
        S.busy = false;
        showEnrollError(error);
        return;
      }
      S.busy = false;
    }

    if (isLast) {
      S.view = "reveal";
      render();
    } else {
      render();
      startRun();
    }
    return;
  }

  await judge(run);
  render();
  startRun();
}

function showEnrollError(error: unknown): void {
  console.error("Typing Twin: failed to save an enrollment line", error);
  const el = $("enroll-error");
  if (el) {
    el.textContent =
      "Couldn't reach the server to save that line. Check your connection and press Esc to try the line again.";
    el.hidden = false;
  }
}

function drawTyper(oops?: boolean): void {
  const r = S.run;
  const p = $("phrase");
  if (!p || !r) return;
  const i = r.idx;
  p.innerHTML =
    `<span class="done">${PHRASE.slice(0, i)}</span>` +
    (i < PHRASE.length
      ? `<span class="cur">${PHRASE[i] === " " ? "&nbsp;" : PHRASE[i]}</span><span class="todo">${PHRASE.slice(i + 1)}</span>`
      : "");
  if (!oops) $("typer")?.classList.remove("oops");
  const typos = $("typos");
  if (typos) typos.textContent = r.errors === 1 ? "1 wrong key" : `${r.errors} wrong keys`;
  const live = $("live-roll");
  if (live) {
    const layers: { notes: Note[]; cls: string; inset?: boolean }[] = [];
    if (S.view === "play" && S.mode === "friend") layers.push({ notes: notesFromProfile(), cls: "n-ghost" });
    layers.push({
      notes: notesFromRun(r),
      cls: S.view === "enroll" ? "n-a" : "n-b",
      inset: S.view === "play" && S.mode === "friend",
    });
    live.innerHTML = rollSVG(layers, S.view === "play" ? usualDuration() : 8000);
  }
}

function duration(run: Run): number {
  return run.keys[run.keys.length - 1]!.down - run.keys[0]!.down;
}

function usualDuration(): number {
  return S.runs.reduce((a, r) => a + duration(r), 0) / S.runs.length;
}

function typerHTML(hint: string, between?: string): string {
  return `<div class="typer" id="typer" tabindex="0" role="textbox" aria-label="Typing area. Type this line: ${PHRASE}">
    <div class="phrase" id="phrase"></div>
    <div class="typer-foot"><span class="blur-note">Click here to type</span><span>${hint}</span><span id="typos" aria-live="off"></span></div>
  </div>
  <div class="row"><button class="quiet" id="restart">Restart line (Esc)</button></div>
  <p class="error" id="enroll-error" hidden></p>
  ${between ?? ""}
  <div class="roll-box" id="live-roll"></div>`;
}

/* ---------- Judging ---------- */

async function judge(run: Run): Promise<void> {
  const paceRatio = duration(run) / usualDuration();
  const paceOk = paceRatio >= 1 - MAX_PACE_DEVIATION && paceRatio <= 1 + MAX_PACE_DEVIATION;

  let result: TypingResult | null = null;
  try {
    await ensureAccount();
    result = await verifySample(run.sample);
  } catch {
    result = null;
  }

  const v = verdictFor(S.mode, result, paceOk, paceRatio);
  S.last = { run, result, paceRatio, v, mode: S.mode };
  S.attempts.unshift({
    mode: S.mode,
    score: result?.score ?? null,
    paceRatio,
    title: v.title,
    counted: v.counted,
    win: v.win,
  });
}

function verdictFor(mode: Mode, result: TypingResult | null, paceOk: boolean, paceRatio: number): Verdict {
  if (result === null || result.decision === "insufficient_data") {
    return {
      good: false,
      title: "Not enough clean typing",
      text: "Too many wrong keys broke up the rhythm, the server couldn't be reached, or this line didn't produce enough matching timings yet. Try the line again.",
      counted: false,
    };
  }
  const isMatch = result.decision === "match";

  if (mode === "self") {
    return isMatch
      ? { good: true, title: "That's you", text: "This line sits inside your rhythm range.", counted: true, win: true }
      : {
          good: false,
          title: "It didn't recognize you",
          text: "This is a false rejection. Rushing, tiredness, or a new posture can all cause one.",
          counted: true,
          win: false,
        };
  }

  if (mode === "disguise") {
    if (!paceOk) {
      const pct = Math.abs(Math.round((paceRatio - 1) * 100));
      return {
        good: false,
        title: paceRatio < 1 ? "Too fast to count" : "Too slow to count",
        text: `Your pace was ${pct}% ${paceRatio < 1 ? "faster" : "slower"} than usual. Disguises must stay within 15%.`,
        counted: false,
      };
    }
    return !isMatch
      ? { good: true, title: "The disguise worked", text: "You kept your pace and still fooled the detector.", counted: true, win: true }
      : {
          good: false,
          title: "Still you",
          text: "The detector saw through it. Try shifting which keys you hold longer.",
          counted: true,
          win: false,
        };
  }

  // friend
  return isMatch
    ? { good: false, title: "They fooled it", text: "This is a false acceptance. Someone else passed as you.", counted: true, win: true }
    : { good: true, title: "Caught", text: "The detector could tell this wasn't you.", counted: true, win: false };
}

function gaugeSVG(score: number, threshold: number): string {
  const W = 760;
  const end = Math.max(threshold * 2, score * 1.15);
  const x = (v: number): number => 10 + (v / end) * (W - 20);
  const px = Math.min(W - 60, Math.max(60, x(score)));
  return `<svg viewBox="0 0 ${W} 72" role="img" aria-label="Distance ${score.toFixed(2)} against a limit of ${threshold.toFixed(2)}">
    <text class="g-val" x="${px}" y="14" text-anchor="middle">distance ${score.toFixed(2)}</text>
    <path class="g-mark" d="M${x(score) - 6} 20 h12 l-6 8 z"/>
    <rect class="g-a" x="10" y="30" width="${x(threshold) - 10}" height="12" rx="2"/>
    <rect class="g-b" x="${x(threshold)}" y="30" width="${W - 10 - x(threshold)}" height="12" rx="2"/>
    <line class="g-thr" x1="${x(threshold)}" x2="${x(threshold)}" y1="26" y2="46"/>
    <text class="g-text" x="10" y="62">0, identical</text>
    <text class="g-text" x="${x(threshold)}" y="62" text-anchor="middle">limit ${threshold.toFixed(2)}</text>
    <text class="g-text" x="${W - 10}" y="62" text-anchor="end">further from you</text>
  </svg>`;
}

/* ---------- Sound ---------- */

function playNotes(notes: Note[]): void {
  try {
    const Ctx = window.AudioContext;
    const ctx = new Ctx();
    const scale = [0, 2, 4, 7, 9];
    const t0 = ctx.currentTime + 0.05;
    notes.forEach((n) => {
      const lane = LANES.indexOf(n.ch);
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

/* ---------- Views ---------- */

function introView(): string {
  const coarse = window.matchMedia?.("(pointer: coarse)").matches;
  return `<div class="stack">
      <h1>Your hands keep time. Can anyone copy it?</h1>
      <p>Type one short line a few times and the game learns your rhythm -- for real, on this app's own backend. Then try to fool it: disguise your own typing, or hand the keyboard to a friend.</p>
      ${coarse ? `<div class="notice">Bring a physical keyboard for this one. Phone keyboards don't report when each key goes down and up.</div>` : ""}
      <div class="row"><button class="primary" id="begin">Start, about 1 minute</button></div>
      <p class="small muted">Playing creates a random, disposable account just for this session -- see the privacy note below.</p>
    </div>
    <div class="stack">
      <div class="eyebrow">Example roll, not your typing yet</div>
      <div class="roll-box">${rollSVG([{ notes: exampleNotes(), cls: "n-a" }])}</div>
      <p class="small muted">Read it like a player-piano roll. Each row is a key, and each bar shows when it went down and how long it stayed down.</p>
    </div>`;
}

function enrollView(): string {
  const n = S.runs.length;
  const dots = Array.from(
    { length: ROUNDS },
    (_, i) => `<span class="dot ${i < n ? "ok" : i === n ? "on" : ""}">${i === 0 ? "Warm-up" : "Line " + i}</span>`,
  ).join("");
  return `<div class="stack">
    <h2>${n === 0 ? "Warm up on this line" : "Same line, your normal rhythm"}</h2>
    <p class="muted">Don't race. Wrong keys don't need fixing, just press the right one.</p>
    <div class="dots" aria-label="Progress: line ${n + 1} of ${ROUNDS}">${dots}</div>
    ${typerHTML("Keep typing, it advances on its own")}
  </div>`;
}

function traitsHTML(): string {
  const counts = new Map<string, number[]>();
  S.runs.forEach((run) => {
    run.keys.forEach((r, i) => {
      if (r.up !== null) {
        const key = `h:${r.ch}`;
        const arr = counts.get(key) ?? [];
        arr.push(r.up - r.down);
        counts.set(key, arr);
      }
      if (i > 0 && !r.afterError) {
        const prev = run.keys[i - 1]!;
        const key = `f:${prev.ch}${r.ch}`;
        const arr = counts.get(key) ?? [];
        arr.push(r.down - prev.down);
        counts.set(key, arr);
      }
    });
  });
  const flights = [...counts.entries()].filter(([k, v]) => k.startsWith("f:") && v.length >= 3);
  const byMean = flights
    .map(([k, v]) => [k, v.reduce((a, b) => a + b, 0) / v.length] as const)
    .sort((a, b) => a[1] - b[1]);
  const pairLabel = (k: string): string => {
    const a = k[2]!;
    const b = k[3]!;
    return `${label(a)}${b === " " || a === " " ? " → " : ""}${label(b)}`;
  };
  const holds = [...counts.entries()].filter(([k]) => k.startsWith("h:")).map(([, v]) => v.reduce((a, b) => a + b, 0) / v.length);
  const wpm = Math.round(PHRASE.length / 5 / (usualDuration() / 60000));
  const tile = (t: string, b: string, s: string): string =>
    `<div class="trait"><span class="eyebrow">${t}</span><b>${b}</b><span class="small muted">${s}</span></div>`;
  const fast = byMean[0];
  const slow = byMean[byMean.length - 1];
  return `<div class="traits">
    ${tile("Pace", wpm + " wpm", "on this line")}
    ${tile("Typical hold", Math.round(median(holds)) + " ms", "per key")}
    ${fast ? tile("Fastest pair", pairLabel(fast[0]), Math.round(fast[1]) + " ms") : ""}
    ${slow ? tile("Slowest pair", pairLabel(slow[0]), Math.round(slow[1]) + " ms") : ""}
  </div>`;
}

function revealView(): string {
  return `<div class="stack">
      <h2>This is your rhythm</h2>
      <p>Your median timing across four lines, the same ones the server just finished building your profile from.</p>
      <div class="roll-box">${rollSVG([{ notes: notesFromProfile(), cls: "n-a" }])}</div>
      <div class="row"><button class="primary" id="to-play">Try to beat it</button><button id="hear">Hear my rhythm</button></div>
    </div>
    ${traitsHTML()}`;
}

function resultHTML(): string {
  const L = S.last;
  if (!L) return "";
  const { result, v } = L;
  const pace = Math.round(L.paceRatio * 100);
  const layers = [
    { notes: notesFromProfile(), cls: "n-ghost" },
    { notes: notesFromRun(L.run), cls: "n-b", inset: true },
  ];
  const score = result?.score ?? null;
  return `<section class="result stack" id="result" aria-live="polite">
    <div class="eyebrow">${MODES[L.mode].name}</div>
    <h2 class="${v.good ? "v-good" : "v-bad"}">${v.title}</h2>
    <p>${v.text}</p>
    ${
      score !== null
        ? `<div class="gauge">${gaugeSVG(score, DISPLAY_THRESHOLD)}</div>
    <p class="small muted">Compared ${result!.compared_features} timings, scored by the server just now. This line took ${pace}% of your usual time.</p>
    <div class="legend"><span><i class="swatch n-ghost" style="background:var(--accent);opacity:.3"></i>Your profile</span><span><i class="swatch" style="background:var(--twin)"></i>This attempt</span></div>
    <div class="roll-box">${rollSVG(layers)}</div>`
        : ""
    }
  </section>`;
}

function recordHTML(): string {
  if (!S.attempts.length) return "";
  const c = (m: Mode): { n: number; w: number } => {
    const a = S.attempts.filter((x) => x.mode === m && x.counted);
    return { n: a.length, w: a.filter((x) => x.win).length };
  };
  const self = c("self");
  const dis = c("disguise");
  const fr = c("friend");
  const tile = (t: string, b: string, s: string): string =>
    `<div class="trait"><span class="eyebrow">${t}</span><b>${b}</b><span class="small muted">${s}</span></div>`;
  const rows = S.attempts
    .slice(0, 8)
    .map(
      (a) =>
        `<tr><td>${MODES[a.mode].name}</td><td>${a.score === null ? "n/a" : a.score.toFixed(2)}</td><td>${Math.round(a.paceRatio * 100)}%</td><td>${a.title}</td></tr>`,
    )
    .join("");
  return `<section class="stack">
    <h3>Detector's record this session</h3>
    <div class="record">
      ${tile("Recognized you", `${self.w} / ${self.n}`, "higher is better for it")}
      ${tile("Disguises that worked", `${dis.w} / ${dis.n}`, "lower is better for it")}
      ${tile("Friends who passed", `${fr.w} / ${fr.n}`, "lower is better for it")}
    </div>
    <div class="table-box"><table><thead><tr><th>Mode</th><th>Distance</th><th>Pace</th><th>Result</th></tr></thead><tbody>${rows}</tbody></table></div>
  </section>`;
}

function playView(): string {
  const tabs = Object.entries(MODES)
    .map(([k, m]) => `<button class="tab" data-mode="${k}" aria-pressed="${S.mode === k}">${m.name}<span>${m.blurb}</span></button>`)
    .join("");
  return `<div class="stack">
      <h2>Beat the detector</h2>
      <div class="tabs">${tabs}</div>
      ${typerHTML(MODES[S.mode].name, resultHTML())}
    </div>
    ${recordHTML()}
    <details>
      <summary>How the detector works</summary>
      <div class="stack">
        <p>It measures two things: how long each key is held, and the time from one key going down to the next. The server compares your line to your stored profile the same way the rest of this app does -- see <a href="/how-it-works">How It Works</a> for the actual method and its measured accuracy.</p>
        <p>A profile built from four short lines is a toy enrollment, so treat this as a game and not as security.</p>
      </div>
    </details>`;
}

function render(): void {
  const headActions = $("head-actions");
  if (headActions) {
    headActions.innerHTML = S.view !== "intro" ? `<button class="quiet" id="reset">Start over</button>` : "";
  }
  const views: Record<ViewName, () => string> = { intro: introView, enroll: enrollView, reveal: revealView, play: playView };
  const app = $("app");
  if (app) app.innerHTML = views[S.view]();
  if ($("typer")) drawTyper();
}

async function resetGame(): Promise<void> {
  const pending = accountReady;
  accountReady = null;
  if (pending) {
    try {
      await pending;
      await deleteProfile();
      await logout();
    } catch {
      /* Best-effort cleanup -- the account is disposable either way. */
    }
  }
  Object.assign(S, { view: "intro", runs: [], mode: "self", attempts: [], last: null, run: null, busy: false });
  render();
}

document.addEventListener("click", (e) => {
  const target = e.target as HTMLElement;
  const b = target.closest("button");
  const typer = target.closest("#typer");
  if (typer) {
    focusTyper();
    return;
  }
  if (!b) return;
  if (b.id === "begin") {
    S.view = "enroll";
    render();
    startRun();
    void ensureAccount().catch(() => {
      /* Surfaced at the first addSample/verifySample call instead. */
    });
  } else if (b.id === "reset") {
    void resetGame();
  } else if (b.id === "restart") {
    startRun();
  } else if (b.id === "hear") {
    playNotes(notesFromProfile());
  } else if (b.id === "to-play") {
    S.view = "play";
    render();
    startRun();
  } else if (b.dataset.mode) {
    S.mode = b.dataset.mode as Mode;
    S.last = null;
    render();
    startRun();
  }
});

render();
