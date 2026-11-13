import { afterEach, describe, expect, it, vi } from "vitest";

import { canChooseKeyboard, chooseOnScreenKeyboard, deviceType, isPhone, mustTurnUpright } from "./device";

/** Stands in for the browser: which media queries match, and how
 * many touch points the screen has. */
function browser(matching: string[], maxTouchPoints: number): void {
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: matching.includes(query) }));
  vi.stubGlobal("navigator", { maxTouchPoints });
}

const COARSE = "(pointer: coarse)";
const LANDSCAPE = "(orientation: landscape)";

afterEach(() => {
  chooseOnScreenKeyboard(false);
  vi.unstubAllGlobals();
});

describe("deviceType", () => {
  it("is touch on a phone, whose main pointer is a finger", () => {
    browser([COARSE], 5);
    expect(isPhone()).toBe(true);
    expect(deviceType()).toBe("touch");
  });

  it("is keyboard on a computer", () => {
    browser([], 0);
    expect(deviceType()).toBe("keyboard");
  });

  it("is keyboard on a touchscreen laptop, until its user asks for the on-screen keyboard", () => {
    browser([], 10);
    expect(deviceType()).toBe("keyboard");
    chooseOnScreenKeyboard(true);
    expect(deviceType()).toBe("touch");
    chooseOnScreenKeyboard(false);
    expect(deviceType()).toBe("keyboard");
  });

  it("is keyboard where the browser can't say", () => {
    vi.stubGlobal("matchMedia", undefined);
    expect(deviceType()).toBe("keyboard");
  });
});

describe("canChooseKeyboard", () => {
  it("is only for a computer with a touchscreen", () => {
    browser([], 10);
    expect(canChooseKeyboard()).toBe(true);
    browser([], 0);
    expect(canChooseKeyboard()).toBe(false);
    // A phone has no physical keyboard to choose.
    browser([COARSE], 5);
    expect(canChooseKeyboard()).toBe(false);
  });
});

describe("mustTurnUpright", () => {
  it("asks a phone on its side to turn", () => {
    browser([COARSE, LANDSCAPE], 5);
    expect(mustTurnUpright()).toBe(true);
    browser([COARSE], 5);
    expect(mustTurnUpright()).toBe(false);
  });

  it("leaves a laptop using the on-screen keyboard alone, though it's always wide", () => {
    browser([LANDSCAPE], 10);
    chooseOnScreenKeyboard(true);
    expect(mustTurnUpright()).toBe(false);
  });
});
