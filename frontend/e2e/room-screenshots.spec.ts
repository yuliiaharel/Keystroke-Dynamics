import { devices, expect, test, type BrowserContextOptions } from "@playwright/test";

import { card, enrollByApi, post } from "./room-helpers";

/**
 * Not a behavior test (rooms.spec.ts is): saves the room header, the
 * join step, and the ended page for review, on a desktop and on a
 * phone (docs/plans/active/ROOMS_PLAN.md Phase 3's "Done when").
 * These are keyboard rooms, so the phone is a watcher: its join step
 * is the room itself, with "This room is for computers" on it.
 * touch-screenshots.spec.ts has the phone's own rooms.
 */

const SIZES: [string, BrowserContextOptions][] = [
  ["desktop", { viewport: { width: 1280, height: 800 } }],
  ["phone", devices["Pixel 7"]],
];

for (const [size, options] of SIZES) {
  test(`screenshot the room header, join step, and ended page: ${size}`, async ({ browser, baseURL }) => {
    const host = await browser.newContext({ baseURL });
    const room = await post(host.request, baseURL!, "/api/game/rooms", { level: "sentence" });
    await enrollByApi(host, baseURL!, "Ada");
    await enrollByApi(host, baseURL!, "Grace");

    const visitor = await browser.newContext({ ...options, baseURL });
    const page = await visitor.newPage();
    const shot = (name: string) => page.screenshot({ path: `screenshots/room-${size}-${name}.png`, fullPage: true });

    // The join step: what opening the link shows a newcomer.
    await page.goto(`/r/${room.code}`);
    if (size === "phone") {
      await expect(card(page, "Ada")).toBeVisible();
      await expect(page.locator("#watching")).toContainText("This room is for computers.");
    } else {
      await expect(page.locator("#name-form")).toBeVisible();
    }
    await shot("join");

    // The room, as someone in it who has a player elsewhere on the page.
    if (size !== "phone") await page.click("#to-room");
    await expect(card(page, "Grace")).toBeVisible();
    if (size !== "phone") {
      await enrollByApi(visitor, baseURL!, "Bob");
      await expect(card(page, "Bob")).toBeVisible();
    }
    await shot("header");

    // The ended page.
    await post(host.request, baseURL!, "/api/game/room/end");
    await expect(page.locator("h2")).toHaveText("This room has ended");
    await shot("ended");

    await host.close();
    await visitor.close();
  });
}
