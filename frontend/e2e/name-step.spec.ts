import { expect, test, type Page } from "@playwright/test";

import { typeLine } from "./room-helpers";

/**
 * The "Who's typing?" step: the name field arrives filled with a
 * generated name from the real backend, which the player can keep,
 * type over, shuffle, or clear.
 */

/** The shape of every generated name: "Quiet Otter". */
const GENERATED = /^[A-Z][a-z]+ [A-Z][a-z]+$/;

async function openNameStep(page: Page): Promise<void> {
  await page.goto("/party");
  await page.click('[data-level="sentence"]');
  await expect(page.locator("#name-form")).toBeVisible();
}

async function typeEnrollment(page: Page): Promise<void> {
  for (let i = 0; i < 5; i++) {
    await expect(page.locator("#typer")).toBeVisible();
    await typeLine(page);
  }
  await expect(page.locator("text=This is how you type.")).toBeVisible({ timeout: 10000 });
}

const isWhollySelected = (page: Page): Promise<boolean> =>
  page.evaluate(() => {
    const input = document.getElementById("player-name") as HTMLInputElement;
    return input.value.length > 0 && input.selectionStart === 0 && input.selectionEnd === input.value.length;
  });

test("the name field offers a generated name that can be shuffled or typed over", async ({ page }) => {
  await openNameStep(page);
  const name = page.locator("#player-name");

  await expect(name).toHaveValue(GENERATED);
  await expect(name).toBeFocused();
  await expect(name).toHaveAttribute("maxlength", "24");
  expect(await isWhollySelected(page)).toBe(true);
  await expect(page.locator("#app")).toContainText("Keep the suggested name, type your own, or shuffle for another.");
  await expect(page.locator("#app")).not.toContainText("Leave the name blank");

  // Shuffle picks another. A shuffle can land on the same name again
  // (rarely), hence the retry.
  const first = await name.inputValue();
  await expect(async () => {
    await page.click("#shuffle-name");
    await expect(name).not.toHaveValue(first, { timeout: 1000 });
  }).toPass();
  await expect(name).toHaveValue(GENERATED);
  await expect(name).toBeFocused();
  expect(await isWhollySelected(page)).toBe(true);

  // Coming back to the field with the mouse selects the suggestion
  // again, so typing replaces it rather than adding to it.
  await page.click("h2");
  await expect(name).not.toBeFocused();
  await name.click();
  await page.keyboard.type("<i>Zed</i>");
  await expect(name).toHaveValue("<i>Zed</i>");

  // A typed name isn't selected on focus: that would make fixing a
  // typo retype the lot.
  await page.click("h2");
  await name.click();
  expect(await isWhollySelected(page)).toBe(false);

  // The typed name is what's enrolled, shown as text and not markup.
  await page.click("#name-form button[type=submit]");
  await typeEnrollment(page);
  await expect(page.locator(".eyebrow", { hasText: "<i>Zed</i>'s signature" })).toBeVisible();
  await expect(page.locator("#app i")).toHaveCount(0);
});

test("on one keyboard, each new player is offered a name nobody in the room has", async ({ page }) => {
  await openNameStep(page);
  const name = page.locator("#player-name");

  // Enter in the field keeps the suggestion and starts the typing.
  await expect(name).toHaveValue(GENERATED);
  const first = await name.inputValue();
  await page.keyboard.press("Enter");
  await typeEnrollment(page);
  await expect(page.locator(".eyebrow", { hasText: `${first}'s signature` })).toBeVisible();

  // The second player's suggestion is never the first player's name.
  await page.click("#to-room");
  await page.click("#add-player");
  await expect(name).toHaveValue(GENERATED);
  expect(await name.inputValue()).not.toBe(first);

  // Cleared and submitted, the server still generates one.
  await name.fill("");
  await page.click("#name-form button[type=submit]");
  await typeEnrollment(page);
  await page.click("#to-room");
  const names = await page.evaluate(() =>
    fetch("/api/game/room")
      .then((r) => r.json())
      .then((room) => room.players.map((p: { name: string }) => p.name)),
  );
  expect(names).toHaveLength(2);
  expect(names[0]).toBe(first);
  expect(names[1]).toMatch(GENERATED);
  expect(names[1]).not.toBe(first);
});

test("a suggestion that arrives late never overwrites a name already typed", async ({ page }) => {
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/game/room/name-suggestion", async (route) => {
    await held;
    await route.continue();
  });

  await openNameStep(page);
  const name = page.locator("#player-name");
  await expect(name).toHaveValue("");
  await name.fill("Dana");

  const answered = page.waitForResponse("**/api/game/room/name-suggestion");
  release();
  await answered;
  await page.waitForTimeout(100); // long enough for the page to have acted on the answer
  await expect(name).toHaveValue("Dana");
});
