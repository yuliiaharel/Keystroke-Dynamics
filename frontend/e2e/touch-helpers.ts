import { expect, type BrowserContext, type BrowserContextOptions, type CDPSession, type Page } from "@playwright/test";

import { post } from "./room-helpers";

/**
 * Shared by the touch game's specs (docs/plans/active/MOBILE_PLAN.md
 * Phase 2). Touches are emulated through Chromium's
 * Input.dispatchTouchEvent, which the browser turns into trusted
 * pointer events of type "touch" -- the events the game listens for.
 *
 * This is emulation: it proves the page's own logic, not how a real
 * phone's browser delivers touches.
 */

export const TOUCH_PHRASE = "tap the rhythm of your thumbs";

/** A phone, as the game detects one: a coarse main pointer. */
export const PHONE: BrowserContextOptions = {
  viewport: { width: 390, height: 844 },
  hasTouch: true,
  isMobile: true,
};

export const codeFor = (ch: string): string => (ch === " " ? "Space" : `Key${ch.toUpperCase()}`);

/** Where a typist's taps land, in letter-key widths and heights from
 * each key's center, and how they're timed. */
export interface Habit {
  fx: number;
  fy: number;
  holdMs: number;
  gapMs: number;
}

export const ADA: Habit = { fx: 0.22, fy: -0.2, holdMs: 30, gapMs: 30 };
/** Lands nearly half a key away from ADA on every tap, so the Place
 * score alone puts an attack on ADA far outside any limit. */
export const BOB: Habit = { fx: -0.22, fy: 0.24, holdMs: 30, gapMs: 30 };

interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Every key's box, read once: the keyboard doesn't move mid-line. */
async function keyBoxes(page: Page): Promise<Record<string, Box>> {
  await expect(page.locator("#keyboard")).toBeVisible();
  return page.evaluate(() => {
    const boxes: Record<string, { x: number; y: number; width: number; height: number }> = {};
    document.querySelectorAll<HTMLElement>("#keyboard .key").forEach((key) => {
      const r = key.getBoundingClientRect();
      boxes[key.dataset.code!] = { x: r.x, y: r.y, width: r.width, height: r.height };
    });
    return boxes;
  });
}

export interface Point {
  x: number;
  y: number;
  id: number;
}

function pointIn(boxes: Record<string, Box>, code: string, id: number, fx: number, fy: number): Point {
  const key = boxes[code];
  const unit = boxes.KeyA;
  if (!key || !unit) throw new Error(`key ${code} is not on screen`);
  return { x: key.x + key.width / 2 + fx * unit.width, y: key.y + key.height / 2 + fy * unit.height, id };
}

/** A point on a key, offset from its center in letter-key widths/heights. */
export async function pointOn(page: Page, code: string, id: number, fx = 0, fy = 0): Promise<Point> {
  return pointIn(await keyBoxes(page), code, id, fx, fy);
}

export async function touch(
  cdp: CDPSession,
  type: "touchStart" | "touchEnd" | "touchCancel",
  points: Point[],
): Promise<void> {
  await cdp.send("Input.dispatchTouchEvent", {
    type,
    touchPoints: points.map((p) => ({ x: p.x, y: p.y, id: p.id })),
  });
}

export const cdpFor = (page: Page): Promise<CDPSession> => page.context().newCDPSession(page);

/** One finger down and up on a key. */
export async function tapKey(page: Page, cdp: CDPSession, code: string, habit: Habit = ADA): Promise<void> {
  const point = await pointOn(page, code, 0, habit.fx, habit.fy);
  await touch(cdp, "touchStart", [point]);
  await page.waitForTimeout(habit.holdMs);
  await touch(cdp, "touchEnd", []);
  await page.waitForTimeout(habit.gapMs);
}

/** Taps `text` (the whole line by default), one finger at a time. */
export async function tapText(
  page: Page,
  cdp: CDPSession,
  habit: Habit = ADA,
  text: string = TOUCH_PHRASE,
): Promise<void> {
  const boxes = await keyBoxes(page);
  for (const ch of text) {
    await touch(cdp, "touchStart", [pointIn(boxes, codeFor(ch), 0, habit.fx, habit.fy)]);
    await page.waitForTimeout(habit.holdMs);
    await touch(cdp, "touchEnd", []);
    await page.waitForTimeout(habit.gapMs);
  }
}

/** How far into the line the page says the typist is. */
export const typedSoFar = (page: Page): Promise<string> =>
  page.locator("#phrase > span").first().innerText();

/** Enrolls a player the way a person does on a phone: the name step,
 * five tapped lines, and the reveal. Leaves the page on the reveal. */
export async function enrollByTapping(page: Page, cdp: CDPSession, name: string, habit: Habit = ADA): Promise<void> {
  await page.fill("#player-name", name);
  await page.click("#name-form button[type=submit]");
  for (let i = 0; i < 5; i++) {
    await expect(page.locator(".dots .dot.on")).toHaveText(i === 0 ? "Warm-up" : String(i));
    await tapText(page, cdp, habit);
  }
  await expect(page.locator("h2", { hasText: "This is how you tap." })).toBeVisible({ timeout: 10_000 });
}

/** One clean line as the touch game sends it, for tests that enroll
 * through the API to keep the tapping out of the way. */
export function tapLineEvents(habit: Habit = ADA, wobble = 0): unknown[] {
  return [...TOUCH_PHRASE].flatMap((ch, i) => {
    const code = codeFor(ch);
    const t = i * 150 + wobble * (i % 3);
    return [
      { code, action: "down", t_ms: t, dx: habit.fx + wobble * 0.001, dy: habit.fy - wobble * 0.001 },
      { code, action: "up", t_ms: t + 80 },
    ];
  });
}

/** Creates a touch room for `context`, as a phone's page would. */
export const createTouchRoom = (context: BrowserContext, baseURL: string): Promise<any> =>
  post(context.request, baseURL, "/api/game/rooms", { level: "touch", device_type: "touch", viewport_width: 390 });

export const joinAsTouch = (context: BrowserContext, baseURL: string, code: string): Promise<any> =>
  post(context.request, baseURL, `/api/game/rooms/${code}/join`, { device_type: "touch", viewport_width: 390 });

export const enrollTouchByApi = (
  context: BrowserContext,
  baseURL: string,
  name: string,
  habit: Habit = ADA,
): Promise<any> =>
  post(context.request, baseURL, "/api/game/players", {
    name,
    training_lines: [0, 1, 2, 3].map((i) => tapLineEvents(habit, i)),
  });

/** The page never scrolls sideways. */
export const sidewaysOverflow = (page: Page): Promise<number> =>
  page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
