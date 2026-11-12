import { expect, type APIRequestContext, type BrowserContext, type Page } from "@playwright/test";

/** Shared by the room specs (docs/plans/active/ROOMS_PLAN.md Phase 3). */

export const PHRASE = "quiet rhythm hides in every small habit of your hands";
/** The plan's bar for a change reaching another browser. */
export const LIVE_MS = 2_000;

/** One clean line of the phrase, as the capture module would send it. */
export const LINE = [...PHRASE].flatMap((ch, i) => {
  const code = ch === " " ? "Space" : `Key${ch.toUpperCase()}`;
  return [
    { code, action: "down", t_ms: i * 150 },
    { code, action: "up", t_ms: i * 150 + 80 },
  ];
});

export async function post(request: APIRequestContext, baseURL: string, path: string, data?: unknown): Promise<any> {
  const response = await request.post(path, { data, headers: { Origin: baseURL } });
  expect(response.ok(), `${path}: ${response.status()} ${await response.text()}`).toBe(true);
  return response.status() === 204 ? null : response.json();
}

/** Enrolls a player without the typing, for tests about something else. */
export const enrollByApi = (context: BrowserContext, baseURL: string, name: string): Promise<any> =>
  post(context.request, baseURL, "/api/game/players", { name, training_lines: Array(5).fill(LINE) });

export async function typeLine(page: Page): Promise<void> {
  await page.locator("#typer").click();
  await page.keyboard.type(PHRASE, { delay: 10 });
  await page.waitForTimeout(350); // the app waits ~260ms for the final keyup before finishing the run
}

/** Enrolls a player the way a person does, from the name step to the room. */
export async function enrollByTyping(page: Page, name: string): Promise<void> {
  await page.fill("#player-name", name);
  await page.click("#name-form button[type=submit]");
  for (let i = 0; i < 5; i++) {
    await expect(page.locator("#typer")).toBeVisible();
    await typeLine(page);
  }
  await expect(page.locator("text=This is how you type.")).toBeVisible({ timeout: 10000 });
  await page.click("#to-room");
}

export const card = (page: Page, name: string) =>
  page.locator("article.card", { has: page.locator("h3", { hasText: new RegExp(`^${name}$`) }) });

export const roomPathOf = (page: Page): string => new URL(page.url()).pathname;
