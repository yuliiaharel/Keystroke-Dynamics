import { expect, test } from "@playwright/test";
import type { Page, Request } from "@playwright/test";

import { PORT, SITE_CODE } from "./settings";

/**
 * docs/plans/active/ANALYTICS_PLAN.md's Done-when: opening a room link
 * sends /r/* to GoatCounter, and the request contains no room code
 * anywhere -- path, title, referrer, or headers.
 *
 * Nothing here reaches GoatCounter. count.js is served from a pinned
 * copy of the real script (fixtures/count.js, fetched from
 * https://gc.zgo.at/count.js), so what's tested is what that script
 * really sends; the count request it makes is recorded and answered
 * locally.
 */

const SCRIPT_HOST = "gc.zgo.at";
const COUNT_HOST = `${SITE_CODE}.goatcounter.com`;

const ROOM = "ABCD2345";
const OTHER_ROOM = "WXYZ6789";
const ANY_ROOM_CODE = new RegExp(`${ROOM}|${OTHER_ROOM}`, "i");

interface Watch {
  counts: Request[];
  hosts: Set<string>;
  cspErrors: string[];
}

async function watchGoatCounter(page: Page): Promise<Watch> {
  const watch: Watch = { counts: [], hosts: new Set(), cspErrors: [] };
  page.on("request", (request) => watch.hosts.add(new URL(request.url()).host));
  page.on("console", (message) => {
    if (/content security policy/i.test(message.text())) watch.cspErrors.push(message.text());
  });
  const countJs = `${test.info().project.testDir}/fixtures/count.js`;
  await page.route(`https://${SCRIPT_HOST}/count.js`, (route) =>
    route.fulfill({ contentType: "application/javascript", path: countJs }),
  );
  await page.route(`https://${COUNT_HOST}/**`, async (route) => {
    watch.counts.push(route.request());
    await route.fulfill({ status: 200, body: "" });
  });
  return watch;
}

/** `master` doesn't serve /r/<code> yet; the rooms branch adds it, and
 * serves the game page there. Until then, a room link that would 404
 * is answered by the server's own "/" instead, under the room link's
 * URL, so this spec tests the real route as soon as it exists and the
 * same page before.
 *
 * The probe is made by Playwright, not the browser, so it uses the
 * server's real address: only the browser knows HOST. */
async function serveRoomLinks(page: Page): Promise<void> {
  await page.route("**/r/*", async (route) => {
    const url = new URL(route.request().url());
    const probe = await page.request.get(`http://127.0.0.1:${PORT}${url.pathname}`);
    if (probe.status() !== 404) {
      await route.continue();
      return;
    }
    await route.continue({ url: `${url.origin}/` });
  });
}

/** Everything a count request carries, in one string, decoded. */
async function everythingSent(request: Request): Promise<string> {
  return [
    decodeURIComponent(request.url()),
    JSON.stringify(await request.allHeaders()),
    request.postData() ?? "",
  ].join("\n");
}

const sent = (request: Request): URLSearchParams => new URL(request.url()).searchParams;

/** Long enough for a second, unwanted count to show up. */
const SETTLE_MS = 500;

test("a room link is counted as /r/* and no room code is sent", async ({ page, baseURL }) => {
  const watch = await watchGoatCounter(page);
  await serveRoomLinks(page);

  // Arriving from another room's page is the case where the browser's
  // own referrer holds a room code.
  await page.goto(`/r/${ROOM}?utm_source=test`, { referer: `${baseURL}/r/${OTHER_ROOM}` });
  expect(await page.evaluate(() => document.referrer)).toContain(OTHER_ROOM);
  expect(new URL(page.url()).pathname).toBe(`/r/${ROOM}`);

  await expect.poll(() => watch.counts.length).toBe(1);
  await page.waitForTimeout(SETTLE_MS);
  expect(watch.counts).toHaveLength(1);

  const count = watch.counts[0]!;
  expect(sent(count).get("p")).toBe("/r/*");
  expect(sent(count).get("t")).toBe("Typing Twin Party");
  expect(sent(count).get("r")).toBeNull();
  expect(await everythingSent(count)).not.toMatch(ANY_ROOM_CODE);
  // The request's own Referer header is this site's origin, never the page's URL.
  expect((await count.allHeaders())["referer"]).toBe(`${baseURL}/`);

  expect(await page.title()).toBe("Typing Twin Party");
  expect(await page.locator('link[rel="canonical"]').count()).toBe(0);
  expect(watch.cspErrors).toEqual([]);
});

test("the home page is counted once, with the site that linked to it", async ({ page }) => {
  const watch = await watchGoatCounter(page);

  await page.goto("/?utm_source=test", { referer: "https://news.example.org/story" });

  await expect.poll(() => watch.counts.length).toBe(1);
  await page.waitForTimeout(SETTLE_MS);
  expect(watch.counts).toHaveLength(1);

  const count = watch.counts[0]!;
  expect(sent(count).get("p")).toBe("/");
  expect(sent(count).get("r")).toBe("https://news.example.org/story");
  // count.js sends the query string separately from the path, for
  // campaign links. Nothing in this app puts a room code in one.
  expect(sent(count).get("q")).toBe("?utm_source=test");

  expect([...watch.hosts].sort()).toEqual(
    [new URL(page.url()).host, SCRIPT_HOST, COUNT_HOST].sort(),
  );
  expect(watch.cspErrors).toEqual([]);
});

test("opening a room without a page load is counted once, as /r/*", async ({ page }) => {
  const watch = await watchGoatCounter(page);

  await page.goto("/");
  await expect.poll(() => watch.counts.length).toBe(1);

  await page.evaluate((room) => {
    history.pushState(null, "", `/r/${room}`);
    history.replaceState(null, "", `/r/${room}`);
  }, ROOM);

  await expect.poll(() => watch.counts.length).toBe(2);
  await page.waitForTimeout(SETTLE_MS);
  expect(watch.counts).toHaveLength(2);

  const count = watch.counts[1]!;
  expect(sent(count).get("p")).toBe("/r/*");
  expect(sent(count).get("r")).toBeNull();
  expect(await everythingSent(count)).not.toMatch(ANY_ROOM_CODE);
  expect(watch.cspErrors).toEqual([]);
});
