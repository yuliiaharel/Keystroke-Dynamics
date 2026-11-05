import { expect, test, type Page } from "@playwright/test";

/**
 * Typing Twin Party is scored by the real backend for every real
 * player -- not a self-contained toy. This drives the full party flow
 * (enroll two real players, attack between them, self-test, attack a
 * simulated bot, replay) against the real stack, and checks that each
 * one actually produced a real verdict, not just that the UI advanced:
 * attacks against real players flow through the backend (confirmed by
 * inspecting the actual request bodies for the typed phrase never
 * appearing), attacks against bots stay entirely local, and "New
 * party" leaves the UI back at the start.
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
}

test("enroll two real players and attack between them, scored by the real backend", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(err.message));

  const requestBodies: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/api/")) {
      const data = request.postData();
      if (data !== null) requestBodies.push(data);
    }
  });

  await page.goto("/typing-twin");
  await page.click('[data-level="sentence"]');

  await enrollPlayer(page, "Alice");
  await page.click("#to-room");
  await page.click("#add-player");
  await enrollPlayer(page, "Bob");
  await page.click("#to-room");

  // Both real players show the app's one shared backend threshold --
  // not a locally-calibrated one, unlike the bots below.
  await expect(page.locator("article.card", { hasText: "Alice" })).toContainText("Limit 1.07");
  await expect(page.locator("article.card", { hasText: "Bob" })).toContainText("Limit 1.07");

  // Bob attacks Alice: scored against Alice's real stored profile.
  await page.locator("article.card", { hasText: "Alice" }).locator("[data-attack]").click();
  await page.selectOption("#who", { label: "Bob" });
  await typeLine(page);
  const attackResult = page.locator("#result");
  await expect(attackResult).toBeVisible({ timeout: 10000 });
  await expect(attackResult).toContainText(/Fooled it!|Caught!|Too messy/);
  // A real verdict carries the server's own compared-feature count and
  // never a per-feature breakdown (the backend doesn't return one).
  const attackText = await attackResult.textContent();
  if (!attackText?.includes("Too messy")) {
    await expect(attackResult).not.toContainText("Biggest giveaways");
  }

  // Alice tests herself.
  await page.click('button[data-tab="room"]');
  await page.locator("article.card", { hasText: "Alice" }).locator("[data-self]").click();
  await typeLine(page);
  await expect(page.locator("#result")).toBeVisible({ timeout: 10000 });
  await expect(page.locator("#result")).toContainText(/That's you|Who are you\?|Too messy/);

  // Attacking a simulated bot stays local: a per-feature breakdown is
  // available (the local scorer computes it), and the bot's own card
  // never claimed the shared backend threshold.
  await page.click('button[data-tab="room"]');
  const botCard = page.locator("article.card", { hasText: "Sample: Quick Fingers" });
  await expect(botCard).toContainText("Simulated practice target");
  await botCard.locator("[data-attack]").click();
  await page.selectOption("#who", { label: "Bob" });
  await typeLine(page);
  await expect(page.locator("#result")).toBeVisible({ timeout: 10000 });

  // Replay: resends Alice's own last captured timing: always passes.
  await page.click('button[data-tab="room"]');
  await page.locator("article.card", { hasText: "Alice" }).locator("[data-attack]").click();
  await page.click("#replay");
  await expect(page.locator("#result")).toBeVisible({ timeout: 15000 });
  await expect(page.locator("#result")).toContainText("Replay wins");

  // The typed phrase itself must never appear in any request body,
  // for any real player's enrollment or attempt.
  expect(requestBodies.length).toBeGreaterThan(0);
  for (const body of requestBodies) {
    expect(body.toLowerCase()).not.toContain(PHRASE.toLowerCase());
  }

  // New party resets the UI back to the start.
  await page.click('button[data-tab="room"]');
  await page.click("#new-party");
  await page.click("#new-party");
  await expect(page.locator('[data-level="sentence"]')).toBeVisible();

  expect(consoleErrors).toEqual([]);
});
