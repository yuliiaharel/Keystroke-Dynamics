import { describe, expect, it } from "vitest";

import { SCORES_MEMO_TEXT, TOUCH_SCORES_MEMO_TEXT, scoresMemoHTML } from "./scores-memo";

function render(scoresEnabled: boolean, touch?: boolean): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = scoresMemoHTML(scoresEnabled, touch);
  return host;
}

describe("scoresMemoHTML", () => {
  it("shows the memo, with the exact wording, when score collection is on", () => {
    const memo = render(true).querySelector("#scores-memo");
    expect(memo).not.toBeNull();
    expect(memo!.textContent).toBe(
      "This site saves a few numbers about each result: pace, how close it came to the limit, and whether it passed. Never your name, your keystrokes, or your IP address. Your attempts in this party are grouped under a random ID that isn't linked to your name.",
    );
    expect(memo!.textContent).toBe(SCORES_MEMO_TEXT);
  });

  it("is styled as fine print", () => {
    const memo = render(true).querySelector("#scores-memo")!;
    expect(memo.tagName).toBe("P");
    expect(memo.classList.contains("small")).toBe(true);
    expect(memo.classList.contains("muted")).toBe(true);
  });

  it("is information only: no checkbox, toggle, button, or other control", () => {
    const host = render(true);
    expect(host.querySelectorAll("input, button, select, textarea, label, a, [role]")).toHaveLength(0);
  });

  it("says nothing when score collection is off, since nothing is saved", () => {
    expect(scoresMemoHTML(false)).toBe("");
  });
});

describe("scoresMemoHTML for a touch room", () => {
  it("names what a touch row stores, and that taps are never among it", () => {
    const memo = render(true, true).querySelector("#scores-memo")!;
    expect(memo.textContent).toBe(TOUCH_SCORES_MEMO_TEXT);
    expect(memo.textContent).toBe(
      "This site saves a few numbers about each result: pace, the Rhythm and Place scores, how close it came to the limit, whether it passed, whether it was tapped on the target's own phone, and a rough screen size. Never your name, your taps, where or when they landed, or your IP address. Your attempts in this room are grouped under a random ID that isn't linked to your name.",
    );
  });

  it("says nothing when score collection is off", () => {
    expect(scoresMemoHTML(false, true)).toBe("");
  });
});
