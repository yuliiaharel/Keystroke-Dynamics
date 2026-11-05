import { expect, test } from "@playwright/test";

/**
 * Not a behavior test -- just walks each main page and the two
 * post-action states, saving a screenshot of each for review, and
 * fails if the browser console logged any error on any of them.
 */

function uniqueUsername(): string {
  return `shotuser${Date.now().toString(36)}${Math.floor(Math.random() * 1000)}`;
}

test("screenshot every main page, with no console errors", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(`[${page.url()}] ${msg.text()}`);
  });
  page.on("pageerror", (err) => {
    consoleErrors.push(`[${page.url()}] ${err.message}`);
  });

  await page.goto("/");
  await page.screenshot({ path: "screenshots/01-home.png", fullPage: true });

  await page.goto("/create-profile");
  await page.screenshot({ path: "screenshots/02-create-profile-step1.png", fullPage: true });

  const username = uniqueUsername();
  const password = "correct-password-123";
  await page.fill("#username", username);
  await page.fill("#password", password);
  await page.click("#register-form button[type=submit]");
  await expect(page.locator("#step2")).toBeVisible();
  await page.screenshot({ path: "screenshots/03-create-profile-step2.png", fullPage: true });

  await page.locator("#sample-text").pressSequentially(
    "A long time ago, in a galaxy far, far away",
    { delay: 15 },
  );
  await page.click("#sample-form button[type=submit]");
  await expect(page.locator("#step-done")).toBeVisible();
  await page.screenshot({ path: "screenshots/04-create-profile-done.png", fullPage: true });

  await page.goto("/authenticate");
  await page.screenshot({ path: "screenshots/05-authenticate.png", fullPage: true });

  await page.fill("#username", username);
  await page.fill("#password", password);
  await page.locator("#sample-text").pressSequentially(
    "A long time ago, in a galaxy far, far away",
    { delay: 15 },
  );
  await page.click("#auth-form button[type=submit]");
  await expect(page.locator("#result")).toBeVisible();
  await page.screenshot({ path: "screenshots/06-authenticate-result.png", fullPage: true });

  await page.goto("/how-it-works");
  await page.screenshot({ path: "screenshots/07-how-it-works.png", fullPage: true });

  await page.goto("/about");
  await page.screenshot({ path: "screenshots/08-about.png", fullPage: true });

  await page.goto("/finish");
  await page.screenshot({ path: "screenshots/09-finish.png", fullPage: true });

  expect(consoleErrors).toEqual([]);
});
