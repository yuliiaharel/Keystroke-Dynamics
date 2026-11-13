import { expect, test } from "@playwright/test";

import { card } from "./room-helpers";
import {
  ADA,
  BOB,
  PHONE,
  TOUCH_PHRASE,
  cdpFor,
  createTouchRoom,
  enrollByTapping,
  enrollTouchByApi,
  sidewaysOverflow,
  tapText,
} from "./touch-helpers";

/**
 * What a phone game puts on the wire, and whether it fits the screen
 * (docs/plans/active/MOBILE_PLAN.md Phase 2's "Done when"): the typed
 * text is never sent, nothing goes to a third party, and the page
 * never scrolls sideways at 320, 390, or 430 px.
 */

test.describe("on the wire", () => {
  test.use(PHONE);

  test("a phone game sends key codes, timing, and tap offsets -- never the text, and nothing to a third party", async ({
    page,
    baseURL,
  }) => {
    test.setTimeout(60_000);
    const ownHost = new URL(baseURL ?? "http://127.0.0.1:8000").host;
    const hosts = new Set<string>();
    const bodies: string[] = [];
    page.on("request", (request) => {
      hosts.add(new URL(request.url()).host);
      if (request.method() === "POST" || request.method() === "PATCH") {
        const data = request.postData();
        if (data !== null) bodies.push(data);
      }
    });

    await page.goto("/party");
    await page.click('[data-level="touch"]');
    const cdp = await cdpFor(page);
    await enrollByTapping(page, cdp, "Dana", ADA);
    await page.click("#to-room");
    // This target's id has none of the line's words in it, so a word
    // of the line turning up in a request could only be typed text.
    await card(page, "Sample: One-Finger Pecker").locator("[data-attack]").click();
    await tapText(page, cdp, BOB);
    await expect(page.locator("#result")).toBeVisible({ timeout: 10_000 });
    await page.click("#to-room");
    await card(page, "Sample: One-Finger Pecker").locator("[data-attack]").click();
    await page.click("#replay");
    await expect(page.locator("#result")).toBeVisible({ timeout: 15_000 });

    // No request went anywhere but this app.
    expect(hosts.size).toBeGreaterThan(0);
    for (const host of hosts) expect(host).toBe(ownHost);

    // The enrollment and the attack were both sent.
    const withEvents = bodies.filter((b) => b.includes('"action"'));
    expect(withEvents).toHaveLength(2);
    for (const body of bodies) {
      // The line itself, or any run of its words, is never in a body.
      expect(body).not.toContain(TOUCH_PHRASE);
      for (const word of TOUCH_PHRASE.split(" ").filter((w) => w.length > 2)) {
        expect(body.toLowerCase()).not.toContain(word);
      }
    }
    // An event is a key code, an action, a time, and where a finger
    // landed -- and nothing else: no character, no key label.
    const allowed = new Set(["code", "action", "t_ms", "dx", "dy"]);
    const events = withEvents.flatMap((body) => {
      const json = JSON.parse(body);
      return (json.events ?? json.training_lines.flat()) as Record<string, unknown>[];
    });
    expect(events.length).toBe(TOUCH_PHRASE.length * 2 * 5); // four kept lines and one attack
    for (const event of events) {
      for (const field of Object.keys(event)) expect(allowed.has(field), `unexpected field ${field}`).toBe(true);
      expect(String(event.code)).toMatch(/^(Key[A-Z]|Space)$/);
    }
    // The warm-up line is never sent at all.
    const enrollment = JSON.parse(withEvents.find((b) => b.includes("training_lines"))!);
    expect(enrollment.training_lines).toHaveLength(4);
    // The screen's width goes with the room, and only there.
    const withWidth = bodies.filter((b) => b.includes("viewport_width"));
    expect(withWidth).toHaveLength(1);
    expect(JSON.parse(withWidth[0]!)).toEqual({ level: "touch", device_type: "touch", viewport_width: 390 });
  });
});

for (const width of [320, 390, 430]) {
  test.describe(`at ${width} px`, () => {
    test.use({ ...PHONE, viewport: { width, height: 740 } });

    test(`no view scrolls sideways, and every key is on screen at ${width} px`, async ({ context, baseURL, page }) => {
      test.setTimeout(60_000);
      const fits = async (view: string): Promise<void> => {
        expect(await sidewaysOverflow(page), `${view} scrolls sideways at ${width} px`).toBeLessThanOrEqual(0);
      };

      await page.goto("/party");
      await expect(page.locator('[data-level="touch"]')).toBeVisible();
      await fits("intro");

      // A room with a long-named player in it already, to stress the cards.
      await createTouchRoom(context, baseURL!);
      await enrollTouchByApi(context, baseURL!, "Wilhelmina Featherstone", BOB);
      await page.goto("/party");
      await expect(card(page, "Wilhelmina Featherstone")).toBeVisible();
      await fits("room");
      await page.click("#lock-room");
      await expect(page.locator("#confirm")).toBeVisible();
      await fits("room with a question open");
      await page.click("#confirm-no");
      await card(page, "Wilhelmina Featherstone").locator("[data-rename]").click();
      await fits("room while renaming");

      await page.click("#add-player");
      await expect(page.locator("#name-form")).toBeVisible();
      await fits("name");

      // Enrollment, with the keyboard up.
      const cdp = await cdpFor(page);
      await page.fill("#player-name", "Ada");
      await page.click("#name-form button[type=submit]");
      await expect(page.locator("#keyboard")).toBeVisible();
      await fits("enrollment");
      const keys = await page.locator("#keyboard .key").all();
      expect(keys).toHaveLength(27);
      for (const key of keys) {
        const box = await key.boundingBox();
        expect(box).not.toBeNull();
        expect(box!.x).toBeGreaterThanOrEqual(0);
        expect(box!.x + box!.width).toBeLessThanOrEqual(width);
        // Usable with a thumb, even on the narrowest phone.
        expect(box!.width).toBeGreaterThanOrEqual(24);
        expect(box!.height).toBeGreaterThanOrEqual(44);
      }
      // The line being typed isn't hidden behind the keyboard.
      const phrase = (await page.locator("#phrase").boundingBox())!;
      const keyboard = (await page.locator("#keyboard").boundingBox())!;
      expect(phrase.y + phrase.height).toBeLessThanOrEqual(keyboard.y);

      for (let i = 0; i < 5; i++) await tapText(page, cdp, ADA);
      await expect(page.locator("h2", { hasText: "This is how you tap." })).toBeVisible({ timeout: 10_000 });
      await fits("reveal");
      await page.click("#to-room");

      await card(page, "Wilhelmina Featherstone").locator("[data-attack]").click();
      await expect(page.locator("#keyboard")).toBeVisible();
      await fits("attack");
      await tapText(page, cdp, ADA);
      await expect(page.locator("#result")).toBeVisible({ timeout: 10_000 });
      await fits("result");

      await page.click('[data-tab="scores"]');
      await expect(page.locator("tbody tr")).toHaveCount(1);
      await fits("scores");
      await page.click('[data-tab="how"]');
      await page.click("summary");
      await fits("how it works");
    });
  });
}
