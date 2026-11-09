import { expect, test, type CDPSession, type Page } from "@playwright/test";

/**
 * The debug-only capture test page (docs/plans/active/MOBILE_PLAN.md Phase 0), driven
 * with emulated touches through Chromium's Input.dispatchTouchEvent.
 * Needs the app running with DEBUG=true, which is the only mode the
 * page exists in.
 *
 * This is emulation: it proves the page's own logic, not how a real
 * phone browser delivers touches. That's what the page is for.
 */

const PHRASE = "tap the rhythm of your thumbs";
const PATH = "/debug/touch-capture";

test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

const codeFor = (ch: string): string => (ch === " " ? "Space" : `Key${ch.toUpperCase()}`);

interface Point {
  x: number;
  y: number;
  id: number;
}

/** A point on a key, offset from its center in letter-key widths/heights. */
async function pointOn(page: Page, code: string, id: number, fx = 0, fy = 0): Promise<Point> {
  const key = await page.locator(`.key[data-code="${code}"]`).boundingBox();
  const unit = await page.locator('.key[data-code="KeyA"]').boundingBox();
  if (!key || !unit) throw new Error(`key ${code} is not on screen`);
  return {
    x: key.x + key.width / 2 + fx * unit.width,
    y: key.y + key.height / 2 + fy * unit.height,
    id,
  };
}

async function touch(
  cdp: CDPSession,
  type: "touchStart" | "touchEnd" | "touchCancel",
  points: Point[],
): Promise<void> {
  await cdp.send("Input.dispatchTouchEvent", {
    type,
    touchPoints: points.map((p) => ({ x: p.x, y: p.y, id: p.id })),
  });
}

async function tap(page: Page, cdp: CDPSession, code: string, fx = 0, fy = 0): Promise<void> {
  const point = await pointOn(page, code, 0, fx, fy);
  await touch(cdp, "touchStart", [point]);
  await page.waitForTimeout(20);
  await touch(cdp, "touchEnd", []);
  await page.waitForTimeout(15);
}

interface ExportedTap {
  key: string;
  outcome: string;
  pointerType: string;
  holdMs: number | null;
  gapMs: number | null;
  dx: number | null;
  dy: number | null;
  events: number;
  canceled: boolean;
  overlapped: boolean;
}

interface ExportedLine {
  completed: boolean;
  wrong: number;
  touchStarts: number;
  problems: { kind: string }[];
  disturbances: Record<string, number>;
  checks: { name: string; ok: boolean | null }[];
  taps: ExportedTap[];
}

async function lastLine(page: Page): Promise<ExportedLine> {
  const exported = JSON.parse(await page.locator("#export").inputValue()) as {
    lines: ExportedLine[];
  };
  const line = exported.lines[exported.lines.length - 1];
  if (!line) throw new Error("no line in the export");
  return line;
}

test("a typed line reports every tap with its timing and offset, and sends nothing", async ({
  page,
  baseURL,
}) => {
  const ownHost = new URL(baseURL ?? "http://127.0.0.1:8000").host;
  const requests: { method: string; url: URL }[] = [];
  page.on("request", (r) => requests.push({ method: r.method(), url: new URL(r.url()) }));
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });

  await page.goto(PATH);
  await page.click("#start");
  await expect(page.locator("#keyboard")).toBeVisible();
  const cdp = await page.context().newCDPSession(page);

  for (const ch of PHRASE) await tap(page, cdp, codeFor(ch), 0.25, -0.2);

  await expect(page.locator("#report")).toBeVisible();
  await expect(page.locator("#report")).toHaveAttribute("data-failed", "0");
  await expect(page.locator("#keyboard")).toBeHidden();

  const line = await lastLine(page);
  expect(line.completed).toBe(true);
  expect(line.wrong).toBe(0);
  expect(line.problems).toEqual([]);
  expect(line.taps).toHaveLength(PHRASE.length);
  expect(line.touchStarts).toBe(PHRASE.length);
  expect(line.taps.map((t) => t.key).join("")).toBe(PHRASE.replaceAll(" ", "space"));
  for (const [i, t] of line.taps.entries()) {
    expect(t.events).toBe(2);
    expect(t.pointerType).toBe("touch");
    expect(t.outcome).toBe("ok");
    expect(t.holdMs).toBeGreaterThan(0);
    if (i > 0) expect(t.gapMs).toBeGreaterThan(0);
    // Touch coordinates snap to whole pixels, hence the tolerance.
    expect(t.dx).toBeCloseTo(0.25, 1);
    expect(t.dy).toBeCloseTo(-0.2, 1);
  }
  expect(Object.values(line.disturbances).every((n) => n === 0)).toBe(true);

  expect(errors).toEqual([]);
  expect(requests.length).toBeGreaterThan(0);
  for (const r of requests) {
    expect(r.url.host).toBe(ownHost);
    expect(r.method).toBe("GET");
    expect(r.url.pathname.startsWith("/api/")).toBe(false);
  }
});

test("overlapping fingers, a wrong key, and a canceled touch are each reported", async ({
  page,
}) => {
  await page.goto(PATH);
  await page.click("#start");
  const cdp = await page.context().newCDPSession(page);

  // Two thumbs: "t" lands, "a" lands before "t" lifts, then "t" lifts first.
  const t = await pointOn(page, "KeyT", 0);
  const a = await pointOn(page, "KeyA", 1);
  await touch(cdp, "touchStart", [t]);
  await page.waitForTimeout(20);
  await touch(cdp, "touchStart", [t, a]);
  await page.waitForTimeout(20);
  await touch(cdp, "touchEnd", [a]);
  await page.waitForTimeout(20);
  await touch(cdp, "touchEnd", []);
  await page.waitForTimeout(20);

  // A wrong key: the line expects "p" next.
  await tap(page, cdp, "KeyQ");
  await expect(page.locator("#phrase")).toHaveClass(/oops/);

  // The right key, but the browser cancels the touch.
  const p = await pointOn(page, "KeyP", 0);
  await touch(cdp, "touchStart", [p]);
  await page.waitForTimeout(20);
  await touch(cdp, "touchCancel", []);
  await page.waitForTimeout(20);

  await page.click("#stop");
  await expect(page.locator("#report")).toBeVisible();

  const line = await lastLine(page);
  expect(line.completed).toBe(false);
  expect(line.taps.map((x) => x.key)).toEqual(["t", "a", "q", "p"]);
  expect(line.taps.map((x) => x.overlapped)).toEqual([false, true, false, false]);
  expect(line.taps.map((x) => x.outcome)).toEqual(["ok", "ok", "wrong", "ok"]);
  expect(line.taps.map((x) => x.canceled)).toEqual([false, false, false, true]);
  expect(line.taps[3]?.holdMs).toBeNull();
  expect(line.taps.every((x) => x.events === 2)).toBe(true);
  expect(line.wrong).toBe(1);
  // A cancel is a complete, if unusable, tap -- not a lost event.
  expect(line.problems).toEqual([]);
  const failed = line.checks.filter((c) => c.ok === false).map((c) => c.name);
  expect(failed).toEqual(["Line", "Canceled touches"]);
});

for (const width of [320, 390, 430]) {
  test(`fits ${width} px with no sideways scroll`, async ({ page }) => {
    await page.setViewportSize({ width, height: 700 });
    await page.goto(PATH);
    const overflow = (): Promise<number> =>
      page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(await overflow()).toBeLessThanOrEqual(0);

    await page.click("#start");
    expect(await overflow()).toBeLessThanOrEqual(0);
    for (const key of await page.locator(".key").all()) {
      const box = await key.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(width);
    }

    await page.click("#stop");
    await expect(page.locator("#report")).toBeVisible();
    expect(await overflow()).toBeLessThanOrEqual(0);
  });
}
