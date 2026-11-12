import { devices, expect, test } from "@playwright/test";

import { LIVE_MS, card, enrollByApi, enrollByTyping, post, roomPathOf, typeLine } from "./room-helpers";

/**
 * docs/plans/active/ROOMS_PLAN.md Phase 3: a room shared by its link,
 * played from separate browsers. Each browser context here is its own
 * session, so its own member of the room -- "another keyboard".
 * Assertions are on what each page shows; the API is used directly
 * only to set a scene quickly, or to try what the page never offers.
 */

const ROOM_URL = /\/r\/[A-HJ-NP-Z2-9]{8}$/;
const ENDED = "This room has ended";

test("two browsers share a room by its link, see each other live, and attack across keyboards", async ({
  browser,
  baseURL,
}) => {
  const host = await browser.newContext({ baseURL, permissions: ["clipboard-read", "clipboard-write"] });
  const friend = await browser.newContext({ baseURL });
  const hostPage = await host.newPage();
  const friendPage = await friend.newPage();

  // Starting a party creates a room and opens it at its own link.
  await hostPage.goto("/party");
  await hostPage.click('[data-level="sentence"]');
  await expect(hostPage).toHaveURL(ROOM_URL);
  await enrollByTyping(hostPage, "Ada");

  // The room header: the code, the note, and a link that copies.
  const code = roomPathOf(hostPage).slice("/r/".length);
  await expect(hostPage.locator("#room-code")).toHaveText(`${code.slice(0, 4)}-${code.slice(4)}`);
  await expect(hostPage.locator("#room-note")).toHaveText(
    "Anyone with this link can join and see names and signatures.",
  );
  await hostPage.click("#copy-link");
  await expect(hostPage.locator("#copy-link")).toHaveText("Link copied");
  const link = await hostPage.evaluate(() => navigator.clipboard.readText());
  expect(link).toBe(`${baseURL}/r/${code}`);

  // Opening the link joins at once, with no sign-up: the name step.
  await friendPage.goto(link);
  await expect(friendPage.locator("#name-form")).toBeVisible();
  await enrollByTyping(friendPage, "Bob");

  // Each sees the other's player arrive without a refresh, and whose
  // keyboard each one is on.
  await expect(card(hostPage, "Bob")).toBeVisible({ timeout: LIVE_MS });
  await expect(card(hostPage, "Ada").locator("[data-keyboard]")).toHaveText("On this keyboard");
  await expect(card(hostPage, "Bob").locator("[data-keyboard]")).toHaveText("On another keyboard");
  await expect(card(friendPage, "Ada").locator("[data-keyboard]")).toHaveText("On another keyboard");
  await expect(card(friendPage, "Bob").locator("[data-keyboard]")).toHaveText("On this keyboard");

  // The friend is offered nothing that changes Ada, and isn't the
  // host, so can't remove her either...
  await expect(card(friendPage, "Bob").locator("[data-rename]")).toBeVisible();
  for (const control of ["[data-rename]", "[data-delete]", "[data-self]", "[data-remove]"]) {
    await expect(card(friendPage, "Ada").locator(control)).toHaveCount(0);
  }
  // ...and asking the server directly is refused.
  const ada = (await (await friend.request.get("/api/game/room")).json()).players.find(
    (p: { name: string }) => p.name === "Ada",
  );
  const origin = { Origin: baseURL! };
  const rename = await friend.request.patch(`/api/game/players/${ada.id}`, {
    data: { name: "Hacked" },
    headers: origin,
  });
  expect(rename.status()).toBe(403);
  const remove = await friend.request.delete(`/api/game/room/players/${ada.id}`, { headers: origin });
  expect(remove.status()).toBe(403);
  await expect(card(hostPage, "Ada")).toBeVisible();
  await expect(card(friendPage, "Ada")).toBeVisible();

  // The host watches the scores while the friend attacks.
  await hostPage.click('[data-tab="scores"]');
  await expect(hostPage.locator("text=No attempts yet")).toBeVisible();

  // "Who's typing" lists only this browser's own players, plus Guest.
  await card(friendPage, "Ada").locator("[data-attack]").click();
  await expect(friendPage.locator("#who option")).toHaveText(["Guest", "Bob"]);
  await expect(friendPage.locator("#who")).toHaveValue(/.+/); // Bob, who was just enrolled here
  await typeLine(friendPage);
  await expect(friendPage.locator("#result")).toBeVisible({ timeout: 10000 });
  await expect(friendPage.locator("#keyboard-note")).toContainText("Different keyboard");

  // The attack reaches the host's scores live, labeled.
  const row = hostPage.locator("tbody tr", { hasText: "Bob" });
  await expect(row).toBeVisible({ timeout: LIVE_MS });
  await expect(row).toContainText("different keyboard");

  // An attack from Ada's own keyboard carries no such note.
  await hostPage.click('[data-tab="room"]');
  await card(hostPage, "Ada").locator("[data-attack]").click();
  await expect(hostPage.locator("#who")).toHaveValue(""); // Guest: Ada can't attack herself
  await typeLine(hostPage);
  await expect(hostPage.locator("#result")).toBeVisible({ timeout: 10000 });
  await expect(hostPage.locator("#keyboard-note")).toHaveCount(0);
  await friendPage.click('[data-tab="scores"]');
  await expect(friendPage.locator("tbody tr", { hasText: "Guest" })).not.toContainText("different keyboard");

  // A returning member goes straight to the room, not the name step.
  await friendPage.goto(link);
  await expect(card(friendPage, "Bob")).toBeVisible();
  await expect(friendPage.locator("#name-form")).toHaveCount(0);

  await host.close();
  await friend.close();
});

test("the host locks the room, removes a player, and ends the room, each after confirming", async ({
  browser,
  baseURL,
}) => {
  const host = await browser.newContext({ baseURL });
  const friend = await browser.newContext({ baseURL });
  const late = await browser.newContext({ baseURL });
  const room = await post(host.request, baseURL!, "/api/game/rooms", { level: "sentence" });
  await enrollByApi(host, baseURL!, "Ada");
  const link = `/r/${room.code}`;

  const hostPage = await host.newPage();
  const friendPage = await friend.newPage();
  const latePage = await late.newPage();
  await hostPage.goto(link);
  await friendPage.goto(link);
  await expect(friendPage.locator("#name-form")).toBeVisible();
  await enrollByApi(friend, baseURL!, "Bob");
  await friendPage.click("#to-room");
  await expect(card(hostPage, "Bob")).toBeVisible({ timeout: LIVE_MS });

  // Only the host is offered the host's controls.
  await expect(hostPage.locator("#lock-room")).toHaveText("Lock room");
  for (const control of ["#lock-room", "#end-room", "[data-remove]"]) {
    await expect(friendPage.locator(control)).toHaveCount(0);
  }

  // Lock: asked first, and "Cancel" changes nothing.
  await hostPage.click("#lock-room");
  await expect(hostPage.locator("#confirm")).toContainText("Lock the room?");
  await hostPage.click("#confirm-no");
  await expect(hostPage.locator("#confirm")).toHaveCount(0);
  await expect(hostPage.locator("#lock-room")).toHaveText("Lock room");

  await hostPage.click("#lock-room");
  await hostPage.click("#confirm-yes");
  await expect(hostPage.locator("#lock-room")).toHaveText("Unlock room");
  await expect(friendPage.locator("#room-note")).toContainText("The room is locked", { timeout: LIVE_MS });

  // A locked room turns a newcomer away with a clear message...
  await latePage.goto(link);
  await expect(latePage.locator("h2")).toHaveText("This room is locked");
  // ...and lets them in once it's unlocked.
  await hostPage.click("#lock-room");
  await expect(hostPage.locator("#confirm")).toContainText("Unlock the room?");
  await hostPage.click("#confirm-yes");
  await expect(hostPage.locator("#lock-room")).toHaveText("Lock room");
  await latePage.click("#retry-join");
  await expect(latePage.locator("#name-form")).toBeVisible();

  // Remove: asked first, in the player's own card.
  await card(hostPage, "Bob").locator("[data-remove]").click();
  await expect(card(hostPage, "Bob").locator("#confirm")).toContainText("Remove Bob from the room?");
  await hostPage.click("#confirm-no");
  await expect(card(hostPage, "Bob")).toBeVisible();
  await card(hostPage, "Bob").locator("[data-remove]").click();
  await hostPage.click("#confirm-yes");
  await expect(card(hostPage, "Bob")).toHaveCount(0);
  await expect(card(friendPage, "Bob")).toHaveCount(0, { timeout: LIVE_MS });
  await expect(card(friendPage, "Ada")).toBeVisible(); // still in the room, just without a player

  // End: asked first; then everyone is out.
  await hostPage.click("#end-room");
  await expect(hostPage.locator("#confirm")).toContainText("End the room for everyone?");
  await hostPage.click("#confirm-yes");
  await expect(hostPage.locator('[data-level="sentence"]')).toBeVisible();
  expect(roomPathOf(hostPage)).not.toMatch(/^\/r\//);
  await expect(friendPage.locator("h2")).toHaveText(ENDED, { timeout: LIVE_MS });

  // The ended page offers a room of one's own.
  await friendPage.click("#start-own");
  await expect(friendPage.locator("#name-form")).toBeVisible();
  await expect(friendPage).toHaveURL(ROOM_URL);
  expect(roomPathOf(friendPage)).not.toBe(link);

  // The old link now leads to the ended page.
  await latePage.goto(link);
  await expect(latePage.locator("h2")).toHaveText(ENDED);

  await host.close();
  await friend.close();
  await late.close();
});

test("an ended room, a code that never existed, and a malformed code all show the same page", async ({
  browser,
  baseURL,
}) => {
  const host = await browser.newContext({ baseURL });
  const room = await post(host.request, baseURL!, "/api/game/rooms", { level: "sentence" });
  await post(host.request, baseURL!, "/api/game/room/end");

  const visitor = await browser.newContext({ baseURL });
  const page = await visitor.newPage();
  const shown: string[] = [];
  for (const code of [room.code, "ZZZZZZZZ", "nonsense"]) {
    await page.goto(`/r/${code}`);
    await expect(page.locator("h2")).toHaveText(ENDED);
    await expect(page.locator("#start-own")).toBeVisible();
    shown.push(await page.locator("#app").innerText());
  }
  expect(shown[1]).toBe(shown[0]);
  expect(shown[2]).toBe(shown[0]);

  await host.close();
  await visitor.close();
});

test("a full room turns a newcomer away with a clear message", async ({ browser, playwright, baseURL }) => {
  const host = await browser.newContext({ baseURL });
  const room = await post(host.request, baseURL!, "/api/game/rooms", { level: "sentence" });

  // Fill every place with a browser of its own, however many the
  // server allows (GAME_MEMBERS_PER_PARTY_LIMIT, 12 by default).
  const members = [];
  let full = false;
  for (let i = 0; i < 30 && !full; i++) {
    const member = await playwright.request.newContext({ baseURL });
    members.push(member);
    const joined = await member.post(`/api/game/rooms/${room.code}/join`, { headers: { Origin: baseURL! } });
    full = joined.status() === 409;
    expect([200, 409], await joined.text()).toContain(joined.status());
  }
  expect(full).toBe(true);

  const newcomer = await browser.newContext({ baseURL });
  const page = await newcomer.newPage();
  await page.goto(`/r/${room.code}`);
  await expect(page.locator("h2")).toHaveText("This room is full");
  await expect(page.locator("#start-own")).toBeVisible();

  for (const member of members) await member.dispose();
  await host.close();
  await newcomer.close();
});

test("a browser already in a room is asked before a link moves it to another", async ({ browser, baseURL }) => {
  const host = await browser.newContext({ baseURL });
  const other = await post(host.request, baseURL!, "/api/game/rooms", { level: "sentence" });

  const visitor = await browser.newContext({ baseURL });
  const mine = await post(visitor.request, baseURL!, "/api/game/rooms", { level: "sentence" });
  await enrollByApi(visitor, baseURL!, "Casey");
  const page = await visitor.newPage();

  await page.goto(`/r/${other.code}`);
  await expect(page.locator("h2")).toHaveText("Leave your current room and join this one?");

  // Staying keeps the room, and the player in it.
  await page.click("#switch-stay");
  await expect(card(page, "Casey")).toBeVisible();
  expect(roomPathOf(page)).toBe(`/r/${mine.code}`);

  // Leaving joins the other room as a newcomer.
  await page.goto(`/r/${other.code}`);
  await page.click("#switch-join");
  await expect(page.locator("#name-form")).toBeVisible();
  expect(roomPathOf(page)).toBe(`/r/${other.code}`);
  const now = await (await visitor.request.get("/api/game/room")).json();
  expect(now.code).toBe(other.code);
  expect(now.players).toEqual([]);

  await host.close();
  await visitor.close();
});

test("leaving a room returns to the start, and the room goes on without that browser's players", async ({
  browser,
  baseURL,
}) => {
  const host = await browser.newContext({ baseURL });
  const friend = await browser.newContext({ baseURL });
  const room = await post(host.request, baseURL!, "/api/game/rooms", { level: "sentence" });
  await enrollByApi(host, baseURL!, "Ada");
  await post(friend.request, baseURL!, `/api/game/rooms/${room.code}/join`);
  await enrollByApi(friend, baseURL!, "Bob");

  const hostPage = await host.newPage();
  const friendPage = await friend.newPage();
  await hostPage.goto(`/r/${room.code}`);
  await friendPage.goto(`/r/${room.code}`);
  await expect(card(hostPage, "Bob")).toBeVisible();

  await friendPage.click("#leave-room");
  await expect(friendPage.locator("#confirm")).toContainText("Leave this room? Your players leave with you.");
  await friendPage.click("#confirm-yes");
  await expect(friendPage.locator('[data-level="sentence"]')).toBeVisible();
  expect(roomPathOf(friendPage)).not.toMatch(/^\/r\//);

  await expect(card(hostPage, "Bob")).toHaveCount(0, { timeout: LIVE_MS });
  await expect(card(hostPage, "Ada")).toBeVisible();

  await host.close();
  await friend.close();
});

test("a phone can open a room link and watch, but is told to join from a computer to play", async ({
  browser,
  baseURL,
}) => {
  const host = await browser.newContext({ baseURL });
  const room = await post(host.request, baseURL!, "/api/game/rooms", { level: "sentence" });
  await enrollByApi(host, baseURL!, "Ada");

  const phone = await browser.newContext({ ...devices["Pixel 7"], baseURL });
  const page = await phone.newPage();
  await page.goto(`/r/${room.code}`);

  // Straight to the room: there's no name to give without typing.
  await expect(card(page, "Ada")).toBeVisible();
  await expect(page.locator(".notice")).toContainText("Join from a computer to play");

  // The name step is replaced.
  await page.click("#add-player");
  await expect(page.locator("h2")).toHaveText("Join from a computer to play");
  await expect(page.locator("#name-form")).toHaveCount(0);
  await page.click("#to-room");

  // So is the typing step of an attack -- but a replay still plays.
  await card(page, "Ada").locator("[data-attack]").click();
  await expect(page.locator("#typer")).toHaveCount(0);
  await expect(page.locator(".typer")).toContainText("Join from a computer to play");
  await page.click("#replay");
  await expect(page.locator("#result")).toContainText("Replay wins", { timeout: 15000 });

  // New players still appear live.
  await page.click('[data-tab="room"]');
  await enrollByApi(host, baseURL!, "Grace");
  await expect(card(page, "Grace")).toBeVisible({ timeout: LIVE_MS });

  await host.close();
  await phone.close();
});
