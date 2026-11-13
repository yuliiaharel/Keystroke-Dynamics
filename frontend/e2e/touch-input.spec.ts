import { expect, test, type BrowserContext, type Page } from "@playwright/test";

import { card } from "./room-helpers";
import {
  ADA,
  PHONE,
  TOUCH_PHRASE,
  cdpFor,
  codeFor,
  createTouchRoom,
  enrollTouchByApi,
  pointOn,
  tapKey,
  tapText,
  touch,
  typedSoFar,
} from "./touch-helpers";

/**
 * How the touch game treats what a real thumb does
 * (docs/plans/active/MOBILE_PLAN.md Phase 2 sections 2 and 4):
 * overlapping fingers, a canceled touch, wrong keys, a mouse, a phone
 * turned on its side, and a line cut short by switching apps or
 * losing the connection.
 *
 * Each test starts on the attack view of a room whose one player was
 * enrolled through the API, so the only taps are the ones under test.
 */

test.use(PHONE);

interface SentEvent {
  code: string;
  action: "down" | "up";
  t_ms: number;
  dx?: number;
  dy?: number;
}

/** A phone in a touch room with Ada enrolled, about to attack her as Guest. */
async function onTheAttackView(context: BrowserContext, baseURL: string): Promise<Page> {
  await createTouchRoom(context, baseURL);
  await enrollTouchByApi(context, baseURL, "Ada");
  const page = await context.newPage();
  await page.goto("/party");
  await card(page, "Ada").locator("[data-attack]").click();
  await page.selectOption("#who", { label: "Guest" });
  await expect(page.locator("#keyboard")).toBeVisible();
  return page;
}

const attempts = async (page: Page): Promise<unknown[]> =>
  (await page.evaluate(() => fetch("/api/game/room").then((r) => r.json()))).attempts;

test("two thumbs that overlap are told apart, and the line is sent whole and in time order", async ({
  context,
  baseURL,
}) => {
  const page = await onTheAttackView(context, baseURL!);
  const cdp = await cdpFor(page);
  const sent: SentEvent[][] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/api/game/attempts")) sent.push(r.postDataJSON().events);
  });

  // "t" lands, "a" lands before "t" lifts, then "t" lifts first.
  const t = await pointOn(page, "KeyT", 0, ADA.fx, ADA.fy);
  const a = await pointOn(page, "KeyA", 1, ADA.fx, ADA.fy);
  await touch(cdp, "touchStart", [t]);
  await page.waitForTimeout(25);
  await touch(cdp, "touchStart", [t, a]);
  await expect(page.locator('.key[data-code="KeyT"]')).toHaveClass(/down/);
  await expect(page.locator('.key[data-code="KeyA"]')).toHaveClass(/down/);
  await page.waitForTimeout(25);
  // Chromium lifts the points a touchEnd names, then any that are left.
  await touch(cdp, "touchEnd", [t]);
  await expect(page.locator('.key[data-code="KeyT"]')).not.toHaveClass(/down/);
  await expect(page.locator('.key[data-code="KeyA"]')).toHaveClass(/down/);
  await page.waitForTimeout(25);
  await touch(cdp, "touchEnd", []);
  await expect(page.locator('.key[data-code="KeyA"]')).not.toHaveClass(/down/);
  expect(await typedSoFar(page)).toBe("ta");
  await expect(page.locator("#typos")).toHaveText("0 wrong keys");

  await tapText(page, cdp, ADA, TOUCH_PHRASE.slice(2));
  await expect(page.locator("#result")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator("#result .verdict")).not.toHaveText("Too messy");

  expect(sent).toHaveLength(1);
  const events = sent[0]!;
  // A down and an up for every character, nothing dropped.
  expect(events).toHaveLength(TOUCH_PHRASE.length * 2);
  expect(events.filter((e) => e.action === "down").map((e) => e.code)).toEqual([...TOUCH_PHRASE].map(codeFor));
  // The overlap, exactly as it happened.
  expect(events.slice(0, 4).map((e) => `${e.code} ${e.action}`)).toEqual([
    "KeyT down",
    "KeyA down",
    "KeyT up",
    "KeyA up",
  ]);
  for (const [i, e] of events.entries()) {
    if (i > 0) expect(e.t_ms).toBeGreaterThanOrEqual(events[i - 1]!.t_ms);
    if (e.action === "down") {
      // Offsets in letter-key widths and heights. Touch coordinates
      // snap to whole pixels, hence the tolerance.
      expect(e.dx).toBeCloseTo(ADA.fx, 1);
      expect(e.dy).toBeCloseTo(ADA.fy, 1);
    } else {
      expect(e).not.toHaveProperty("dx");
      expect(e).not.toHaveProperty("dy");
    }
  }
});

test("a canceled touch can't be scored: the line starts again and says why", async ({ context, baseURL }) => {
  const page = await onTheAttackView(context, baseURL!);
  const cdp = await cdpFor(page);
  let posts = 0;
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().includes("/api/game/")) posts++;
  });

  await tapText(page, cdp, ADA, "tap ");
  expect(await typedSoFar(page)).toBe("tap ");

  // The right key, but the browser takes the touch away.
  await touch(cdp, "touchStart", [await pointOn(page, "KeyT", 0)]);
  await page.waitForTimeout(20);
  await touch(cdp, "touchCancel", []);

  await expect(page.locator("#tap-status")).toHaveText("That touch was interrupted, so this line starts again.");
  expect(await typedSoFar(page)).toBe("");
  await expect(page.locator('.key[data-code="KeyT"]')).not.toHaveClass(/down/);
  await expect(page.locator("#keyboard")).toBeVisible();
  expect(posts).toBe(0);

  // The notice goes once the new line is under way, and that line scores.
  await tapKey(page, cdp, "KeyT");
  await expect(page.locator("#tap-status")).toBeHidden();
  await tapText(page, cdp, ADA, TOUCH_PHRASE.slice(1));
  await expect(page.locator("#result")).toBeVisible({ timeout: 10_000 });
  expect(await attempts(page)).toHaveLength(1);
});

test("a wrong key shows an error, doesn't advance, and isn't sent", async ({ context, baseURL }) => {
  const page = await onTheAttackView(context, baseURL!);
  const cdp = await cdpFor(page);
  const sent: SentEvent[][] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/api/game/attempts")) sent.push(r.postDataJSON().events);
  });

  await tapKey(page, cdp, "KeyT");
  await tapKey(page, cdp, "KeyQ"); // the line wants "a"
  await expect(page.locator("#phrase")).toHaveClass(/oops/);
  await expect(page.locator("#typos")).toHaveText("1 wrong key");
  expect(await typedSoFar(page)).toBe("t");

  // Between two keys is no key at all.
  const a = await pointOn(page, "KeyA", 0);
  const s = await pointOn(page, "KeyS", 0);
  await touch(cdp, "touchStart", [{ x: (a.x + s.x) / 2, y: a.y, id: 0 }]);
  await touch(cdp, "touchEnd", []);
  await expect(page.locator("#typos")).toHaveText("2 wrong keys");
  expect(await typedSoFar(page)).toBe("t");

  // The right key clears the error and moves on.
  await tapKey(page, cdp, "KeyA");
  await expect(page.locator("#phrase")).not.toHaveClass(/oops/);
  expect(await typedSoFar(page)).toBe("ta");

  await tapText(page, cdp, ADA, TOUCH_PHRASE.slice(2));
  await expect(page.locator("#result")).toBeVisible({ timeout: 10_000 });
  expect(sent).toHaveLength(1);
  expect(sent[0]!.map((e) => e.code)).not.toContain("KeyQ");
  expect(sent[0]!).toHaveLength(TOUCH_PHRASE.length * 2);
});

test("a mouse click is refused outside debug mode, and scripted events always are", async ({
  context,
  baseURL,
}) => {
  const page = await onTheAttackView(context, baseURL!);
  const key = await pointOn(page, "KeyT", 0);

  // As the deployed site serves the page: no debug mark on the keyboard.
  await page.evaluate(() => delete document.getElementById("keyboard")!.dataset.allowMouse);
  await page.mouse.click(key.x, key.y);
  await expect(page.locator("#tap-status")).toHaveText("Tap with your fingers. A mouse click isn't a touch signature.");
  expect(await typedSoFar(page)).toBe("");

  // An event made by a script, dressed up as a touch.
  await page.evaluate(
    ([x, y]) => {
      const target = document.querySelector('.key[data-code="KeyT"]')!;
      for (const type of ["pointerdown", "pointerup"]) {
        target.dispatchEvent(
          new PointerEvent(type, { bubbles: true, pointerId: 9, pointerType: "touch", clientX: x, clientY: y }),
        );
      }
    },
    [key.x, key.y],
  );
  expect(await typedSoFar(page)).toBe("");

  // A real touch still works.
  const cdp = await cdpFor(page);
  await tapKey(page, cdp, "KeyT");
  expect(await typedSoFar(page)).toBe("t");
  await expect(page.locator("#tap-status")).toBeHidden();

  // In debug mode, a mouse may stand in for a finger.
  await page.evaluate(() => {
    document.getElementById("keyboard")!.dataset.allowMouse = "true";
  });
  const a = await pointOn(page, "KeyA", 0);
  await page.mouse.click(a.x, a.y);
  expect(await typedSoFar(page)).toBe("ta");
});

test("turning the phone on its side pauses the line, and turning back starts it again", async ({
  context,
  baseURL,
}) => {
  const page = await onTheAttackView(context, baseURL!);
  const cdp = await cdpFor(page);
  let posts = 0;
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().includes("/api/game/")) posts++;
  });

  await tapText(page, cdp, ADA, "tap the ");
  expect(await typedSoFar(page)).toBe("tap the ");

  await page.setViewportSize({ width: 844, height: 390 });
  await expect(page.locator("#tap-status")).toContainText("Turn your phone upright to keep going.");
  await expect(page.locator("#keyboard")).toBeHidden();
  expect(await typedSoFar(page)).toBe("");

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator("#keyboard")).toBeVisible();
  await expect(page.locator("#tap-status")).toHaveText("This line started again after the turn.");
  expect(await typedSoFar(page)).toBe("");
  expect(posts).toBe(0);

  // Opening a line while already on its side waits for the turn too.
  await page.click("#to-room");
  await page.setViewportSize({ width: 844, height: 390 });
  await card(page, "Ada").locator("[data-attack]").click();
  await expect(page.locator("#tap-status")).toContainText("Turn your phone upright to keep going.");
  await expect(page.locator("#keyboard")).toBeHidden();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator("#keyboard")).toBeVisible();

  await tapText(page, cdp, ADA);
  await expect(page.locator("#result")).toBeVisible({ timeout: 10_000 });
  expect(await attempts(page)).toHaveLength(1);
});

/** What a browser does when its tab is hidden or shown again. */
async function setVisibility(page: Page, state: "hidden" | "visible"): Promise<void> {
  await page.evaluate((value) => {
    Object.defineProperty(document, "visibilityState", { value, configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
  }, state);
}

test("switching away mid-line starts the line again instead of scoring part of it", async ({
  context,
  baseURL,
}) => {
  const page = await onTheAttackView(context, baseURL!);
  const cdp = await cdpFor(page);

  await tapText(page, cdp, ADA, "tap the rhythm ");
  await setVisibility(page, "hidden");
  await setVisibility(page, "visible");

  await expect(page.locator("#tap-status")).toHaveText("You switched away, so this line started again.");
  expect(await typedSoFar(page)).toBe("");
  // The rest of the old line doesn't finish it.
  await tapText(page, cdp, ADA, "of");
  await expect(page.locator("#typos")).toHaveText("2 wrong keys");
  expect(await attempts(page)).toHaveLength(0);

  // Switching away before the first tap changes nothing.
  await page.click("#to-room");
  await card(page, "Ada").locator("[data-attack]").click();
  await setVisibility(page, "hidden");
  await setVisibility(page, "visible");
  await expect(page.locator("#tap-status")).toBeHidden();
});

test("a lost connection scores nothing: the line starts again, and the next one counts once", async ({
  context,
  baseURL,
}) => {
  const page = await onTheAttackView(context, baseURL!);
  const cdp = await cdpFor(page);

  await tapText(page, cdp, ADA, TOUCH_PHRASE.slice(0, -1));
  await context.setOffline(true);
  await tapKey(page, cdp, codeFor(TOUCH_PHRASE.at(-1)!));

  await expect(page.locator(".error")).toHaveText(
    "Couldn't reach the server to score that line. Check your connection, then tap it again.",
  );
  await expect(page.locator("#result")).toHaveCount(0);
  await expect(page.locator("#keyboard")).toBeVisible();
  expect(await typedSoFar(page)).toBe("");

  await context.setOffline(false);
  expect(await attempts(page)).toHaveLength(0);
  await tapText(page, cdp, ADA);
  await expect(page.locator("#result")).toBeVisible({ timeout: 10_000 });
  expect(await attempts(page)).toHaveLength(1);
});

test("a lost connection at the end of enrollment keeps the lines, and the retry sends a full set", async ({
  context,
  baseURL,
}) => {
  await createTouchRoom(context, baseURL!);
  const page = await context.newPage();
  await page.goto("/party");
  await page.click("#add-player");
  await page.fill("#player-name", "Ada");
  await page.click("#name-form button[type=submit]");
  const cdp = await cdpFor(page);
  const sent: unknown[][] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/api/game/players")) sent.push(r.postDataJSON().training_lines);
  });

  for (let i = 0; i < 4; i++) await tapText(page, cdp);
  await tapText(page, cdp, ADA, TOUCH_PHRASE.slice(0, -1));
  await context.setOffline(true);
  await tapKey(page, cdp, codeFor(TOUCH_PHRASE.at(-1)!));

  await expect(page.locator(".error")).toHaveText(
    "Couldn't save your signature. Check your connection, then tap this line again.",
  );
  // Back on the last line, not the first.
  await expect(page.locator(".dots .dot.on")).toHaveText("4");
  await expect(page.locator("#keyboard")).toBeVisible();

  await context.setOffline(false);
  await tapText(page, cdp);
  await expect(page.locator("h2", { hasText: "This is how you tap." })).toBeVisible({ timeout: 10_000 });
  // Both tries sent the four lines after the warm-up, never five.
  expect(sent.map((lines) => lines.length)).toEqual([4, 4]);
  const room = await page.evaluate(() => fetch("/api/game/room").then((r) => r.json()));
  expect(room.players.map((p: { name: string }) => p.name)).toEqual(["Ada"]);
});

test("tapping never focuses a text field, so the phone's own keyboard stays closed", async ({
  context,
  baseURL,
}) => {
  const page = await onTheAttackView(context, baseURL!);
  const cdp = await cdpFor(page);
  const focused = (): Promise<string> => page.evaluate(() => document.activeElement?.tagName ?? "");

  await tapText(page, cdp, ADA, "tap the");
  expect(["BODY", "SELECT"]).toContain(await focused());
  // The keyboard itself is plain elements: nothing in it can take text.
  await expect(page.locator("#keyboard input, #keyboard textarea, #keyboard [contenteditable]")).toHaveCount(0);

  // The enrollment view has no text field at all.
  await page.click("#to-room");
  await page.click("#add-player");
  await page.fill("#player-name", "Bob");
  await page.click("#name-form button[type=submit]");
  await expect(page.locator("#keyboard")).toBeVisible();
  await expect(page.locator("#app input, #app textarea, #app [contenteditable]")).toHaveCount(0);
  await tapText(page, cdp, ADA, "tap");
  expect(await focused()).toBe("BODY");
});

test("the keyboard blocks the long-press menu and selection, and only there", async ({ context, baseURL }) => {
  const page = await onTheAttackView(context, baseURL!);
  const prevented = (selector: string): Promise<boolean> =>
    page.evaluate((s) => {
      const event = new MouseEvent("contextmenu", { bubbles: true, cancelable: true });
      document.querySelector(s)!.dispatchEvent(event);
      return event.defaultPrevented;
    }, selector);
  expect(await prevented('.key[data-code="KeyT"]')).toBe(true);
  expect(await prevented("#phrase")).toBe(false);

  const style = (selector: string, property: string): Promise<string> =>
    page.evaluate(([s, p]) => getComputedStyle(document.querySelector(s!)!).getPropertyValue(p!), [selector, property]);
  expect(await style("#keyboard", "touch-action")).toBe("none");
  expect(await style("#keyboard", "user-select")).toBe("none");
  // The page around it scrolls and zooms as usual.
  expect(await style("#app", "touch-action")).toBe("auto");
  expect(await page.locator('meta[name="viewport"]').getAttribute("content")).not.toMatch(/user-scalable|maximum-scale/);
});
