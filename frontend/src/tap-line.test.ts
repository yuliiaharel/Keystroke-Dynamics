import { describe, expect, it } from "vitest";

import { codeFor, TapLine } from "./tap-line";

/** Taps `text` cleanly, one finger at a time, 100 ms apart and held 40 ms. */
function tapAll(line: TapLine, text: string, from = 0): number {
  let t = from;
  for (const ch of text) {
    line.down(1, codeFor(ch), t, 0.1, -0.2);
    line.up(1, t + 40);
    t += 100;
  }
  return t;
}

describe("TapLine", () => {
  it("records a clean line as a down and an up per key, timed from the first landing", () => {
    const line = new TapLine("at a");
    tapAll(line, "at a", 5_000);

    expect(line.complete).toBe(true);
    expect(line.errors).toBe(0);
    expect(line.events()).toEqual([
      { code: "KeyA", action: "down", t_ms: 0, dx: 0.1, dy: -0.2 },
      { code: "KeyA", action: "up", t_ms: 40 },
      { code: "KeyT", action: "down", t_ms: 100, dx: 0.1, dy: -0.2 },
      { code: "KeyT", action: "up", t_ms: 140 },
      { code: "Space", action: "down", t_ms: 200, dx: 0.1, dy: -0.2 },
      { code: "Space", action: "up", t_ms: 240 },
      { code: "KeyA", action: "down", t_ms: 300, dx: 0.1, dy: -0.2 },
      { code: "KeyA", action: "up", t_ms: 340 },
    ]);
  });

  it("never puts a position on an up event", () => {
    const line = new TapLine("ab");
    tapAll(line, "ab");
    for (const event of line.events().filter((e) => e.action === "up")) {
      expect(event).not.toHaveProperty("dx");
      expect(event).not.toHaveProperty("dy");
    }
  });

  it("keeps overlapping fingers apart by pointer id, and sends events in time order", () => {
    const line = new TapLine("ab");
    line.down(1, "KeyA", 0, 0, 0);
    line.down(2, "KeyB", 50, 0, 0); // lands before the first finger lifts
    expect(line.complete).toBe(false);
    line.up(2, 90); // and lifts first
    expect(line.complete).toBe(false);
    line.up(1, 120);

    expect(line.complete).toBe(true);
    expect(line.events().map((e) => `${e.code} ${e.action} ${e.t_ms}`)).toEqual([
      "KeyA down 0",
      "KeyB down 50",
      "KeyB up 90",
      "KeyA up 120",
    ]);
  });

  it("isn't complete until the last finger lifts", () => {
    const line = new TapLine("a");
    line.down(1, "KeyA", 0, 0, 0);
    expect(line.index).toBe(1);
    expect(line.complete).toBe(false);
    line.up(1, 60);
    expect(line.complete).toBe(true);
  });

  it("counts a wrong key, doesn't advance, and sends nothing for it", () => {
    const line = new TapLine("ab");
    expect(line.down(1, "KeyQ", 0, 0, 0)).toBe("wrong");
    line.up(1, 30);
    expect(line.index).toBe(0);
    expect(line.errors).toBe(1);

    tapAll(line, "ab", 100);
    expect(line.complete).toBe(true);
    expect(line.events().map((e) => e.code)).toEqual(["KeyA", "KeyA", "KeyB", "KeyB"]);
  });

  it("counts a tap between keys as a wrong key", () => {
    const line = new TapLine("a");
    expect(line.down(1, null, 0, 0, 0)).toBe("wrong");
    expect(line.errors).toBe(1);
    expect(line.index).toBe(0);
  });

  it("marks only the tap right after a wrong key", () => {
    const line = new TapLine("abc");
    line.down(1, "KeyA", 0, 0, 0);
    line.up(1, 40);
    line.down(1, "KeyX", 100, 0, 0);
    line.up(1, 140);
    line.down(1, "KeyB", 200, 0, 0);
    line.up(1, 240);
    line.down(1, "KeyC", 300, 0, 0);
    line.up(1, 340);
    expect(line.taps.map((t) => t.afterError)).toEqual([false, true, false]);
  });

  it("breaks the line when a recorded tap's touch is canceled", () => {
    const line = new TapLine("ab");
    line.down(1, "KeyA", 0, 0, 0);
    line.cancel(1);
    expect(line.broken).toBe(true);
    expect(line.complete).toBe(false);
    // Nothing more is taken once it's broken.
    expect(line.down(1, "KeyB", 100, 0, 0)).toBe("ignored");
    expect(line.index).toBe(1);
  });

  it("shrugs off a canceled touch that was on a wrong key", () => {
    const line = new TapLine("a");
    line.down(1, "KeyQ", 0, 0, 0);
    line.cancel(1);
    expect(line.broken).toBe(false);
    tapAll(line, "a", 100);
    expect(line.complete).toBe(true);
  });

  it("ignores a lift or a cancel for a finger it never saw land", () => {
    const line = new TapLine("a");
    line.up(7, 10);
    line.cancel(8);
    expect(line.broken).toBe(false);
    expect(line.events()).toEqual([]);
  });

  it("ignores taps after the line is finished", () => {
    const line = new TapLine("a");
    tapAll(line, "a");
    expect(line.down(1, "KeyA", 500, 0, 0)).toBe("ignored");
    expect(line.errors).toBe(0);
    expect(line.events()).toHaveLength(2);
  });

  it("treats a second finger on a key that's still held as a wrong key", () => {
    // The scorer pairs a down with the next up for the same key, so
    // two overlapping presses of one key can't both be sent.
    const line = new TapLine("aa");
    line.down(1, "KeyA", 0, 0, 0);
    expect(line.down(2, "KeyA", 30, 0, 0)).toBe("wrong");
    line.up(2, 50);
    line.up(1, 60);
    expect(line.down(1, "KeyA", 100, 0, 0)).toBe("ok");
    line.up(1, 140);
    expect(line.complete).toBe(true);
  });

  it("never reports a lift earlier than its own landing", () => {
    const line = new TapLine("a");
    line.down(1, "KeyA", 100, 0, 0);
    line.up(1, 90);
    expect(line.events()).toEqual([
      { code: "KeyA", action: "down", t_ms: 0, dx: 0, dy: 0 },
      { code: "KeyA", action: "up", t_ms: 0 },
    ]);
  });

  it("returns fresh events each time, so a retried request sends the same line", () => {
    const line = new TapLine("ab");
    tapAll(line, "ab");
    const first = line.events();
    first[0]!.t_ms = 999;
    expect(line.events()[0]!.t_ms).toBe(0);
  });
});
