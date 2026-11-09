/**
 * Debug-only capture test page (MOBILE_PLAN.md Phase 0), served at
 * /debug/touch-capture only when DEBUG=true.
 *
 * Shows what a phone browser actually delivers for a line typed on the
 * on-page keyboard from design/typing-twin-touch.html. Everything stays
 * in the page: it makes no requests, so no tap ever reaches the server.
 *
 * Unlike the game will, this page accepts mouse and untrusted events
 * and reports them, since its job is to show what arrives.
 */

import {
  analyze,
  spread,
  timestampStep,
  type Analysis,
  type PointerRecord,
  type Spread,
  type TapOutcome,
} from "../touch-capture";

const PHRASE = "tap the rhythm of your thumbs";
const ROWS = ["qwertyuiop", "asdfghjkl", "zxcvbnm"];
/** How long to wait for the last finger to lift before reporting. */
const FINAL_LIFT_WAIT_MS = 280;

const codeFor = (ch: string): string => (ch === " " ? "Space" : `Key${ch.toUpperCase()}`);
const labelFor = (code: string | null): string =>
  code === null ? "(gap)" : code === "Space" ? "space" : code.slice(3).toLowerCase();

interface Disturbances {
  scroll: number;
  zoom: number;
  selection: number;
  callout: number;
  touchCancel: number;
  pageHidden: number;
  viewportResize: number;
}

interface Run {
  position: number;
  wrong: number;
  records: PointerRecord[];
  disturbances: Disturbances;
  touchStarts: number;
  touchEnds: number;
  /** Disturbances count only from the first tap, so setup scrolling doesn't. */
  armed: boolean;
  finished: boolean;
  /** Pointer ids currently down that landed on the keyboard. */
  held: Set<number>;
}

interface LineReport {
  line: number;
  completed: boolean;
  wrong: number;
  analysis: Analysis;
  records: PointerRecord[];
  disturbances: Disturbances;
  touchStarts: number;
  touchEnds: number;
}

interface KeyMetrics {
  letterKey: string;
  spaceKey: string;
  keyboard: string;
}

const state: {
  view: "ready" | "typing" | "report";
  run: Run | null;
  lines: LineReport[];
  keyMetrics: KeyMetrics | null;
  copied: boolean;
} = { view: "ready", run: null, lines: [], keyMetrics: null, copied: false };

function mustGet(id: string): HTMLElement {
  const el = document.getElementById(id);
  if (!el) throw new Error(`touch-capture: #${id} is missing from the page`);
  return el;
}

const app = mustGet("app");
const keyboard = mustGet("keyboard");

const esc = (s: unknown): string =>
  String(s).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] ?? c,
  );

const noDisturbances = (): Disturbances => ({
  scroll: 0,
  zoom: 0,
  selection: 0,
  callout: 0,
  touchCancel: 0,
  pageHidden: 0,
  viewportResize: 0,
});

/* ---------- Environment ---------- */

function safeAreaInsets(): string {
  const cs = getComputedStyle(mustGet("safe-probe"));
  return `top ${cs.paddingTop}, right ${cs.paddingRight}, bottom ${cs.paddingBottom}, left ${cs.paddingLeft}`;
}

function environment(): Record<string, string> {
  return {
    "User agent": navigator.userAgent,
    Viewport: `${window.innerWidth} x ${window.innerHeight}`,
    Screen: `${screen.width} x ${screen.height}`,
    "Pixel ratio": String(window.devicePixelRatio),
    "Max touch points": String(navigator.maxTouchPoints),
    "Coarse pointer": String(window.matchMedia("(pointer: coarse)").matches),
    "Pointer events": String("PointerEvent" in window),
    "Visual viewport": String(Boolean(window.visualViewport)),
    Vibration: String("vibrate" in navigator),
    "Secure context": String(window.isSecureContext),
    "Safe area": safeAreaInsets(),
    "Letter key": state.keyMetrics?.letterKey ?? "not measured yet",
    "Space key": state.keyMetrics?.spaceKey ?? "not measured yet",
    Keyboard: state.keyMetrics?.keyboard ?? "not measured yet",
  };
}

function measureKeys(): void {
  const size = (r: DOMRect): string => `${r.width.toFixed(1)} x ${r.height.toFixed(1)} px`;
  const letter = keyboard.querySelector('.key[data-code="KeyA"]');
  const space = keyboard.querySelector('.key[data-code="Space"]');
  if (!letter || !space) return;
  state.keyMetrics = {
    letterKey: size(letter.getBoundingClientRect()),
    spaceKey: size(space.getBoundingClientRect()),
    keyboard: size(keyboard.getBoundingClientRect()),
  };
}

/* ---------- Keyboard and capture ---------- */

function buildKeyboard(): void {
  const rows = ROWS.map(
    (row) =>
      `<div class="kb-row">${[...row].map((c) => `<div class="key" data-code="${codeFor(c)}">${c}</div>`).join("")}</div>`,
  ).join("");
  keyboard.innerHTML = `<div class="kb">${rows}<div class="kb-row"><div class="key space" data-code="Space">space</div></div></div>`;
}

function startRun(): void {
  state.run = {
    position: 0,
    wrong: 0,
    records: [],
    disturbances: noDisturbances(),
    touchStarts: 0,
    touchEnds: 0,
    armed: false,
    finished: false,
    held: new Set(),
  };
  state.view = "typing";
  state.copied = false;
  window.scrollTo(0, 0);
  keyboard.hidden = false;
  document.body.classList.add("typing");
  render();
  measureKeys();
}

function finishRun(): void {
  const run = state.run;
  if (!run) return;
  state.lines.push({
    line: state.lines.length + 1,
    completed: run.position === PHRASE.length,
    wrong: run.wrong,
    analysis: analyze(run.records),
    records: run.records,
    disturbances: run.disturbances,
    touchStarts: run.touchStarts,
    touchEnds: run.touchEnds,
  });
  state.run = null;
  keyboard.hidden = true;
  document.body.classList.remove("typing");
  state.view = "report";
  render();
  window.scrollTo(0, 0);
}

function drawPhrase(oops = false): void {
  const run = state.run;
  const phrase = document.getElementById("phrase");
  if (!run || !phrase) return;
  const i = run.position;
  phrase.classList.toggle("oops", oops);
  const current = PHRASE[i];
  phrase.innerHTML =
    `<span>${PHRASE.slice(0, i)}</span>` +
    (current !== undefined
      ? `<span class="cur">${current === " " ? "&nbsp;" : current}</span><span class="todo">${PHRASE.slice(i + 1)}</span>`
      : "");
  const live = document.getElementById("live");
  if (live) {
    const downs = run.records.filter((r) => r.phase === "down").length;
    live.textContent = `${downs} taps, ${run.wrong} wrong`;
  }
}

keyboard.addEventListener("pointerdown", (e) => {
  e.preventDefault();
  const run = state.run;
  if (!run) return;
  run.armed = true;
  const key = e.target instanceof Element ? e.target.closest<HTMLElement>(".key") : null;
  const code = key?.dataset.code ?? null;
  try {
    // Optional: absent on iOS, and must never be relied on.
    navigator.vibrate?.(6);
  } catch {
    /* Haptics are a nicety; a refusal changes nothing measured here. */
  }

  let dx: number | null = null;
  let dy: number | null = null;
  const unit = keyboard.querySelector('.key[data-code="KeyA"]')?.getBoundingClientRect();
  if (key && unit) {
    // Normalized to a letter key, so offsets don't depend on screen size.
    const box = key.getBoundingClientRect();
    dx = (e.clientX - (box.left + box.width / 2)) / unit.width;
    dy = (e.clientY - (box.top + box.height / 2)) / unit.height;
    key.classList.add("down");
    key.dataset.pointer = String(e.pointerId);
  }

  let outcome: TapOutcome;
  if (run.finished) outcome = "idle";
  else if (code === null) outcome = "between";
  else if (code === codeFor(PHRASE[run.position] ?? "")) outcome = "ok";
  else outcome = "wrong";

  run.held.add(e.pointerId);
  run.records.push({
    phase: "down",
    pointerId: e.pointerId,
    pointerType: e.pointerType,
    t: e.timeStamp,
    trusted: e.isTrusted,
    code,
    dx,
    dy,
    outcome,
  });

  if (outcome === "ok") {
    run.position += 1;
    if (run.position === PHRASE.length) {
      run.finished = true;
      window.setTimeout(finishRun, FINAL_LIFT_WAIT_MS);
    }
    drawPhrase();
  } else if (outcome === "wrong" || outcome === "between") {
    run.wrong += 1;
    drawPhrase(true);
  }
});

function release(e: PointerEvent): void {
  keyboard.querySelectorAll<HTMLElement>(".key.down").forEach((k) => {
    if (k.dataset.pointer === String(e.pointerId)) k.classList.remove("down");
  });
  const run = state.run;
  if (!run || !run.armed) return;
  // A lift belongs in the log if its finger landed on the keyboard, or
  // if it ends on the keyboard with no landing (a lost down). A tap on
  // a button elsewhere on the page is neither.
  const landedHere = run.held.delete(e.pointerId);
  const endsHere = e.target instanceof Node && keyboard.contains(e.target);
  if (!landedHere && !endsHere) return;
  run.records.push({
    phase: e.type === "pointercancel" ? "cancel" : "up",
    pointerId: e.pointerId,
    pointerType: e.pointerType,
    t: e.timeStamp,
    trusted: e.isTrusted,
    code: null,
    dx: null,
    dy: null,
    outcome: null,
  });
}
// On the document, so a finger that slides off the keyboard still ends its tap.
document.addEventListener("pointerup", release);
document.addEventListener("pointercancel", release);

/* ---------- Disturbances ---------- */

function disturb(kind: keyof Disturbances): void {
  const run = state.run;
  if (run?.armed) run.disturbances[kind] += 1;
}

// Passive touch listeners only count; they cross-check the pointer
// events without changing how the browser handles the touch.
keyboard.addEventListener(
  "touchstart",
  (e) => {
    if (state.run) state.run.touchStarts += e.changedTouches.length;
  },
  { passive: true },
);
keyboard.addEventListener(
  "touchend",
  (e) => {
    if (state.run) state.run.touchEnds += e.changedTouches.length;
  },
  { passive: true },
);
keyboard.addEventListener(
  "touchcancel",
  (e) => {
    if (state.run) state.run.touchEnds += e.changedTouches.length;
    disturb("touchCancel");
  },
  { passive: true },
);
keyboard.addEventListener("contextmenu", (e) => e.preventDefault());
document.addEventListener("contextmenu", () => disturb("callout"), true);
window.addEventListener("scroll", () => disturb("scroll"), { passive: true });
document.addEventListener("selectionchange", () => {
  const selection = document.getSelection();
  if (selection && !selection.isCollapsed) disturb("selection");
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) disturb("pageHidden");
});
// Safari-only pinch gesture event.
document.addEventListener("gesturestart", () => disturb("zoom"));
if (window.visualViewport) {
  const viewport = window.visualViewport;
  viewport.addEventListener("resize", () => {
    disturb(Math.abs(viewport.scale - 1) > 0.01 ? "zoom" : "viewportResize");
  });
} else {
  window.addEventListener("resize", () => disturb("viewportResize"));
}

/* ---------- Report ---------- */

const ms = (v: number | null): string => (v === null ? "-" : v.toFixed(1));
/** Two decimals, without the "-0.00" a tiny negative would print. */
const keys = (v: number): string => (Math.abs(v) < 0.005 ? "0.00" : v.toFixed(2));
const off = (v: number | null): string => (v === null ? "-" : keys(v));
const range = (s: Spread | null, fmt: (v: number) => string): string =>
  s === null ? "no data" : `${fmt(s.min)} / ${fmt(s.median)} / ${fmt(s.max)}`;
const numbers = (values: (number | null)[]): number[] =>
  values.filter((v): v is number => v !== null);

interface Check {
  name: string;
  value: string;
  /** Null for a measurement with no pass/fail meaning. */
  ok: boolean | null;
}

function checks(r: LineReport): Check[] {
  const { taps, problems } = r.analysis;
  const touchDowns = r.records.filter((x) => x.phase === "down" && x.pointerType === "touch").length;
  const touchEnds = r.records.filter((x) => x.phase !== "down" && x.pointerType === "touch").length;
  const incomplete = taps.filter((t) => t.events !== 2).length;
  const canceled = taps.filter((t) => t.canceled).length;
  const orderProblems = problems.filter((p) => p.kind !== "untrusted");
  const untrusted = problems.length - orderProblems.length;
  const types = [...new Set(r.records.map((x) => x.pointerType || "unknown"))].join(", ");
  const step = timestampStep(r.records);
  const d = r.disturbances;
  const count = (n: number): Check["ok"] => n === 0;
  return [
    {
      name: "Line",
      value: r.completed ? `completed, ${PHRASE.length} keys` : "stopped early",
      ok: r.completed,
    },
    {
      name: "Taps recorded",
      value: `${taps.length} (${taps.filter((t) => t.outcome === "ok").length} right, ${r.wrong} wrong or between keys)`,
      ok: null,
    },
    {
      name: "Events per tap",
      value: incomplete === 0 ? "2 for every tap" : `${incomplete} taps without an end event`,
      ok: incomplete === 0,
    },
    {
      name: "Lost or out of order",
      value: orderProblems.length === 0 ? "none" : orderProblems.map((p) => p.detail).join("; "),
      ok: orderProblems.length === 0,
    },
    {
      name: "Pointer vs touch events",
      value: `down ${touchDowns} / touchstart ${r.touchStarts}, end ${touchEnds} / touchend ${r.touchEnds}`,
      // Lifts off the keyboard still reach touchend, but a tap that
      // began before the first counted one can skew ends by design.
      ok: touchDowns === r.touchStarts,
    },
    { name: "Canceled touches", value: String(canceled + d.touchCancel), ok: count(canceled + d.touchCancel) },
    { name: "Scrolling", value: String(d.scroll), ok: count(d.scroll) },
    { name: "Zooming", value: String(d.zoom), ok: count(d.zoom) },
    { name: "Text selection", value: String(d.selection), ok: count(d.selection) },
    { name: "Callouts or menus", value: String(d.callout), ok: count(d.callout) },
    { name: "Page hidden", value: String(d.pageHidden), ok: count(d.pageHidden) },
    { name: "Viewport resized", value: String(d.viewportResize), ok: count(d.viewportResize) },
    { name: "Untrusted events", value: String(untrusted), ok: count(untrusted) },
    { name: "Pointer types", value: types || "none", ok: null },
    {
      name: "Hold ms (min / median / max)",
      value: range(spread(numbers(taps.map((t) => t.holdMs))), (v) => v.toFixed(1)),
      ok: null,
    },
    {
      name: "Gap ms (min / median / max)",
      value: range(spread(numbers(taps.map((t) => t.gapMs))), (v) => v.toFixed(1)),
      ok: null,
    },
    {
      name: "Offset x, in keys (min / median / max)",
      value: range(spread(numbers(taps.map((t) => t.dx))), keys),
      ok: null,
    },
    {
      name: "Offset y, in keys (min / median / max)",
      value: range(spread(numbers(taps.map((t) => t.dy))), keys),
      ok: null,
    },
    {
      name: "Overlapping taps",
      value: String(taps.filter((t) => t.overlapped).length),
      ok: null,
    },
    {
      name: "Smallest time step",
      value: step === null ? "no data" : `${step.toFixed(3)} ms`,
      ok: null,
    },
  ];
}

function exportJSON(): string {
  const round = (v: number | null, places: number): number | null =>
    v === null ? null : Number(v.toFixed(places));
  return JSON.stringify(
    {
      page: "touch-capture",
      line: PHRASE,
      environment: environment(),
      lines: state.lines.map((r) => ({
        line: r.line,
        completed: r.completed,
        wrong: r.wrong,
        touchStarts: r.touchStarts,
        touchEnds: r.touchEnds,
        disturbances: r.disturbances,
        problems: r.analysis.problems,
        checks: checks(r).map((c) => ({ name: c.name, value: c.value, ok: c.ok })),
        taps: r.analysis.taps.map((t) => ({
          key: labelFor(t.code),
          outcome: t.outcome,
          pointerType: t.pointerType,
          holdMs: round(t.holdMs, 1),
          gapMs: round(t.gapMs, 1),
          dx: round(t.dx, 3),
          dy: round(t.dy, 3),
          events: t.events,
          canceled: t.canceled,
          overlapped: t.overlapped,
        })),
      })),
    },
    null,
    1,
  );
}

function environmentTable(): string {
  const rows = Object.entries(environment())
    .map(([k, v]) => `<tr><th scope="row">${esc(k)}</th><td class="wrap-cell">${esc(v)}</td></tr>`)
    .join("");
  return `<div class="table-box"><table><tbody>${rows}</tbody></table></div>`;
}

function readyView(): string {
  return `<section class="stack">
    <div class="eyebrow">Debug only</div>
    <h2>Touch capture test</h2>
    <p>Type the line on the on-page keyboard with your normal grip. Afterwards this page shows what the browser delivered for every tap.</p>
    <p class="small muted">Nothing is sent or saved. Refreshing erases it.</p>
    <button class="primary" id="start">Start a line</button>
    <h3>This device</h3>
    ${environmentTable()}
  </section>`;
}

function typingView(): string {
  return `<section class="stack">
    <div class="eyebrow">Line ${state.lines.length + 1}</div>
    <div class="phrase" id="phrase"></div>
    <div class="row small muted" style="justify-content:space-between"><span>Use your normal grip</span><span id="live"></span></div>
    <button class="quiet" id="stop" style="align-self:flex-start">Stop and show results</button>
  </section>`;
}

function reportView(): string {
  const r = state.lines[state.lines.length - 1];
  if (!r) return readyView();
  const all = checks(r);
  const failed = all.filter((c) => c.ok === false).length;
  const checkRows = all
    .map((c) => {
      const mark = c.ok === null ? "" : c.ok ? "OK" : "CHECK";
      return `<tr${c.ok === false ? ' class="flag"' : ""}><th scope="row">${esc(c.name)}</th><td class="wrap-cell">${esc(c.value)}</td><td>${mark}</td></tr>`;
    })
    .join("");
  const tapRows = r.analysis.taps
    .map((t) => {
      const notes = [
        t.outcome === "ok" ? "" : (t.outcome ?? ""),
        t.canceled ? "canceled" : "",
        t.events !== 2 ? "no end event" : "",
        t.overlapped ? "overlap" : "",
        t.pointerType === "touch" ? "" : t.pointerType,
      ]
        .filter(Boolean)
        .join(", ");
      return `<tr><td>${t.index + 1}</td><td>${esc(labelFor(t.code))}</td><td>${ms(t.holdMs)}</td><td>${ms(t.gapMs)}</td><td>${off(t.dx)}</td><td>${off(t.dy)}</td><td>${t.events}</td><td>${esc(notes)}</td></tr>`;
    })
    .join("");
  return `<section class="stack" id="report" data-failed="${failed}">
    <div class="eyebrow">Line ${r.line} of ${state.lines.length}</div>
    <h2>${failed === 0 ? "Nothing to flag" : `${failed} to check`}</h2>
    <div class="row"><button class="primary" id="start">Type another line</button><button id="copy">${state.copied ? "Copied" : "Copy results"}</button></div>
    <div class="table-box"><table><thead><tr><th>Check</th><th>Result</th><th></th></tr></thead><tbody>${checkRows}</tbody></table></div>
    <h3>Every tap</h3>
    <div class="table-box"><table><thead><tr><th>#</th><th>Key</th><th>Hold ms</th><th>Gap ms</th><th>dx</th><th>dy</th><th>Events</th><th>Notes</th></tr></thead><tbody>${tapRows}</tbody></table></div>
    <h3>This device</h3>
    ${environmentTable()}
    <label for="export">Results for all ${state.lines.length} lines, to paste back. If Copy doesn't work, select this text by hand.<textarea id="export" readonly>${esc(exportJSON())}</textarea></label>
  </section>`;
}

function render(): void {
  app.innerHTML = { ready: readyView, typing: typingView, report: reportView }[state.view]();
  if (state.view === "typing") drawPhrase();
}

document.addEventListener("click", (e) => {
  const button = e.target instanceof Element ? e.target.closest("button") : null;
  if (!button) return;
  if (button.id === "start") startRun();
  else if (button.id === "stop") finishRun();
  else if (button.id === "copy") {
    const done = (): void => {
      state.copied = true;
      button.textContent = "Copied";
    };
    // The clipboard API exists only on HTTPS or localhost, so over a
    // plain-HTTP LAN address fall back to selecting the text.
    const fallback = (): void => {
      const box = document.getElementById("export");
      if (box instanceof HTMLTextAreaElement) {
        box.focus();
        box.select();
      }
    };
    if (navigator.clipboard) navigator.clipboard.writeText(exportJSON()).then(done, fallback);
    else fallback();
  }
});

buildKeyboard();
render();
