import { describe, expect, it } from "vitest";

import type { NoteView } from "./game-api";
import { traitsFromNotes } from "./traits";

const note = (ch: string, start_ms: number, dur_ms: number): NoteView => ({ ch, start_ms, dur_ms });

describe("traitsFromNotes", () => {
  it("calculates pace, typical hold, and the fastest and slowest pairs", () => {
    // 10 characters over 6000 ms from first to last key down: 2 words in 0.1 min.
    const notes = [
      note("a", 0, 80),
      note("b", 300, 100),
      note("c", 400, 90),
      note("a", 1400, 80),
      note("b", 1600, 120),
      note("d", 2500, 70),
      note("e", 3600, 60),
      note("f", 4600, 110),
      note("g", 5600, 95),
      note("h", 6000, 85),
    ];

    expect(traitsFromNotes(notes)).toEqual({
      wpm: 20,
      typicalHoldMs: 90,
      fastest: { pair: "bc", gapMs: 100 },
      slowest: { pair: "de", gapMs: 1100 },
    });
  });

  it("uses the median gap for a pair that repeats", () => {
    const notes = [
      note("a", 0, 50),
      note("b", 100, 50),
      note("a", 600, 50),
      note("b", 900, 50),
      note("a", 1400, 50),
      note("b", 1600, 50),
    ];

    // "ab" gaps are 100, 300, and 200; "ba" gaps are both 500.
    expect(traitsFromNotes(notes).fastest).toEqual({ pair: "ab", gapMs: 200 });
    expect(traitsFromNotes(notes).slowest).toEqual({ pair: "ba", gapMs: 500 });
  });

  it.each([
    { name: "no notes", notes: [], typicalHoldMs: null },
    { name: "a single note", notes: [note("a", 0, 80)], typicalHoldMs: 80 },
    {
      name: "notes that all start together",
      notes: [note("a", 0, 80), note("b", 0, 80)],
      typicalHoldMs: 80,
      pair: { pair: "ab", gapMs: 0 },
    },
  ])("has no pace for $name", ({ notes, typicalHoldMs, pair }) => {
    expect(traitsFromNotes(notes)).toEqual({
      wpm: null,
      typicalHoldMs,
      fastest: pair ?? null,
      slowest: pair ?? null,
    });
  });

  it("leaves out values that aren't finite numbers", () => {
    const traits = traitsFromNotes([note("a", 0, Number.NaN), note("b", Number.NaN, Number.NaN)]);

    expect(traits).toEqual({ wpm: null, typicalHoldMs: null, fastest: null, slowest: null });
  });
});
