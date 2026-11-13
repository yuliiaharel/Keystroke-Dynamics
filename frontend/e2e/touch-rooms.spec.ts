import { expect, test, type Page } from "@playwright/test";

import { LIVE_MS, card, roomPathOf } from "./room-helpers";
import { ADA, BOB, PHONE, cdpFor, enrollByTapping, enrollTouchByApi, joinAsTouch, tapText } from "./touch-helpers";

/**
 * A touch room shared by two phones, each its own browser context
 * and so its own member of the room
 * (docs/plans/active/MOBILE_PLAN.md Phase 2). The rooms themselves
 * are the keyboard game's (rooms.spec.ts); this is what changes when
 * the keyboards are phones.
 */

/** What a browser does when its tab is hidden or shown again. */
async function setVisibility(page: Page, state: "hidden" | "visible"): Promise<void> {
  await page.evaluate((value) => {
    Object.defineProperty(document, "visibilityState", { value, configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
  }, state);
}

test("two phones share a room by its link: each enrolls, attacks cross phones, and neither can touch the other's player", async ({
  browser,
  baseURL,
}) => {
  test.setTimeout(120_000);
  const host = await browser.newContext({ ...PHONE, baseURL });
  const friend = await browser.newContext({ ...PHONE, baseURL });
  const hostPage = await host.newPage();
  const friendPage = await friend.newPage();
  const hostCdp = await cdpFor(hostPage);
  const friendCdp = await cdpFor(friendPage);

  // The host starts a room on their phone and enrolls.
  await hostPage.goto("/party");
  await hostPage.click('[data-level="touch"]');
  await expect(hostPage.locator("#name-form")).toBeVisible();
  const link = roomPathOf(hostPage);
  expect(link).toMatch(/^\/r\/[A-HJ-NP-Z2-9]{8}$/);
  await enrollByTapping(hostPage, hostCdp, "Ada", ADA);
  await hostPage.click("#to-room");
  await expect(hostPage.locator("#room-code")).toHaveText(/^[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$/);
  await expect(hostPage.locator("#copy-link")).toBeVisible();
  await expect(hostPage.locator("#room-note")).toContainText("names, signatures, and tap maps");

  // The friend opens the link on their own phone: straight to the
  // name step, as a player and not a watcher.
  await friendPage.goto(link);
  await expect(friendPage.locator("#name-form")).toBeVisible();
  const joined = await friendPage.evaluate(() => fetch("/api/game/room").then((r) => r.json()));
  expect(joined.device_type).toBe("touch");
  expect(joined.watching).toBe(false);
  expect(joined.is_host).toBe(false);
  await enrollByTapping(friendPage, friendCdp, "Bob", BOB);

  // Bob appears on the host's phone live, tap map and all.
  await expect(card(hostPage, "Bob")).toBeVisible({ timeout: LIVE_MS });
  await expect(card(hostPage, "Bob").locator(".map svg circle")).toHaveCount(14);
  await friendPage.click("#to-room");
  await expect(card(friendPage, "Ada")).toBeVisible();

  // Each card says which phone it's on, from each side.
  await expect(card(hostPage, "Ada").locator("[data-keyboard]")).toHaveText("On this phone");
  await expect(card(hostPage, "Bob").locator("[data-keyboard]")).toHaveText("On another phone");
  await expect(card(friendPage, "Bob").locator("[data-keyboard]")).toHaveText("On this phone");
  await expect(card(friendPage, "Ada").locator("[data-keyboard]")).toHaveText("On another phone");

  // Neither phone is offered the other's player to rename, delete,
  // test, or re-grip. (The host may remove, which is tested below.)
  for (const control of ["[data-rename]", "[data-delete]", "[data-self]", "[data-grip]"]) {
    await expect(card(friendPage, "Ada").locator(control)).toHaveCount(0);
    await expect(card(hostPage, "Bob").locator(control)).toHaveCount(0);
    await expect(card(friendPage, "Bob").locator(control)).toHaveCount(1);
  }
  // And the server refuses it, whatever the page offers.
  const ada = joined.players.find((p: { name: string }) => p.name === "Ada");
  const origin = { Origin: baseURL! };
  const rename = await friend.request.patch(`/api/game/players/${ada.id}`, { data: { name: "Hacked" }, headers: origin });
  expect(rename.status()).toBe(403);
  const remove = await friend.request.delete(`/api/game/room/players/${ada.id}`, { headers: origin });
  expect(remove.status()).toBe(403);
  await expect(card(hostPage, "Ada")).toBeVisible();
  await expect(card(hostPage, "Hacked")).toHaveCount(0);

  // "Who's tapping" lists only this phone's own players, plus Guest.
  await card(friendPage, "Ada").locator("[data-attack]").click();
  await expect(friendPage.locator("#who option")).toHaveText(["Guest", "Bob"]);
  await tapText(friendPage, friendCdp, BOB);
  await expect(friendPage.locator("#result")).toBeVisible({ timeout: 10_000 });
  await expect(friendPage.locator("#result .verdict")).toHaveText("Caught!");
  await expect(friendPage.locator("#keyboard-note")).toContainText("Different phone");

  // The attack reaches the host's scores live, labeled.
  await hostPage.click('[data-tab="scores"]');
  const row = hostPage.locator("tbody tr", { hasText: "Bob" });
  await expect(row).toBeVisible({ timeout: LIVE_MS });
  await expect(row).toContainText("different phone");

  // An attack tapped on Ada's own phone carries no such note.
  await hostPage.click('[data-tab="room"]');
  await card(hostPage, "Ada").locator("[data-attack]").click();
  await expect(hostPage.locator("#who")).toHaveValue(""); // Guest: Ada can't attack herself
  await tapText(hostPage, hostCdp, BOB);
  await expect(hostPage.locator("#result")).toBeVisible({ timeout: 10_000 });
  await expect(hostPage.locator("#keyboard-note")).toHaveCount(0);
  await friendPage.click('[data-tab="scores"]');
  const guestRow = friendPage.locator("tbody tr", { hasText: "Guest" });
  await expect(guestRow).toBeVisible({ timeout: LIVE_MS });
  await expect(guestRow).not.toContainText("different phone");

  // A returning phone goes straight to the room, not the name step.
  await friendPage.goto(link);
  await expect(card(friendPage, "Bob")).toBeVisible();
  await expect(friendPage.locator("#name-form")).toHaveCount(0);

  await host.close();
  await friend.close();
});

test("a phone that was hidden catches up as soon as it's looked at again", async ({ browser, baseURL }) => {
  const host = await browser.newContext({ ...PHONE, baseURL });
  const friend = await browser.newContext({ ...PHONE, baseURL });
  const hostPage = await host.newPage();
  const friendPage = await friend.newPage();

  await hostPage.goto("/party");
  await hostPage.click('[data-level="touch"]');
  await expect(hostPage.locator("#name-form")).toBeVisible();
  const code = roomPathOf(hostPage).slice(3);
  await enrollTouchByApi(host, baseURL!, "Ada");
  await joinAsTouch(friend, baseURL!, code);
  await friendPage.goto("/party");
  await expect(card(friendPage, "Ada")).toBeVisible();

  // The friend's phone is locked. The stream still says the room
  // changed, but the request that would fetch it fails, as it does on
  // a phone whose browser has been put to sleep -- and nothing tells
  // the page to try again.
  let streams = 0;
  await friendPage.route("**/api/game/room/events", (route) => {
    streams++;
    return route.continue();
  });
  await setVisibility(friendPage, "hidden");
  await friendPage.route("**/api/game/room", (route) => route.abort());
  await enrollTouchByApi(host, baseURL!, "Grace");
  await friendPage.waitForTimeout(1_000);
  await expect(card(friendPage, "Grace")).toHaveCount(0);

  // Unlocked: the page fetches the room and opens a fresh stream, so
  // the room on screen is the current one at once.
  await friendPage.unroute("**/api/game/room");
  await setVisibility(friendPage, "visible");
  await expect(card(friendPage, "Grace")).toBeVisible({ timeout: LIVE_MS });
  expect(streams).toBe(1);

  // And live again from then on.
  await enrollTouchByApi(host, baseURL!, "Linus");
  await expect(card(friendPage, "Linus")).toBeVisible({ timeout: LIVE_MS });

  await host.close();
  await friend.close();
});

test("the host of a touch room locks it, removes a player, and ends it, each after confirming", async ({
  browser,
  baseURL,
}) => {
  const host = await browser.newContext({ ...PHONE, baseURL });
  const friend = await browser.newContext({ ...PHONE, baseURL });
  const late = await browser.newContext({ ...PHONE, baseURL });
  const hostPage = await host.newPage();
  const friendPage = await friend.newPage();
  const latePage = await late.newPage();

  await hostPage.goto("/party");
  await hostPage.click('[data-level="touch"]');
  await expect(hostPage.locator("#name-form")).toBeVisible();
  const link = roomPathOf(hostPage);
  await enrollTouchByApi(host, baseURL!, "Ada");
  await hostPage.click("#home");
  await expect(card(hostPage, "Ada")).toBeVisible();

  await friendPage.goto(link);
  await expect(friendPage.locator("#name-form")).toBeVisible();
  await enrollTouchByApi(friend, baseURL!, "Bob", BOB);
  await friendPage.click("#to-room");
  await expect(card(hostPage, "Bob")).toBeVisible({ timeout: LIVE_MS });

  // Only the host is offered the host's controls.
  await expect(hostPage.locator("#lock-room")).toHaveText("Lock room");
  for (const control of ["#lock-room", "#end-room", "[data-remove]"]) {
    await expect(friendPage.locator(control)).toHaveCount(0);
  }

  // Lock: asked first. A third phone is then turned away.
  await hostPage.click("#lock-room");
  await expect(hostPage.locator("#confirm")).toContainText("Lock the room?");
  await hostPage.click("#confirm-yes");
  await expect(hostPage.locator("#lock-room")).toHaveText("Unlock room");
  await expect(friendPage.locator("#room-note")).toContainText("The room is locked", { timeout: LIVE_MS });
  await latePage.goto(link);
  await expect(latePage.locator("h2")).toHaveText("This room is locked");
  await hostPage.click("#lock-room");
  await hostPage.click("#confirm-yes");
  await expect(hostPage.locator("#lock-room")).toHaveText("Lock room");

  // Remove: asked first, and Bob goes from both phones.
  await card(hostPage, "Bob").locator("[data-remove]").click();
  await expect(card(hostPage, "Bob").locator("#confirm")).toContainText("Remove Bob from the room?");
  await hostPage.click("#confirm-yes");
  await expect(card(hostPage, "Bob")).toHaveCount(0);
  await expect(card(friendPage, "Bob")).toHaveCount(0, { timeout: LIVE_MS });

  // Leave room is offered on a phone too, and asks first.
  await friendPage.click("#leave-room");
  await expect(friendPage.locator("#confirm")).toContainText("Leave this room?");
  await friendPage.click("#confirm-no");

  // End: asked first, and the friend's phone shows the ended page.
  await hostPage.click("#end-room");
  await expect(hostPage.locator("#confirm")).toContainText("End the room for everyone?");
  await hostPage.click("#confirm-yes");
  await expect(hostPage.locator('[data-level="touch"]')).toBeVisible();
  await expect(friendPage.locator("h2")).toHaveText("This room has ended", { timeout: LIVE_MS });
  // Starting again from there makes a touch room.
  await friendPage.click("#start-own");
  await expect(friendPage.locator("#name-form")).toBeVisible();
  const fresh = await friendPage.evaluate(() => fetch("/api/game/room").then((r) => r.json()));
  expect(fresh.device_type).toBe("touch");

  await host.close();
  await friend.close();
  await late.close();
});

test("a phone already in a room is asked before a link takes it to another", async ({ browser, baseURL }) => {
  const host = await browser.newContext({ ...PHONE, baseURL });
  const friend = await browser.newContext({ ...PHONE, baseURL });
  const hostPage = await host.newPage();
  const friendPage = await friend.newPage();

  await hostPage.goto("/party");
  await hostPage.click('[data-level="touch"]');
  await expect(hostPage.locator("#name-form")).toBeVisible();
  const link = roomPathOf(hostPage);

  await friendPage.goto("/party");
  await friendPage.click('[data-level="touch"]');
  await expect(friendPage.locator("#name-form")).toBeVisible();
  const own = roomPathOf(friendPage);

  await friendPage.goto(link);
  await expect(friendPage.locator("h2")).toHaveText("Leave your current room and join this one?");
  await friendPage.click("#switch-stay");
  expect(roomPathOf(friendPage)).toBe(own);

  await friendPage.goto(link);
  await friendPage.click("#switch-join");
  await expect(friendPage.locator("#name-form")).toBeVisible();
  expect(roomPathOf(friendPage)).toBe(link);

  await host.close();
  await friend.close();
});
