import { describe, expect, it } from "vitest";

import type { NoteView, TapPointView } from "./game-api";
import type { Tap } from "./tap-line";
import { giveawayHTML, giveaways, leans, spotsFromTapMap, spotsFromTaps, tapMapSVG } from "./tap-map";

const PHRASE = "at a";

const tap = (ch: string, down: number, hold: number, dx: number, dy: number, afterError = false): Tap => ({
  ch,
  code: ch === " " ? "Space" : `Key${ch.toUpperCase()}`,
  down,
  up: down + hold,
  dx,
  dy,
  afterError,
});

/** A target who taps every 200 ms and holds for 80. */
const NOTES: NoteView[] = [...PHRASE].map((ch, i) => ({ ch, start_ms: i * 200, dur_ms: 80 }));
const MAP: TapPointView[] = [
  { code: "KeyA", x: 0.1, x_spread: 0.05, y: -0.1, y_spread: 0.2 },
  { code: "KeyT", x: 0, x_spread: 0.1, y: 0, y_spread: 0.1 },
  { code: "Space", x: null, x_spread: null, y: 0.2, y_spread: 0.1 },
];

const render = (svg: string): SVGElement => {
  const host = document.createElement("div");
  host.innerHTML = svg;
  return host.querySelector("svg")!;
};

describe("spotsFromTaps", () => {
  it("averages a key tapped more than once, as the scorer does", () => {
    const spots = spotsFromTaps([tap("a", 0, 80, 0.2, 0.0), tap("t", 200, 80, -0.1, 0.3), tap("a", 400, 80, 0.4, 0.2)]);
    expect(spots.get("KeyA")!.x).toBeCloseTo(0.3);
    expect(spots.get("KeyA")!.y).toBeCloseTo(0.1);
    expect(spots.get("KeyT")).toEqual({ x: -0.1, y: 0.3 });
  });

  it("has no side-to-side position for the space bar", () => {
    expect(spotsFromTaps([tap(" ", 0, 80, 1.5, 0.1)]).get("Space")).toEqual({ x: null, y: 0.1 });
  });
});

describe("spotsFromTapMap", () => {
  it("lands a replay on the target's own averages", () => {
    expect(spotsFromTapMap(MAP).get("KeyA")).toEqual({ x: 0.1, y: -0.1 });
    expect(spotsFromTapMap(MAP).get("Space")).toEqual({ x: null, y: 0.2 });
  });
});

describe("tapMapSVG", () => {
  it("draws a dot and a shaded area for each key of the line, and none for the rest", () => {
    const svg = render(tapMapSVG(MAP, 2, PHRASE, null));
    expect(svg.querySelectorAll("circle")).toHaveLength(3); // a, t, space
    expect(svg.querySelectorAll("ellipse")).toHaveLength(3);
    expect(svg.querySelectorAll(".m-key")).toHaveLength(3);
    expect(svg.querySelectorAll(".m-off")).toHaveLength(27 - 3);
    expect(svg.querySelector("circle")!.getAttribute("fill")).toBe("var(--p2)");
    expect(svg.querySelectorAll(".m-attempt")).toHaveLength(0);
  });

  it("puts the dot where the average tap is, in key widths from the center", () => {
    const svg = render(tapMapSVG([{ code: "KeyA", x: 0.5, x_spread: 0.1, y: -0.5, y_spread: 0.1 }], 0, "a", null));
    const cross = svg.querySelector(".m-center")!.getAttribute("d")!;
    // "M<cx-3> <cy> h6 ...": the key's center.
    const [, left, cy] = /^M([\d.]+) ([\d.]+) /.exec(cross)!;
    const dot = svg.querySelector("circle")!;
    expect(Number(dot.getAttribute("cx"))).toBeCloseTo(Number(left) + 3 + 0.5 * 38, 1);
    expect(Number(dot.getAttribute("cy"))).toBeCloseTo(Number(cy) - 0.5 * 38, 1);
  });

  it("adds a square per key for an attempt's taps", () => {
    const attempt = spotsFromTaps([tap("a", 0, 80, 0.3, 0.3), tap("t", 200, 80, 0, 0)]);
    const svg = render(tapMapSVG(MAP, 0, PHRASE, attempt));
    expect(svg.querySelectorAll(".m-attempt")).toHaveLength(2);
    expect(svg.getAttribute("aria-label")).toContain("where this attempt landed");
  });

  it("still draws the keyboard for a player with no tap map", () => {
    const svg = render(tapMapSVG([], 0, PHRASE, null));
    expect(svg.querySelectorAll("circle")).toHaveLength(0);
    expect(svg.querySelectorAll(".m-key")).toHaveLength(3);
  });

  it("escapes the player's name in its label", () => {
    const svg = render(tapMapSVG(MAP, 0, PHRASE, null, `<b>"Ada"</b>`));
    expect(svg.querySelector("b")).toBeNull();
    expect(svg.getAttribute("aria-label")).toContain(`<b>"Ada"</b>`);
  });
});

describe("leans", () => {
  it("averages the per-key positions, leaving the space bar out of the side lean", () => {
    const lean = leans(MAP);
    expect(lean.side).toBeCloseTo(0.05); // (0.1 + 0) / 2
    expect(lean.height).toBeCloseTo((-0.1 + 0 + 0.2) / 3);
  });

  it("is null with no tap map, never zero", () => {
    expect(leans([])).toEqual({ side: null, height: null });
  });
});

describe("giveaways", () => {
  /** The target's own typical line: nothing to give away. */
  const typical = (): Tap[] => [tap("a", 0, 80, 0.1, -0.1), tap("t", 200, 80, 0, 0), tap(" ", 400, 80, 0, 0.2), tap("a", 600, 80, 0.1, -0.1)];

  it("finds nothing in a line that matches the target's typical one", () => {
    expect(giveaways(typical(), NOTES, MAP)).toEqual([]);
  });

  it("names a key held too long", () => {
    const taps = typical();
    taps[1] = tap("t", 200, 200, 0, 0);
    const [first] = giveaways(taps, NOTES, MAP);
    expect(first).toMatchObject({ kind: "hold", keys: "t", diff: 120 });
    expect(giveawayHTML(first!)).toBe("Held <b>t</b> 120 ms longer");
  });

  it("names a gap that was too short, by its two keys", () => {
    const taps = [tap("a", 0, 80, 0.1, -0.1), tap("t", 60, 80, 0, 0), tap(" ", 260, 80, 0, 0.2), tap("a", 460, 80, 0.1, -0.1)];
    const [first] = giveaways(taps, NOTES, MAP);
    expect(first).toMatchObject({ kind: "gap", keys: "at", diff: -140 });
    expect(giveawayHTML(first!)).toBe("The gap from <b>a</b> to <b>t</b> was 140 ms shorter");
  });

  it("names a tap that landed off to the side, or too low", () => {
    const side = typical();
    side[1] = tap("t", 200, 80, 0.4, 0);
    expect(giveawayHTML(giveaways(side, NOTES, MAP)[0]!)).toBe("Tapped <b>t</b> 40% of a key further right");

    const low = typical();
    low[2] = tap(" ", 400, 80, 0, 0.5);
    expect(giveawayHTML(giveaways(low, NOTES, MAP)[0]!)).toBe("Tapped <b>space</b> 30% of a key lower");
  });

  it("never judges the space bar's side-to-side position", () => {
    const taps = typical();
    taps[2] = tap(" ", 400, 80, 3, 0.2);
    expect(giveaways(taps, NOTES, MAP)).toEqual([]);
  });

  it("leaves out the gap after a wrong key, and a gap that was a pause", () => {
    const afterError = typical();
    afterError[1] = tap("t", 900, 80, 0, 0, true);
    expect(giveaways(afterError, NOTES, MAP).some((g) => g.kind === "gap" && g.keys === "at")).toBe(false);

    const pause = [tap("a", 0, 80, 0.1, -0.1), tap("t", 2_500, 80, 0, 0)];
    expect(giveaways(pause, NOTES, MAP).some((g) => g.kind === "gap")).toBe(false);
  });

  it("ranks by size against the usual variation, biggest first, and keeps the top few", () => {
    const taps = [tap("a", 0, 300, 0.1, -0.1), tap("t", 200, 120, 0.5, 0.6), tap(" ", 400, 80, 0, 0.2), tap("a", 600, 300, 0.1, -0.1)];
    const found = giveaways(taps, NOTES, MAP);
    expect(found).toHaveLength(3);
    expect(found.map((g) => g.size)).toEqual([...found.map((g) => g.size)].sort((a, b) => b - a));
    expect(giveaways(taps, NOTES, MAP, 1)).toHaveLength(1);
  });

  it("measures a position against the scorer's floor, not a spread of zero", () => {
    const map: TapPointView[] = [{ code: "KeyA", x: 0, x_spread: 0, y: 0, y_spread: 0 }];
    const [first] = giveaways([tap("a", 0, 80, 0.16, 0)], [{ ch: "a", start_ms: 0, dur_ms: 80 }], map);
    expect(first!.size).toBeCloseTo(2); // 0.16 / 0.08
  });

  it("skips anything it can't line up with the target's line", () => {
    // A line that isn't the target's phrase at all.
    expect(giveaways([tap("z", 0, 80, 0, 0)], NOTES, MAP)).toEqual([]);
  });
});
