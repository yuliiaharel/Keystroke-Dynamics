import { describe, expect, it } from "vitest";
import { KeystrokeCapture } from "./capture";

/** `isTrusted` is a spec-"unforgeable" property on a real Event --
 * jsdom makes it non-configurable even on instances, so it can't be
 * overridden via Object.defineProperty on a real KeyboardEvent. A
 * plain object with the same shape sidesteps that, standing in for a
 * real, user-generated key event. */
function trustedKeyEvent(
  type: "keydown" | "keyup",
  code: string,
  opts: { repeat?: boolean; timeStamp: number },
): KeyboardEvent {
  return {
    type,
    code,
    repeat: opts.repeat ?? false,
    isTrusted: true,
    timeStamp: opts.timeStamp,
  } as unknown as KeyboardEvent;
}

describe("KeystrokeCapture", () => {
  it("records down/up events with timestamps relative to the first event", () => {
    const capture = new KeystrokeCapture();
    capture.record(trustedKeyEvent("keydown", "KeyA", { timeStamp: 1000 }));
    capture.record(trustedKeyEvent("keyup", "KeyA", { timeStamp: 1090 }));

    expect(capture.sample()).toEqual([
      { code: "KeyA", action: "down", t_ms: 0 },
      { code: "KeyA", action: "up", t_ms: 90 },
    ]);
  });

  it("ignores repeated keydowns from a held key", () => {
    const capture = new KeystrokeCapture();
    capture.record(trustedKeyEvent("keydown", "KeyA", { timeStamp: 0 }));
    capture.record(trustedKeyEvent("keydown", "KeyA", { repeat: true, timeStamp: 50 }));
    capture.record(trustedKeyEvent("keydown", "KeyA", { repeat: true, timeStamp: 100 }));
    capture.record(trustedKeyEvent("keyup", "KeyA", { timeStamp: 150 }));

    expect(capture.count).toBe(2);
  });

  it("ignores untrusted (synthetic, non-user-generated) events", () => {
    const capture = new KeystrokeCapture();
    const untrusted = new KeyboardEvent("keydown", { code: "KeyA" });
    // isTrusted defaults to false for script-constructed events -- no
    // override here, unlike trustedKeyEvent above.
    capture.record(untrusted);

    expect(capture.count).toBe(0);
  });

  it("captures no field that could reveal the typed text", () => {
    const capture = new KeystrokeCapture();
    capture.record(trustedKeyEvent("keydown", "KeyA", { timeStamp: 0 }));

    const [event] = capture.sample();
    expect(Object.keys(event!).sort()).toEqual(["action", "code", "t_ms"]);
  });

  it("never mutates recorded data when sampled -- sending twice gives identical values", () => {
    // Regression test for the old app's bug: its submit handler
    // normalized the shared `timelog` array in place, so a second
    // call (e.g. a resend) read back values it had already converted
    // on the first call and corrupted them further.
    const capture = new KeystrokeCapture();
    capture.record(trustedKeyEvent("keydown", "KeyA", { timeStamp: 1000 }));
    capture.record(trustedKeyEvent("keyup", "KeyA", { timeStamp: 1090 }));
    capture.record(trustedKeyEvent("keydown", "KeyB", { timeStamp: 1200 }));
    capture.record(trustedKeyEvent("keyup", "KeyB", { timeStamp: 1260 }));

    const first = capture.sample();
    const second = capture.sample();

    expect(second).toEqual(first);

    // Mutating the first returned array/objects must not affect later
    // calls either -- sample() must hand back independent copies.
    first[0]!.t_ms = -999;
    first.push({ code: "Bogus", action: "down", t_ms: -1 });
    expect(capture.sample()).toEqual(second);
  });

  it("starts a fresh sample from zero after reset", () => {
    const capture = new KeystrokeCapture();
    capture.record(trustedKeyEvent("keydown", "KeyA", { timeStamp: 1000 }));
    capture.reset();
    capture.record(trustedKeyEvent("keydown", "KeyB", { timeStamp: 5000 }));

    expect(capture.sample()).toEqual([{ code: "KeyB", action: "down", t_ms: 0 }]);
  });
});
