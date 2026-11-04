import { expect, test } from "@playwright/test";

/**
 * Phase 7 review finding: the authenticate page's capture buffer was
 * never reset between attempts, so retyping after a failed login
 * blended the failed attempt's keystrokes into the next request,
 * scored against timestamps relative to the *first* attempt's first
 * keydown. Confirms the fix by inspecting the actual request bodies:
 * typing the identical phrase twice (once per attempt) must produce
 * two requests with the *same* event count -- a still-accumulating
 * buffer would make the second request's count roughly double.
 */

const PHRASE = "retry phrase";

function uniqueUsername(): string {
  return `e2eretry${Date.now().toString(36)}${Math.floor(Math.random() * 1000)}`;
}

test("retrying after a failed login does not blend in the previous attempt's keystrokes", async ({
  page,
}) => {
  const username = uniqueUsername();
  const password = "correct-password-123";

  await page.goto("/create-profile");
  await page.fill("#username", username);
  await page.fill("#password", password);
  await page.click("#register-form button[type=submit]");
  await expect(page.locator("#step2")).toBeVisible();
  await page.locator("#sample-text").pressSequentially("enrollment sample text", { delay: 10 });
  await page.click("#sample-form button[type=submit]");
  await expect(page.locator("#step-done")).toBeVisible();

  const sampleLengths: number[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/api/login")) {
      const data = request.postData();
      if (data !== null) {
        const sample = JSON.parse(data).sample as unknown[] | null;
        sampleLengths.push(sample?.length ?? 0);
      }
    }
  });

  await page.goto("/authenticate");
  await page.fill("#username", username);

  await page.fill("#password", "wrong-password");
  await page.locator("#sample-text").pressSequentially(PHRASE, { delay: 10 });
  await page.click("#auth-form button[type=submit]");
  await expect(page.locator("#form-error")).toBeVisible();

  await page.fill("#password", password);
  await page.locator("#sample-text").fill(""); // clearing the textarea does not clear capture
  await page.locator("#sample-text").pressSequentially(PHRASE, { delay: 10 });
  await page.click("#auth-form button[type=submit]");
  await expect(page.locator("#result")).toBeVisible();

  expect(sampleLengths).toHaveLength(2);
  const [firstAttemptCount, secondAttemptCount] = sampleLengths;
  expect(firstAttemptCount).toBeGreaterThan(0);
  // Same phrase both times: a reset buffer gives (roughly) the same
  // count; an accumulating one gives the second request close to
  // double the first.
  expect(secondAttemptCount).toBeLessThan(firstAttemptCount! * 1.5);
});
