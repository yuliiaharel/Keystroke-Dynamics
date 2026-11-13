import { expect, test } from "@playwright/test";

import { card, enrollByApi, post } from "./room-helpers";
import {
  ADA,
  BOB,
  PHONE,
  cdpFor,
  createTouchRoom,
  enrollTouchByApi,
  joinAsTouch,
  tapText,
} from "./touch-helpers";

/**
 * Not a behavior test (the other touch specs are): saves each main
 * phone view at 390 px, in the light and the dark theme, for review
 * (docs/plans/active/MOBILE_PLAN.md Phase 2's "Done when"). Includes
 * the room header, the host's controls, and both watcher notices --
 * the second of which is a computer's, so it's saved at desktop width.
 *
 * Files land in screenshots/ as touch-<theme>-<nn>-<view>.png.
 */

for (const theme of ["light", "dark"] as const) {
  test(`screenshot each main phone view: ${theme}`, async ({ browser, baseURL }) => {
    test.setTimeout(90_000);
    const phone = await browser.newContext({ ...PHONE, baseURL, colorScheme: theme });
    const page = await phone.newPage();
    const cdp = await cdpFor(page);
    let n = 0;
    const shot = (name: string, target = page, fullPage = true) =>
      target.screenshot({
        path: `screenshots/touch-${theme}-${String(++n).padStart(2, "0")}-${name}.png`,
        fullPage,
      });

    await page.goto("/party");
    await expect(page.locator('[data-level="touch"]')).toBeVisible();
    await shot("intro");

    await page.click('[data-level="touch"]');
    await expect(page.locator("#player-name")).not.toHaveValue("");
    await shot("name");

    // Enrollment, part-way through a line, with the keyboard up.
    await page.fill("#player-name", "Ada");
    await page.click("#name-form button[type=submit]");
    await tapText(page, cdp, ADA);
    await tapText(page, cdp, ADA, "tap the rhy");
    await shot("enroll", page, false);
    await tapText(page, cdp, ADA, "thm of your thumbs");
    for (let i = 0; i < 3; i++) await tapText(page, cdp, ADA);
    await expect(page.locator("h2", { hasText: "This is how you tap." })).toBeVisible({ timeout: 10_000 });
    await shot("reveal");
    await page.click("#to-room");

    // A second phone joins by the link and enrolls Bob.
    const code = new URL(page.url()).pathname.slice(3);
    const friend = await browser.newContext({ ...PHONE, baseURL, colorScheme: theme });
    await joinAsTouch(friend, baseURL!, code);
    await enrollTouchByApi(friend, baseURL!, "Bob", BOB);
    await expect(card(page, "Bob")).toBeVisible();

    // The room: header with the code and Copy link, the cards, and
    // the host's controls at the foot.
    await shot("room");
    await page.locator(".room-head").scrollIntoViewIfNeeded();
    await shot("room-header", page, false);
    await page.locator("#end-room").scrollIntoViewIfNeeded();
    await shot("host-controls", page, false);
    await page.click("#lock-room");
    await page.locator("#confirm").scrollIntoViewIfNeeded();
    await shot("host-lock-question", page, false);
    await page.click("#confirm-no");
    await card(page, "Bob").locator("[data-remove]").click();
    await card(page, "Bob").locator("#confirm").scrollIntoViewIfNeeded();
    await shot("host-remove-question", page, false);
    await page.click("#confirm-no");

    // The friend's phone attacks Ada: a result with the "different phone" note.
    const friendPage = await friend.newPage();
    const friendCdp = await cdpFor(friendPage);
    await friendPage.goto("/party");
    await card(friendPage, "Ada").locator("[data-attack]").click();
    await expect(friendPage.locator("#keyboard")).toBeVisible();
    await shot("attack", friendPage, false);
    await tapText(friendPage, friendCdp, BOB);
    await expect(friendPage.locator("#result")).toBeVisible({ timeout: 10_000 });
    await shot("result", friendPage);

    // A self test on the host's phone, then scores.
    await card(page, "Ada").locator("[data-grip]").click();
    await expect(page.locator("#keyboard")).toBeVisible();
    await shot("new-grip", page, false);
    await tapText(page, cdp, ADA);
    await expect(page.locator("#result")).toBeVisible({ timeout: 10_000 });
    await shot("result-own");
    await page.click('[data-tab="scores"]');
    await expect(page.locator("tbody tr")).toHaveCount(2);
    await shot("scores");

    await page.click('[data-tab="how"]');
    await page.click("summary");
    await shot("how-it-works");

    // The phone on its side, mid-line.
    await page.click('[data-tab="room"]');
    await card(page, "Bob").locator("[data-attack]").click();
    await page.setViewportSize({ width: 844, height: 390 });
    await expect(page.locator("#tap-status")).toBeVisible();
    await shot("turn-upright", page, false);
    await page.setViewportSize({ width: 390, height: 844 });

    // The friend leaves; a link to another room asks first.
    const other = await browser.newContext({ ...PHONE, baseURL });
    const otherRoom = await createTouchRoom(other, baseURL!);
    await friendPage.goto(`/r/${otherRoom.code}`);
    await expect(friendPage.locator("#switch-join")).toBeVisible();
    await shot("leave-and-join-question", friendPage);
    await friendPage.click("#switch-stay");

    // Watcher notice 1: this phone opens a keyboard room's link.
    const computerHost = await browser.newContext({ baseURL });
    const keyboardRoom = await post(computerHost.request, baseURL!, "/api/game/rooms", { level: "sentence" });
    await enrollByApi(computerHost, baseURL!, "Grace");
    const watcherPhone = await browser.newContext({ ...PHONE, baseURL, colorScheme: theme });
    const watcherPage = await watcherPhone.newPage();
    await watcherPage.goto(`/r/${keyboardRoom.code}`);
    await expect(watcherPage.locator("#watching")).toBeVisible();
    await shot("watching-a-keyboard-room", watcherPage);

    // Watcher notice 2: a computer opens this touch room's link.
    const computer = await browser.newContext({
      baseURL,
      colorScheme: theme,
      viewport: { width: 1280, height: 800 },
    });
    const computerPage = await computer.newPage();
    await computerPage.goto(`/r/${code}`);
    await expect(computerPage.locator("#watching")).toBeVisible();
    await shot("computer-watching-a-touch-room", computerPage);

    // The ended page.
    await page.click('[data-tab="room"]');
    await page.click("#end-room");
    await page.click("#confirm-yes");
    await expect(friendPage.locator("h2")).toHaveText("This room has ended");
    await shot("ended", friendPage);

    for (const context of [phone, friend, other, computerHost, watcherPhone, computer]) await context.close();
  });
}
