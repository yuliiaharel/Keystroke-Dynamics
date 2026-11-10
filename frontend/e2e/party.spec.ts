import { expect, test, type Page } from "@playwright/test";

/**
 * The anonymous party game (docs/plans/done/PARTY_LAUNCH_PLAN.md Part 1), driven end
 * to end against the real backend: two players enrolled on one
 * keyboard, an attack, a server-run replay, a rename, a deletion,
 * and the scores page. Every verdict comes from a real
 * POST /api/game/attempts or /api/game/replay round trip -- nothing
 * here is scored locally.
 */

const PHRASE = "quiet rhythm hides in every small habit of your hands";

async function typeLine(page: Page): Promise<void> {
  await page.locator("#typer").click();
  await page.keyboard.type(PHRASE, { delay: 10 });
  await page.waitForTimeout(350); // the app waits ~260ms for the final keyup before finishing the run
}

async function enrollPlayer(page: Page, name: string): Promise<void> {
  await page.fill("#player-name", name);
  await page.click("#name-form button[type=submit]");
  for (let i = 0; i < 5; i++) {
    await expect(page.locator("#typer")).toBeVisible();
    await typeLine(page);
  }
  await expect(page.locator("text=This is how you type.")).toBeVisible({ timeout: 10000 });

  // The reveal's four stats come from the player's server-provided
  // notes. They used to read enrollment lines that had already been
  // cleared, and showed "undefined" and NaN.
  const stats = page.locator(".traits .trait");
  await expect(stats).toHaveCount(4);
  const text = await page.locator(".traits").innerText();
  expect(text).not.toContain("undefined");
  expect(text).not.toContain("NaN");
  await expect(stats.locator(".eyebrow")).toHaveText([
    "Pace",
    "Typical hold",
    "Fastest pair",
    "Slowest pair",
  ]);
  await expect(stats.nth(0).locator("b")).toHaveText(/^\d+ wpm$/);
  await expect(stats.nth(1).locator("b")).toHaveText(/^\d+ ms$/);
}

test("a full one-keyboard party: two players, an attack, a replay, a rename, a deletion, and the scores page", async ({
  page,
}) => {
  // GET /api/game/room legitimately 404s once, on first load, before
  // any room exists (party.ts probes for one in the background and
  // catches the rejection) -- that one network-level 404 log is
  // expected, not a bug, so it's filtered out below rather than
  // loosening the check for every other console error.
  const consoleErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error" && !msg.text().includes("404")) consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(err.message));

  await page.goto("/party");
  await page.click('[data-level="sentence"]');
  // Wait for the party the click just created to actually exist
  // server-side (the name form only renders once it does) before
  // querying it directly below -- otherwise the fetch can race the
  // click's own POST and read back a 404/no session yet.
  await expect(page.locator("#name-form")).toBeVisible();

  // Scores are saved automatically, so there's a memo and nothing to
  // tick. The memo's presence must track the server's own
  // scores_enabled, not any hardcoded assumption -- this suite runs
  // against both the default (off) stack and, run locally with
  // SCORES_DATABASE_URL set, an on one. With collection off nothing
  // is saved, so the memo isn't shown.
  const party = await page.evaluate(() => fetch("/api/game/room").then((r) => r.json()));
  const memo = page.locator("#scores-memo");
  const expectMemo = async (): Promise<void> => {
    if (party.scores_enabled) {
      await expect(memo).toBeVisible();
      await expect(memo).toContainText("This site saves a few numbers about each result");
    } else {
      await expect(memo).toHaveCount(0);
    }
    await expect(page.locator("#app input[type=checkbox]")).toHaveCount(0);
  };
  await expectMemo();
  await expect(page.locator("#enroll-share-scores")).toHaveCount(0);

  await enrollPlayer(page, "Alice");
  await page.click("#to-room");
  await page.click("#add-player");
  await enrollPlayer(page, "Bob");
  await page.click("#to-room");

  await expect(page.locator("article.card", { hasText: "Alice" })).toBeVisible();
  await expect(page.locator("article.card", { hasText: "Bob" })).toBeVisible();
  // Three simulated bots are always present alongside real players.
  await expect(page.locator("article.card", { hasText: "Sample: Quick Fingers" })).toBeVisible();

  // Bob attacks Alice -- scored by the real backend against Alice's
  // actual stored profile.
  await page.locator("article.card", { hasText: "Alice" }).locator("[data-attack]").click();
  // "Who's typing?" defaults to whoever was just enrolled (Bob), not
  // Guest. The memo is the same for a Guest and for an enrolled
  // player, and neither is asked anything.
  await page.selectOption("#who", { label: "Guest" });
  await expectMemo();
  await expect(page.locator("#guest-share-scores")).toHaveCount(0);
  await page.selectOption("#who", { label: "Bob" });
  await expectMemo();
  await typeLine(page);
  const attackResult = page.locator("#result");
  await expect(attackResult).toBeVisible({ timeout: 10000 });
  await expect(attackResult).toContainText(/Fooled it!|Caught!|Too messy/);
  await expectMemo(); // still there, under the result
  // Pace and a one-line clue show on every scoreable result
  // (docs/plans/done/PARTY_LAUNCH_PLAN.md section 8) -- "Too messy" is the one
  // outcome that hides both, so only assert this when the attack
  // actually got scored.
  const resultText = (await attackResult.textContent()) ?? "";
  if (!resultText.includes("Too messy")) {
    await expect(page.locator("#clue")).toBeVisible();
    await expect(attackResult).toContainText("Pace");
  }

  // Replay: the server runs it from Alice's own median timing, never
  // a raw recording, and it reliably passes against her own limit.
  await page.click('button[data-tab="room"]');
  await page.locator("article.card", { hasText: "Alice" }).locator("[data-attack]").click();
  await page.click("#replay");
  await expect(page.locator("#result")).toBeVisible({ timeout: 15000 });
  await expect(page.locator("#result")).toContainText("Replay wins");
  await expect(page.locator("#clue")).toBeVisible();

  // Rename Bob.
  await page.click('button[data-tab="room"]');
  await page.locator("article.card", { hasText: "Bob" }).locator("[data-rename]").click();
  await page.locator("form[data-rename-form] input[name=name]").fill("Bobby");
  await page.locator("form[data-rename-form] button[type=submit]").click();
  await expect(page.locator("article.card", { hasText: "Bobby" })).toBeVisible();

  // Delete Bobby.
  await page.locator("article.card", { hasText: "Bobby" }).locator("[data-delete]").click();
  await expect(page.locator("article.card", { hasText: "Bobby" })).toHaveCount(0);

  // Scores page.
  await page.click('button[data-tab="scores"]');
  await expect(page.locator("h2", { hasText: "Scores" })).toBeVisible();
  await expect(page.locator("text=Latest attempts")).toBeVisible();

  // New room asks first, then opens a fresh, empty room at its own
  // link, on the name step.
  await page.click('button[data-tab="room"]');
  const oldRoom = new URL(page.url()).pathname;
  await page.click("#new-room");
  await expect(page.locator("#confirm")).toContainText("Start a new room?");
  await page.click("#confirm-yes");
  await expect(page.locator("#name-form")).toBeVisible();
  expect(new URL(page.url()).pathname).toMatch(/^\/r\/[A-HJ-NP-Z2-9]{8}$/);
  expect(new URL(page.url()).pathname).not.toBe(oldRoom);
  const fresh = await page.evaluate(() => fetch("/api/game/room").then((r) => r.json()));
  expect(fresh.players).toEqual([]);

  // Leave room asks first too, then resets the UI back to the start.
  await enrollPlayer(page, "Dana");
  await page.click("#to-room");
  await page.click("#leave-room");
  await page.click("#confirm-yes");
  await expect(page.locator('[data-level="sentence"]')).toBeVisible();
  expect(new URL(page.url()).pathname).not.toMatch(/^\/r\//);

  expect(consoleErrors).toEqual([]);
});

test("the party survives a page reload", async ({ page }) => {
  await page.goto("/party");
  await page.click('[data-level="sentence"]');
  await enrollPlayer(page, "Casey");
  await page.click("#to-room");
  await expect(page.locator("article.card", { hasText: "Casey" })).toBeVisible();

  await page.reload();
  await expect(page.locator("article.card", { hasText: "Casey" })).toBeVisible({ timeout: 10000 });
});
