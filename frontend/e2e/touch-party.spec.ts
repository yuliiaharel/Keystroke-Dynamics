import { expect, test } from "@playwright/test";

import { card } from "./room-helpers";
import { ADA, BOB, PHONE, cdpFor, enrollByTapping, tapText } from "./touch-helpers";

/**
 * The touch game on one phone (docs/plans/active/MOBILE_PLAN.md
 * Phase 2), driven end to end against the real backend with emulated
 * touches: two players, an attack, a self test, a grip test, a
 * replay, a rename, a deletion, and the scores page. Every verdict
 * comes from a real POST /api/game/attempts or /api/game/replay.
 *
 * Ada and Bob land nearly half a key apart on every tap, so which
 * side of the limit an attack or a changed grip falls on is decided
 * by the Place score alone and doesn't depend on emulated timing.
 */

test.use(PHONE);

const tile = (page: import("@playwright/test").Page, name: string) =>
  page.locator("#rhythm-place .trait", { hasText: name }).locator("b");

test("a full game on one phone: two players, an attack, a self test, a grip test, a replay, a rename, a deletion, and scores", async ({
  page,
}) => {
  // Two enrollments and four more lines, each tapped key by key.
  test.setTimeout(120_000);
  // GET /api/game/room 404s once on first load, before any room
  // exists; that one is expected (see party.spec.ts).
  const consoleErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error" && !msg.text().includes("404")) consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(err.message));

  await page.goto("/party");
  // A phone gets the game itself, not a notice to use a computer.
  await expect(page.locator("h1")).toHaveText("Your thumbs leave a signature.");
  await expect(page.locator("#app")).not.toContainText("computer");
  await expect(page.locator('[data-level="long"]')).toHaveCount(0);
  await page.click('[data-level="touch"]');
  await expect(page.locator("#name-form")).toBeVisible();
  expect(new URL(page.url()).pathname).toMatch(/^\/r\/[A-HJ-NP-Z2-9]{8}$/);

  const room = await page.evaluate(() => fetch("/api/game/room").then((r) => r.json()));
  expect(room.device_type).toBe("touch");
  expect(room.watching).toBe(false);
  expect(room.phrase).toBe("tap the rhythm of your thumbs");

  // The name step never opens the phone's own keyboard by itself.
  await expect(page.locator("#player-name")).not.toBeFocused();

  const cdp = await cdpFor(page);
  await enrollByTapping(page, cdp, "Ada", ADA);

  // The reveal: the ring, the tap map, and six stats, all from the
  // server's view of the player.
  await expect(page.locator(".solo-ring svg")).toBeVisible();
  await expect(page.locator(".map svg circle")).toHaveCount(14); // one per distinct key of the line
  const stats = page.locator(".traits .trait");
  await expect(stats.locator(".eyebrow")).toHaveText([
    "Pace",
    "Typical hold",
    "Side lean",
    "Height lean",
    "Fastest pair",
    "Slowest pair",
  ]);
  const traits = await page.locator(".traits").innerText();
  expect(traits).not.toContain("undefined");
  expect(traits).not.toContain("NaN");
  // Ada's taps were emulated 0.22 of a key right and 0.2 high.
  await expect(stats.nth(2).locator("b")).toHaveText(/^2[0-4]% right$/);
  await expect(stats.nth(3).locator("b")).toHaveText(/^(1[89]|2[0-2])% high$/);
  await page.click("#to-room");

  await page.click("#add-player");
  await enrollByTapping(page, cdp, "Bob", BOB);
  await page.click("#to-room");

  await expect(card(page, "Ada")).toBeVisible();
  await expect(card(page, "Bob")).toBeVisible();
  await expect(card(page, "Ada").locator("[data-keyboard]")).toHaveText("On this phone");
  await expect(card(page, "Ada").locator(".map svg")).toBeVisible();
  // Two simulated tappers are always there to practice on.
  await expect(card(page, "Sample: Speedy Thumbs")).toBeVisible();
  await expect(card(page, "Sample: One-Finger Pecker")).toBeVisible();

  // Bob attacks Ada, tapping where Bob taps.
  await card(page, "Ada").locator("[data-attack]").click();
  await expect(page.locator("h2")).toHaveText("Pass as Ada");
  await expect(page.locator("#who option")).toHaveText(["Guest", "Bob"]);
  await expect(page.locator("#who")).toHaveValue(/.+/); // Bob, who was just enrolled
  await tapText(page, cdp, BOB);
  const result = page.locator("#result");
  await expect(result).toBeVisible({ timeout: 10_000 });
  await expect(page.locator("#keyboard")).toBeHidden();
  await expect(result.locator(".verdict")).toHaveText("Caught!");
  await expect(result).toContainText("It could tell Bob isn't Ada.");
  // The clue names the actual giveaway, and never says it all fits.
  await expect(page.locator("#clue")).toContainText("wrong tap places");
  await expect(page.locator("#clue")).not.toContainText("all fit");
  await expect(result).toContainText("Pace");
  expect(Number(await tile(page, "Tap place").innerText())).toBeGreaterThan(2);
  await expect(tile(page, "Rhythm")).toHaveText(/^\d+\.\d\d$/);
  await expect(page.locator("#giveaways li")).toHaveCount(3);
  await expect(page.locator("#giveaways")).toContainText("of a key");
  await expect(result.locator(".gauge svg")).toBeVisible();
  await expect(result.locator(".solo-ring .ring-compare")).toHaveCount(1); // the ring overlay
  await expect(result.locator(".map .m-attempt")).toHaveCount(14); // the tap map overlay
  await expect(page.locator("#keyboard-note")).toHaveCount(0); // same phone

  // Go again runs the same attack.
  await page.click("#again");
  await expect(page.locator("h2")).toHaveText("Pass as Ada");
  await expect(page.locator("#keyboard")).toBeVisible();
  await page.click("#to-room");

  // Ada tests herself, tapping where Ada taps.
  await card(page, "Ada").locator("[data-self]").click();
  await expect(page.locator("h2")).toHaveText("Prove it's you");
  await expect(page.locator("#who")).toHaveCount(0);
  await tapText(page, cdp, ADA);
  await expect(result).toBeVisible({ timeout: 10_000 });
  await expect(result.locator(".verdict")).toHaveText(/^(That's you|Who are you\?)$/);
  // Her taps landed where they always do, whatever the timing did.
  expect(Number(await tile(page, "Tap place").innerText())).toBeLessThan(1);
  await page.click("#to-room");

  // Ada tries a new grip: the same line, landing where Bob lands.
  await card(page, "Ada").locator("[data-grip]").click();
  await expect(page.locator("h2")).toHaveText("Try a different grip");
  await tapText(page, cdp, BOB);
  await expect(result).toBeVisible({ timeout: 10_000 });
  await expect(result.locator(".verdict")).toHaveText("Who are you?");
  await expect(result).toContainText("The new grip was enough to throw it off.");
  await page.click("#to-room");

  // A replay: run by the server from Ada's typical timing and her
  // average tap positions, played back on the line and the keys.
  await card(page, "Ada").locator("[data-attack]").click();
  await page.click("#replay");
  await expect(page.locator("h2")).toHaveText("Replay attack on Ada");
  await expect(result).toBeVisible({ timeout: 15_000 });
  await expect(result.locator(".verdict")).toHaveText("Replay wins");
  await expect(page.locator("#clue")).toBeVisible();
  await expect(page.locator("#giveaways")).toHaveCount(0); // nobody tapped it
  await page.click("#to-room");

  // Rename Bob.
  await card(page, "Bob").locator("[data-rename]").click();
  await page.locator("form[data-rename-form] input[name=name]").fill("Bobby");
  await page.locator("form[data-rename-form] button[type=submit]").click();
  await expect(card(page, "Bobby")).toBeVisible();

  // Scores: pace, Rhythm, and Place for every attempt.
  await page.click('[data-tab="scores"]');
  await expect(page.locator("thead th")).toHaveText([
    "Tapping",
    "Target",
    "Type",
    "Pace",
    "Rhythm",
    "Place",
    "Total",
    "Limit",
    "Result",
  ]);
  const rows = page.locator("tbody tr");
  await expect(rows).toHaveCount(4);
  await expect(rows.nth(0)).toContainText("Replay");
  await expect(rows.nth(1)).toContainText("New grip");
  await expect(rows.nth(2)).toContainText("Own");
  await expect(rows.nth(3)).toContainText("Attack");
  await expect(rows.nth(3)).toContainText("Caught!");
  const scores = await page.locator("tbody").innerText();
  expect(scores).not.toContain("undefined");
  expect(scores).not.toContain("NaN");

  // Delete Bobby: gone from the room, and his attack with him.
  await page.click('[data-tab="room"]');
  await card(page, "Bobby").locator("[data-delete]").click();
  await expect(card(page, "Bobby")).toHaveCount(0);
  await page.click('[data-tab="scores"]');
  await expect(page.locator("tbody tr")).toHaveCount(3);

  // New room asks first, then opens a fresh touch room on the name step.
  await page.click('[data-tab="room"]');
  const oldRoom = new URL(page.url()).pathname;
  await page.click("#new-room");
  await expect(page.locator("#confirm")).toContainText("Start a new room?");
  await page.click("#confirm-yes");
  await expect(page.locator("#name-form")).toBeVisible();
  expect(new URL(page.url()).pathname).not.toBe(oldRoom);
  const fresh = await page.evaluate(() => fetch("/api/game/room").then((r) => r.json()));
  expect(fresh.players).toEqual([]);
  expect(fresh.device_type).toBe("touch");

  expect(consoleErrors).toEqual([]);
});

test("a phone's room survives a reload, tap maps included", async ({ page }) => {
  await page.goto("/party");
  await page.click('[data-level="touch"]');
  const cdp = await cdpFor(page);
  await enrollByTapping(page, cdp, "Casey");
  await page.click("#to-room");
  await expect(card(page, "Casey")).toBeVisible();

  await page.reload();
  await expect(card(page, "Casey")).toBeVisible({ timeout: 10_000 });
  await expect(card(page, "Casey").locator(".map svg circle")).toHaveCount(14);
  await expect(card(page, "Casey").locator("[data-grip]")).toBeVisible();
});

test("How it works on a phone says what the touch game sends and keeps", async ({ page }) => {
  await page.goto("/party");
  await page.click('[data-level="touch"]');
  await expect(page.locator("#name-form")).toBeVisible();
  await page.click("#home");
  await page.click('[data-tab="how"]');

  const how = page.locator("#app");
  await expect(how).toContainText("where on the key it lands");
  await expect(how).toContainText("This is a game, not security.");
  await expect(how).toContainText("A different grip or a different phone can change your signature");
  await expect(how).toContainText("screen reader");
  // The keyboard benchmark's number isn't the touch game's accuracy.
  await expect(how).not.toContainText("9.1");

  await page.click("summary");
  const privacy = page.locator("details");
  await expect(privacy).toContainText("where on the key it landed are sent to the server for scoring");
  await expect(privacy).toContainText("Raw taps are discarded right after scoring");
  await expect(privacy).toContainText("average tap positions and timing statistics in memory");
  await expect(privacy).toContainText("Anyone who has the link can join");
  await expect(privacy).toContainText("name, rhythm ring, tap map, and scores");
});
