import { describe, expect, it } from "vitest";

import { analyze, spread, timestampStep, type PointerRecord } from "./touch-capture";

function down(pointerId: number, t: number, extra: Partial<PointerRecord> = {}): PointerRecord {
  return {
    phase: "down",
    pointerId,
    pointerType: "touch",
    t,
    trusted: true,
    code: "KeyA",
    dx: 0,
    dy: 0,
    outcome: "ok",
    ...extra,
  };
}

function end(phase: "up" | "cancel", pointerId: number, t: number): PointerRecord {
  return {
    phase,
    pointerId,
    pointerType: "touch",
    t,
    trusted: true,
    code: null,
    dx: null,
    dy: null,
    outcome: null,
  };
}

describe("analyze", () => {
  it("pairs each down with its up and measures hold, gap, and offset", () => {
    const { taps, problems } = analyze([
      down(1, 100, { code: "KeyT", dx: 0.25, dy: -0.1 }),
      end("up", 1, 180),
      down(2, 400, { code: "KeyA" }),
      end("up", 2, 460),
    ]);

    expect(problems).toEqual([]);
    expect(taps).toHaveLength(2);
    expect(taps[0]).toMatchObject({
      code: "KeyT",
      holdMs: 80,
      gapMs: null,
      dx: 0.25,
      dy: -0.1,
      events: 2,
      overlapped: false,
      canceled: false,
    });
    expect(taps[1]).toMatchObject({ code: "KeyA", holdMs: 60, gapMs: 300, events: 2 });
  });

  it("keeps overlapping fingers apart by pointer id", () => {
    // Second thumb lands before the first lifts, and lifts first.
    const { taps, problems } = analyze([
      down(1, 0),
      down(2, 50),
      end("up", 2, 90),
      end("up", 1, 120),
    ]);

    expect(problems).toEqual([]);
    expect(taps.map((t) => t.holdMs)).toEqual([120, 40]);
    expect(taps.map((t) => t.overlapped)).toEqual([false, true]);
  });

  it("marks a canceled touch as an unusable hold, not a problem", () => {
    const { taps, problems } = analyze([down(1, 0), end("cancel", 1, 30)]);

    expect(problems).toEqual([]);
    expect(taps[0]).toMatchObject({ canceled: true, holdMs: null, upT: null, events: 2 });
  });

  it.each([
    {
      name: "a finger that never lifts",
      records: [down(1, 0), end("up", 1, 50), down(2, 200)],
      kinds: ["missing_up"],
    },
    {
      name: "a reused pointer id whose first lift was lost",
      records: [down(1, 0), down(1, 200), end("up", 1, 250)],
      kinds: ["missing_up"],
    },
    {
      name: "a lift with no landing",
      records: [end("up", 7, 10)],
      kinds: ["up_without_down"],
    },
    {
      name: "a cancel with no landing",
      records: [end("cancel", 7, 10)],
      kinds: ["up_without_down"],
    },
    {
      name: "events delivered out of time order",
      records: [down(1, 100), end("up", 1, 90)],
      kinds: ["time_went_backwards"],
    },
    {
      name: "an untrusted event",
      records: [down(1, 0, { trusted: false }), end("up", 1, 50)],
      kinds: ["untrusted"],
    },
  ])("reports $name", ({ records, kinds }) => {
    expect(analyze(records).problems.map((p) => p.kind)).toEqual(kinds);
  });

  it("counts one event for a tap whose lift was lost", () => {
    const { taps } = analyze([down(1, 0), down(1, 200), end("up", 1, 250)]);

    expect(taps.map((t) => t.events)).toEqual([1, 2]);
    // The stale entry is the same pointer, not a second finger.
    expect(taps[1]?.overlapped).toBe(false);
  });

  it("returns nothing for an empty log", () => {
    expect(analyze([])).toEqual({ taps: [], problems: [] });
  });
});

describe("spread", () => {
  it("is null for no values", () => {
    expect(spread([])).toBeNull();
  });

  it.each([
    { values: [5], expected: { n: 1, min: 5, median: 5, max: 5, mean: 5 } },
    { values: [3, 1, 2], expected: { n: 3, min: 1, median: 2, max: 3, mean: 2 } },
    { values: [4, 1, 3, 2], expected: { n: 4, min: 1, median: 2.5, max: 4, mean: 2.5 } },
  ])("summarizes $values", ({ values, expected }) => {
    expect(spread(values)).toEqual(expected);
  });
});

describe("timestampStep", () => {
  it("is null without two distinct timestamps", () => {
    expect(timestampStep([])).toBeNull();
    expect(timestampStep([down(1, 5), end("up", 1, 5)])).toBeNull();
  });

  it("finds the smallest non-zero step", () => {
    expect(timestampStep([down(1, 0), end("up", 1, 16), down(2, 20), end("up", 2, 120)])).toBe(4);
  });
});
