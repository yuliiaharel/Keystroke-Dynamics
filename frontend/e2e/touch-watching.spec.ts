import { devices, expect, test, type Browser, type BrowserContext } from "@playwright/test";

import { LIVE_MS, LINE, card, enrollByApi, post } from "./room-helpers";
import { PHONE, createTouchRoom, enrollTouchByApi, tapLineEvents } from "./touch-helpers";

/**
 * A room is for one kind of device
 * (docs/plans/active/MOBILE_PLAN.md Phase 2 section 4). The other kind
 * can open the link and watch -- read the room, see it change, run a
 * replay -- but is never given a step to type or tap in, and the
 * server refuses it if it tries.
 */

test("a phone that opens a keyboard room's link watches: no typing step, a replay, and its own room one tap away", async ({
  browser,
  baseURL,
}) => {
  const host = await browser.newContext({ baseURL });
  const room = await post(host.request, baseURL!, "/api/game/rooms", { level: "sentence" });
  await enrollByApi(host, baseURL!, "Ada");

  const phone = await browser.newContext({ ...devices["Pixel 7"], baseURL });
  const page = await phone.newPage();
  await page.goto(`/r/${room.code}`);

  // Straight to the room, with the reason it can't play here.
  await expect(card(page, "Ada")).toBeVisible();
  await expect(page.locator("#watching")).toContainText("This room is for computers.");
  await expect(page.locator("#watching #start-own")).toHaveText("Start your own room");
  const joined = await page.evaluate(() => fetch("/api/game/room").then((r) => r.json()));
  expect(joined.watching).toBe(true);
  expect(joined.device_type).toBe("keyboard");

  // Nothing leads to a name step or a line to type.
  await expect(page.locator("#add-player")).toHaveCount(0);
  await expect(page.locator("#name-form")).toHaveCount(0);
  await expect(page.locator("[data-self], [data-grip], [data-rename], [data-delete]")).toHaveCount(0);
  // The old advice to use a computer is gone from the page.
  await expect(page.locator("#app")).not.toContainText("Join from a computer to play");
  await expect(page.locator("#app")).not.toContainText("Best on a computer");

  // An attack opens with no typing area and no on-page keyboard --
  // but a replay still plays.
  await card(page, "Ada").locator("[data-attack]").click();
  await expect(page.locator("#typer")).toHaveCount(0);
  await expect(page.locator("#keyboard")).toBeHidden();
  await expect(page.locator(".typer")).toContainText("This room is for computers");
  await page.click("#replay");
  await expect(page.locator("#result")).toContainText("Replay wins", { timeout: 15_000 });

  // The server refuses a watcher's enrollment and typing, whatever it sends.
  const origin = { Origin: baseURL! };
  const touchLines = [0, 1, 2, 3].map((i) => tapLineEvents(undefined, i));
  const enroll = await phone.request.post("/api/game/players", {
    data: { name: "Sneaky", training_lines: touchLines },
    headers: origin,
  });
  expect(enroll.status()).toBe(403);
  expect((await enroll.json()).detail).toContain("This room is for computers");
  const attempt = await phone.request.post("/api/game/attempts", {
    data: { typist_id: null, target_id: joined.players[0].id, mode: "attack", events: LINE, client_attempt_id: "x" },
    headers: origin,
  });
  expect(attempt.status()).toBe(403);

  // New players still appear live.
  await page.click('[data-tab="room"]');
  await enrollByApi(host, baseURL!, "Grace");
  await expect(card(page, "Grace")).toBeVisible({ timeout: LIVE_MS });

  // Start your own room: a touch room, where this phone plays.
  await page.click("#start-own");
  await expect(page.locator("#name-form")).toBeVisible();
  await expect(page.locator("h2")).toHaveText("Who's tapping?");
  const own = await page.evaluate(() => fetch("/api/game/room").then((r) => r.json()));
  expect(own.device_type).toBe("touch");
  expect(own.watching).toBe(false);
  expect(own.code).not.toBe(room.code);

  await host.close();
  await phone.close();
});

test("a computer that opens a touch room's link watches: no typing step, a replay, and its own room one click away", async ({
  browser,
  baseURL,
}) => {
  const host = await browser.newContext({ ...PHONE, baseURL });
  const room = await createTouchRoom(host, baseURL!);
  await enrollTouchByApi(host, baseURL!, "Ada");

  const computer = await browser.newContext({ baseURL, viewport: { width: 1280, height: 800 } });
  const page = await computer.newPage();
  await page.goto(`/r/${room.code}`);

  // Straight to the room, with the reason it can't play here.
  await expect(card(page, "Ada")).toBeVisible();
  await expect(page.locator("#watching")).toContainText("This room is for phones.");
  await expect(page.locator("#watching #start-own")).toHaveText("Start your own room");
  // No touchscreen here, so no on-screen keyboard is offered.
  await expect(page.locator("#use-touch")).toHaveCount(0);
  const joined = await page.evaluate(() => fetch("/api/game/room").then((r) => r.json()));
  expect(joined.watching).toBe(true);
  expect(joined.device_type).toBe("touch");

  // It reads the room as its players see it: signatures and tap maps.
  await expect(card(page, "Ada").locator(".ring svg")).toBeVisible();
  await expect(card(page, "Ada").locator(".map svg circle")).toHaveCount(14);
  await expect(card(page, "Ada").locator("[data-keyboard]")).toHaveText("On another phone");
  await expect(card(page, "Sample: Speedy Thumbs")).toBeVisible();
  // The computer keeps its own layout: it isn't a phone.
  await expect(page.locator("body")).not.toHaveClass(/touch/);

  // Nothing leads to a name step or a line to type or tap.
  await expect(page.locator("#add-player")).toHaveCount(0);
  await expect(page.locator("#name-form")).toHaveCount(0);
  await expect(page.locator("[data-self], [data-grip], [data-rename], [data-delete]")).toHaveCount(0);
  await card(page, "Ada").locator("[data-attack]").click();
  await expect(page.locator("#typer")).toHaveCount(0);
  await expect(page.locator("#keyboard")).toBeHidden();
  await expect(page.locator(".typer")).toContainText("This room is for phones");
  // Typing does nothing: no key is being listened for.
  await page.keyboard.type("tap the rhythm");
  await expect(page.locator("#phrase > span").first()).toHaveText("");

  // A replay still plays, and shows the touch game's two scores.
  await page.click("#replay");
  await expect(page.locator("#result")).toContainText("Replay wins", { timeout: 15_000 });
  await expect(page.locator("#rhythm-place")).toContainText("Rhythm");
  await expect(page.locator("#rhythm-place")).toContainText("Tap place");

  // The server refuses a watcher's enrollment and typing, whatever it sends.
  const origin = { Origin: baseURL! };
  const enroll = await computer.request.post("/api/game/players", {
    data: { name: "Sneaky", training_lines: [0, 1, 2, 3].map((i) => tapLineEvents(undefined, i)) },
    headers: origin,
  });
  expect(enroll.status()).toBe(403);
  expect((await enroll.json()).detail).toContain("This room is for phones");
  const attempt = await computer.request.post("/api/game/attempts", {
    data: {
      typist_id: null,
      target_id: joined.players[0].id,
      mode: "attack",
      events: tapLineEvents(),
      client_attempt_id: "x",
    },
    headers: origin,
  });
  expect(attempt.status()).toBe(403);

  // Scores read the touch way, and new players still appear live.
  await page.click('[data-tab="scores"]');
  await expect(page.locator("thead th")).toContainText(["Rhythm", "Place"]);
  await page.click('[data-tab="room"]');
  await enrollTouchByApi(host, baseURL!, "Grace");
  await expect(card(page, "Grace")).toBeVisible({ timeout: LIVE_MS });

  // How it works describes the room on screen, not the keyboard game.
  await page.click('[data-tab="how"]');
  await expect(page.locator("#app")).toContainText("where on the key it lands");

  // Start your own room: a keyboard room, where this computer plays.
  await page.click('[data-tab="room"]');
  await page.click("#start-own");
  await expect(page.locator("#name-form")).toBeVisible();
  await expect(page.locator("h2")).toHaveText("Who's typing?");
  const own = await page.evaluate(() => fetch("/api/game/room").then((r) => r.json()));
  expect(own.device_type).toBe("keyboard");
  expect(own.level).toBe("sentence");
  expect(own.watching).toBe(false);

  await host.close();
  await computer.close();
});

/**
 * A computer with a touchscreen: touch points, but a mouse as its
 * main pointer. Chromium's touch emulation always reports a finger as
 * the main pointer, so that one media query is answered here the way
 * such a laptop's browser answers it.
 */
async function touchscreenLaptop(browser: Browser, baseURL: string): Promise<BrowserContext> {
  const context = await browser.newContext({ baseURL, viewport: { width: 1280, height: 800 }, hasTouch: true });
  await context.addInitScript(() => {
    const real = window.matchMedia.bind(window);
    window.matchMedia = (query: string) =>
      query === "(pointer: coarse)" ? ({ ...real("not all"), media: query } as MediaQueryList) : real(query);
  });
  return context;
}

test("a touchscreen laptop types by default, and can choose the on-screen keyboard before starting or on a touch room's link", async ({
  browser,
  baseURL,
}) => {
  const laptop = await touchscreenLaptop(browser, baseURL!);
  const page = await laptop.newPage();
  await page.goto("/party");

  // The keyboard game, with a switch.
  await expect(page.locator("h1")).toHaveText("Everyone types in their own shape.");
  await expect(page.locator('[data-level="sentence"]')).toBeVisible();
  await page.click("#use-touch");
  await expect(page.locator("h1")).toHaveText("Your thumbs leave a signature.");
  // And back.
  await page.click("#use-keys");
  await expect(page.locator("h1")).toHaveText("Everyone types in their own shape.");

  // Chosen before starting: the room is a touch room.
  await page.click("#use-touch");
  await page.click('[data-level="touch"]');
  await expect(page.locator("h2")).toHaveText("Who's tapping?");
  let room = await page.evaluate(() => fetch("/api/game/room").then((r) => r.json()));
  expect(room.device_type).toBe("touch");
  // A laptop is always wide: it isn't asked to turn upright.
  await page.fill("#player-name", "Lap");
  await page.click("#name-form button[type=submit]");
  await expect(page.locator("#keyboard")).toBeVisible();
  await expect(page.locator("#tap-status")).toBeHidden();
  await laptop.close();

  // Opening a touch room's link: a watcher by default, with the switch.
  const host = await browser.newContext({ ...PHONE, baseURL });
  const touchRoom = await createTouchRoom(host, baseURL!);
  await enrollTouchByApi(host, baseURL!, "Ada");
  const second = await touchscreenLaptop(browser, baseURL!);
  const visitor = await second.newPage();
  await visitor.goto(`/r/${touchRoom.code}`);
  await expect(visitor.locator("#watching")).toContainText("This room is for phones.");
  await visitor.click("#use-touch");
  await expect(visitor.locator("h2")).toHaveText("Who's tapping?");
  room = await visitor.evaluate(() => fetch("/api/game/room").then((r) => r.json()));
  expect(room.code).toBe(touchRoom.code);
  expect(room.watching).toBe(false);
  expect(room.member_count).toBe(2); // rejoined, not joined twice
  await visitor.click("#to-room");
  await expect(card(visitor, "Ada")).toBeVisible();
  await expect(visitor.locator("#watching")).toHaveCount(0);

  await host.close();
  await second.close();
});
