import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";

/**
 * docs/plans/active/ROOMS_PLAN.md Phase 2: two browsers in one room
 * see each other's changes without a refresh -- through the event
 * stream, and through polling when the stream is blocked.
 *
 * The second browser joins with the request a room link makes
 * (rooms.spec.ts covers the link itself), then opens the page.
 * Players are enrolled the same way, to keep the typing out of a test
 * that's about something else. Every assertion is on what the page
 * shows.
 */

const PHRASE = "quiet rhythm hides in every small habit of your hands";
/** The plan's bar for the stream. */
const LIVE_MS = 2_000;
/** Polling can't beat its own 5-second interval (live.ts's
 * POLL_VISIBLE_MS); allow one interval plus the same 2 seconds. */
const POLLED_MS = 5_000 + LIVE_MS;

const LINE = [...PHRASE].flatMap((ch, i) => {
  const code = ch === " " ? "Space" : `Key${ch.toUpperCase()}`;
  return [
    { code, action: "down", t_ms: i * 150 },
    { code, action: "up", t_ms: i * 150 + 80 },
  ];
});

async function post(context: BrowserContext, baseURL: string, path: string, data?: unknown): Promise<any> {
  const response = await context.request.post(path, { data, headers: { Origin: baseURL } });
  expect(response.ok(), `${path}: ${response.status()} ${await response.text()}`).toBe(true);
  return response.status() === 204 ? null : response.json();
}

const enroll = (context: BrowserContext, baseURL: string, name: string): Promise<any> =>
  post(context, baseURL, "/api/game/players", { name, training_lines: Array(5).fill(LINE) });

const card = (page: Page, name: string) => page.locator("article.card h3", { hasText: new RegExp(`^${name}$`) });

/** Host and friend in one room, each looking at the room view. */
async function twoBrowsersInOneRoom(
  browser: Browser,
  baseURL: string,
  options: { blockFriendStream?: boolean } = {},
): Promise<{ host: BrowserContext; friend: BrowserContext; hostPage: Page; friendPage: Page; streams: string[] }> {
  const host = await browser.newContext({ baseURL });
  const friend = await browser.newContext({ baseURL });
  const room = await post(host, baseURL, "/api/game/rooms", { level: "sentence" });
  await enroll(host, baseURL, "Ada");
  await post(friend, baseURL, `/api/game/rooms/${room.code}/join`);

  const hostPage = await host.newPage();
  const friendPage = await friend.newPage();
  const streams: string[] = [];
  friendPage.on("response", (response) => {
    if (response.url().endsWith("/api/game/room/events")) streams.push(`${response.status()}`);
  });
  if (options.blockFriendStream) {
    await friendPage.route("**/api/game/room/events", (route) => route.abort());
  }
  await hostPage.goto("/party");
  await friendPage.goto("/party");
  await expect(card(hostPage, "Ada")).toBeVisible();
  await expect(card(friendPage, "Ada")).toBeVisible();
  return { host, friend, hostPage, friendPage, streams };
}

test("two browsers see each other's changes within 2 seconds over the event stream", async ({
  browser,
  baseURL,
}) => {
  const { host, friend, hostPage, friendPage, streams } = await twoBrowsersInOneRoom(browser, baseURL!);
  await expect.poll(() => streams).toEqual(["200"]);

  // The friend adds a player: it appears on the host's screen.
  await enroll(friend, baseURL!, "Bob");
  await expect(card(hostPage, "Bob")).toBeVisible({ timeout: LIVE_MS });

  // The host renames their own player, through the page itself: the
  // friend's screen follows.
  await hostPage.locator("article.card", { hasText: "Ada" }).locator("[data-rename]").click();
  await hostPage.locator("form[data-rename-form] input[name=name]").fill("Countess");
  await hostPage.locator("form[data-rename-form] button[type=submit]").click();
  await expect(card(friendPage, "Countess")).toBeVisible({ timeout: LIVE_MS });
  await expect(card(friendPage, "Ada")).toHaveCount(0);

  // The friend's player goes: it leaves the host's screen too.
  const bob = (await (await friend.request.get("/api/game/room")).json()).players.find(
    (p: { name: string }) => p.name === "Bob",
  );
  const deleted = await friend.request.delete(`/api/game/room/players/${bob.id}`, {
    headers: { Origin: baseURL! },
  });
  expect(deleted.status()).toBe(204);
  await expect(card(hostPage, "Bob")).toHaveCount(0, { timeout: LIVE_MS });

  // The scores page is live as well.
  await friendPage.click('[data-tab="scores"]');
  await expect(friendPage.locator("text=No attempts yet")).toBeVisible();
  const ada = (await (await host.request.get("/api/game/room")).json()).players[0];
  await post(host, baseURL!, "/api/game/replay", { target_id: ada.id });
  await expect(friendPage.locator("td", { hasText: "Replay bot" })).toBeVisible({ timeout: LIVE_MS });

  // When the host ends the room, the friend is told, not left with a stale page.
  await post(host, baseURL!, "/api/game/room/end");
  await expect(friendPage.locator("text=This room has ended")).toBeVisible({ timeout: LIVE_MS });

  await host.close();
  await friend.close();
});

test("a browser whose event stream is blocked still sees changes, by polling", async ({
  browser,
  baseURL,
}) => {
  const { host, friend, hostPage, friendPage, streams } = await twoBrowsersInOneRoom(browser, baseURL!, {
    blockFriendStream: true,
  });

  // The host's change reaches the friend with no stream at all.
  await enroll(host, baseURL!, "Grace");
  await expect(card(friendPage, "Grace")).toBeVisible({ timeout: POLLED_MS });
  expect(streams).toEqual([]); // nothing ever answered the friend's stream

  // And the friend's change still reaches the host at stream speed.
  await enroll(friend, baseURL!, "Bob");
  await expect(card(hostPage, "Bob")).toBeVisible({ timeout: LIVE_MS });

  // A room that ends is noticed by polling too.
  await post(host, baseURL!, "/api/game/room/end");
  await expect(friendPage.locator("text=This room has ended")).toBeVisible({ timeout: POLLED_MS });

  await host.close();
  await friend.close();
});
