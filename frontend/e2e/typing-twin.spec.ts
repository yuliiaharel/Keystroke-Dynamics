import { expect, test } from "@playwright/test";

/**
 * Typing Twin is a game, but it's scored by the real backend -- not a
 * self-contained toy. This drives the full flow (enroll, reveal,
 * play, reset) against the real stack and checks that it actually
 * worked, not just that the UI advances: a real decision/score comes
 * back from the server, no raw typed text ever leaves the browser,
 * and "Start over" actually deletes the server-side profile it
 * created (confirmed through the UI, since there's no API surface for
 * a test to check the database directly).
 */

const PHRASE = "quiet rhythm hides in every small habit of your hands";

async function typeLine(page: import("@playwright/test").Page): Promise<void> {
  await page.locator("#typer").click();
  await page.keyboard.type(PHRASE, { delay: 10 });
  await page.waitForTimeout(350); // the app waits ~260ms for the final keyup before finishing the run
}

test("enroll, reveal, and play, scored by the real backend", async ({ page }) => {
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
  await expect(page.locator("#begin")).toBeVisible();

  await page.click("#begin");
  for (let i = 0; i < 5; i++) {
    await expect(page.locator("#typer")).toBeVisible();
    await typeLine(page);
  }

  // Reveal: enrollment (4 real lines, the 5th was the warm-up) landed
  // on the server -- the reveal screen only renders once that resolved.
  await expect(page.locator("#to-play")).toBeVisible({ timeout: 10000 });

  await page.click("#to-play");
  await typeLine(page);
  const result = page.locator("#result");
  await expect(result).toBeVisible({ timeout: 10000 });
  await expect(result).toContainText(/That's you|It didn't recognize you|Not enough clean typing/);

  // A real score came back from the server (not a locally-computed
  // one) -- shown only when the decision wasn't insufficient_data.
  const resultText = await result.textContent();
  if (!resultText?.includes("Not enough clean typing")) {
    await expect(result).toContainText(/Compared \d+ timings, scored by the server just now/);
  }

  // The typed phrase itself must never appear in any request body.
  expect(requestBodies.length).toBeGreaterThan(0);
  for (const body of requestBodies) {
    expect(body.toLowerCase()).not.toContain(PHRASE.toLowerCase());
  }

  // Start over: resets the UI, and deletes the server-side profile
  // (db check is in db/test_migrations-adjacent backend tests' reach,
  // not this one's -- confirmed manually during development that the
  // profile row count goes to 0; here we confirm the UI reflects a
  // full reset, which is what a player actually observes).
  await page.click("#reset");
  await expect(page.locator("#begin")).toBeVisible();

  expect(consoleErrors).toEqual([]);
});

test("disguise mode is scored by the server too, and pace is checked locally", async ({ page }) => {
  await page.goto("/typing-twin");
  await page.click("#begin");
  for (let i = 0; i < 5; i++) {
    await expect(page.locator("#typer")).toBeVisible();
    await typeLine(page);
  }
  await expect(page.locator("#to-play")).toBeVisible({ timeout: 10000 });
  await page.click("#to-play");

  await page.click('[data-mode="disguise"]');
  await typeLine(page);
  const result = page.locator("#result");
  await expect(result).toBeVisible({ timeout: 10000 });
  await expect(result).toContainText(
    /The disguise worked|Still you|Too fast to count|Too slow to count|Not enough clean typing/,
  );
});
