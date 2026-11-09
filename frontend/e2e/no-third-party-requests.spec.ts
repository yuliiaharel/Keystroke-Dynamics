import { expect, test } from "@playwright/test";

/**
 * Confirms the Done-when requirement "no request goes to a
 * third-party host" by recording every single network request the
 * page makes (not just the ones to /api/*) while playing through
 * enrollment and an attack on the sentence level -- the page that's
 * most likely to regress this, since it's the one that used to load
 * Google Fonts (design/typing-twin-party.html) before they were
 * self-hosted (static/css/fonts.css).
 */

const PHRASE = "quiet rhythm hides in every small habit of your hands";

test("the party page makes no third-party requests", async ({ page, baseURL }) => {
  const ownHost = new URL(baseURL ?? "http://127.0.0.1:8000").host;
  const hosts = new Set<string>();
  page.on("request", (request) => {
    hosts.add(new URL(request.url()).host);
  });

  await page.goto("/party");
  await page.click('[data-level="sentence"]');
  await page.fill("#player-name", "Dana");
  await page.click("#name-form button[type=submit]");
  for (let i = 0; i < 5; i++) {
    await expect(page.locator("#typer")).toBeVisible();
    await page.locator("#typer").click();
    await page.keyboard.type(PHRASE, { delay: 10 });
    await page.waitForTimeout(350);
  }
  await expect(page.locator("text=This is how you type.")).toBeVisible({ timeout: 10000 });
  await page.click("#to-room");

  await page
    .locator("article.card", { hasText: "Sample: Quick Fingers" })
    .locator("[data-attack]")
    .click();
  await page.locator("#typer").click();
  await page.keyboard.type(PHRASE, { delay: 10 }); // the sentence level's own phrase
  await page.waitForTimeout(350);
  await expect(page.locator("#result")).toBeVisible({ timeout: 10000 });

  expect(hosts.size).toBeGreaterThan(0);
  for (const host of hosts) {
    expect(host).toBe(ownHost);
  }
});
