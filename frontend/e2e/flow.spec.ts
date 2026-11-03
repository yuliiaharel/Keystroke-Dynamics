import { expect, test } from "@playwright/test";

/**
 * Registers a new user, enrolls one sample with scripted keystrokes,
 * logs back in with another scripted sample, and checks that a
 * result is shown. Requires the app and a real Postgres to already be
 * running (see frontend/README.md) -- this is an end-to-end test
 * against the real stack, not a mock.
 */

const PHRASE = "the quick brown fox jumps over the lazy dog";

function uniqueUsername(): string {
  return `e2euser${Date.now().toString(36)}${Math.floor(Math.random() * 1000)}`;
}

test("register, enroll, log in, and see a typing result", async ({ page }) => {
  const username = uniqueUsername();
  const password = "correct-password-123";

  await page.goto("/create-profile");
  await page.fill("#username", username);
  await page.fill("#password", password);
  await page.click("#register-form button[type=submit]");

  await expect(page.locator("#step2")).toBeVisible();
  await page.locator("#sample-text").pressSequentially(PHRASE, { delay: 20 });
  await page.click("#sample-form button[type=submit]");

  await expect(page.locator("#step-done")).toBeVisible();

  await page.goto("/authenticate");
  await page.fill("#username", username);
  await page.fill("#password", password);
  await page.locator("#sample-text").pressSequentially(PHRASE, { delay: 20 });
  await page.click("#auth-form button[type=submit]");

  const result = page.locator("#result");
  await expect(result).toBeVisible();
  await expect(result).toContainText(/MATCH|NO MATCH|INSUFFICIENT DATA/);

  await expect(page.locator("#delete-section")).toBeVisible();
  await page.click("#delete-button");
  await expect(page.locator("#delete-section")).toBeHidden();
});
