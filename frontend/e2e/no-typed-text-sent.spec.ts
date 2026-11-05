import { expect, test } from "@playwright/test";

/**
 * Confirms the plan's "No page sends the typed text" requirement by
 * inspecting the actual outgoing request bodies, not just the
 * capture module's unit-tested output -- this is what the browser
 * really puts on the wire for /api/profile/samples and /api/login.
 */

const TELLTALE_PHRASE = "VeryDistinctiveSentenceNobodyShouldEverTransmit";

function uniqueUsername(): string {
  return `e2etext${Date.now().toString(36)}${Math.floor(Math.random() * 1000)}`;
}

test("the typed phrase itself never appears in a request body", async ({ page }) => {
  const username = uniqueUsername();
  const password = "correct-password-123";
  const bodies: string[] = [];

  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/api/")) {
      const data = request.postData();
      if (data !== null) bodies.push(data);
    }
  });

  await page.goto("/create-profile");
  await page.fill("#username", username);
  await page.fill("#password", password);
  await page.click("#register-form button[type=submit]");
  await expect(page.locator("#step2")).toBeVisible();

  await page.locator("#sample-text").pressSequentially(TELLTALE_PHRASE, { delay: 20 });
  await page.click("#sample-form button[type=submit]");
  await expect(page.locator("#step-done")).toBeVisible();

  expect(bodies.length).toBeGreaterThan(0);
  for (const body of bodies) {
    expect(body).not.toContain(TELLTALE_PHRASE);
    expect(body.toLowerCase()).not.toContain(TELLTALE_PHRASE.toLowerCase());
  }
});
