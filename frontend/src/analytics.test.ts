import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  REPORTED_TITLE,
  analyticsPrivacyNote,
  reportedPath,
  reportedReferrer,
  startAnalytics,
} from "./analytics";

describe("reportedPath", () => {
  it.each([
    ["/", "/"],
    ["/party", "/party"],
    ["/r/ABCD2345", "/r/*"],
    ["/r/abcd-2345", "/r/*"],
    ["/r/ABCD2345/", "/r/*"],
    ["/r/ABCD2345/anything/after", "/r/*"],
    ["/r/", "/r/*"],
    // Not a room link, so it's left alone.
    ["/rooms", "/rooms"],
    ["/?utm_source=x", "/"],
    ["/party?a=1&b=2", "/party"],
    ["/r/ABCD2345?name=Dana", "/r/*"],
    ["/?next=/r/ABCD2345", "/"],
    ["", "/"],
  ])("reports %s as %s", (path, expected) => {
    expect(reportedPath(path)).toBe(expected);
  });
});

describe("reportedReferrer", () => {
  const own = "https://typingtwin.com";

  it.each([
    ["", ""],
    ["https://news.example.org/item?id=1", "https://news.example.org/item?id=1"],
    // This site's own pages, a room link above all, are never reported.
    ["https://typingtwin.com/r/ABCD2345", ""],
    ["https://typingtwin.com/", ""],
    // A host that merely starts with this one's name is still another site.
    ["https://typingtwin.com.example.org/", "https://typingtwin.com.example.org/"],
    ["not a url", ""],
  ])("reports %s as %s", (referrer, expected) => {
    expect(reportedReferrer(referrer, own)).toBe(expected);
  });
});

describe("startAnalytics", () => {
  let count: ReturnType<typeof vi.fn>;
  let stop: () => void = () => {};
  const win = window as unknown as { goatcounter?: { count?: unknown } };

  const addSnippet = (): HTMLScriptElement => {
    const tag = document.createElement("script");
    tag.dataset.goatcounter = "https://example.goatcounter.com/count";
    document.head.appendChild(tag);
    return tag;
  };
  const setVisibility = (state: string): void => {
    Object.defineProperty(document, "visibilityState", { value: state, configurable: true });
  };
  const setReferrer = (referrer: string): void => {
    Object.defineProperty(document, "referrer", { value: referrer, configurable: true });
  };
  const countedPaths = (): string[] =>
    count.mock.calls.map(([vars]) => (vars as { path: string }).path);

  beforeEach(() => {
    count = vi.fn();
    win.goatcounter = { count };
    history.replaceState(null, "", "/");
    document.title = REPORTED_TITLE;
    setVisibility("visible");
    setReferrer("");
  });

  afterEach(() => {
    stop();
    stop = () => {};
    document.querySelectorAll("script[data-goatcounter]").forEach((tag) => tag.remove());
    delete win.goatcounter;
  });

  it("does nothing when the page has no snippet", () => {
    stop = startAnalytics();
    history.pushState(null, "", "/r/ABCD2345");
    expect(count).not.toHaveBeenCalled();
    expect(analyticsPrivacyNote()).toBe("");
  });

  it("counts the page once, even if started twice", () => {
    addSnippet();
    stop = startAnalytics();
    startAnalytics();
    expect(count).toHaveBeenCalledTimes(1);
    expect(count).toHaveBeenCalledWith({ path: "/", title: REPORTED_TITLE, referrer: "" });
  });

  it("reports a room link as /r/* and never passes a code", () => {
    addSnippet();
    document.title = "Room ABCD2345";
    setReferrer(`${location.origin}/r/WXYZ6789`);
    history.replaceState(null, "", "/r/ABCD2345?from=WXYZ6789");
    stop = startAnalytics();
    expect(count).toHaveBeenCalledTimes(1);
    expect(count).toHaveBeenCalledWith({ path: "/r/*", title: REPORTED_TITLE, referrer: "" });
    expect(JSON.stringify(count.mock.calls)).not.toMatch(/ABCD2345|WXYZ6789/i);
  });

  it("passes another site's referrer on the first view only", () => {
    addSnippet();
    setReferrer("https://news.example.org/item");
    stop = startAnalytics();
    history.pushState(null, "", "/r/ABCD2345");
    expect(count.mock.calls).toEqual([
      [{ path: "/", title: REPORTED_TITLE, referrer: "https://news.example.org/item" }],
      [{ path: "/r/*", title: REPORTED_TITLE, referrer: "" }],
    ]);
  });

  it("counts each in-page navigation once, and not a move to the same reported path", () => {
    addSnippet();
    stop = startAnalytics();
    history.pushState(null, "", "/r/ABCD2345");
    history.replaceState(null, "", "/r/ABCD2345?x=1");
    history.pushState(null, "", "/r/WXYZ6789");
    history.pushState(null, "", "/");
    expect(countedPaths()).toEqual(["/", "/r/*", "/"]);
  });

  it("counts a back or forward move", () => {
    addSnippet();
    stop = startAnalytics();
    // The unwrapped method changes the URL without counting, which is
    // what the browser itself does on back/forward before popstate.
    History.prototype.pushState.call(history, null, "", "/r/ABCD2345");
    expect(countedPaths()).toEqual(["/"]);
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(countedPaths()).toEqual(["/", "/r/*"]);
  });

  it("waits for count.js when it loads after this module", () => {
    const tag = addSnippet();
    delete win.goatcounter;
    stop = startAnalytics();
    expect(count).not.toHaveBeenCalled();
    win.goatcounter = { count };
    tag.dispatchEvent(new Event("load"));
    expect(count).toHaveBeenCalledTimes(1);
  });

  it("counts a background tab only once it becomes visible", () => {
    addSnippet();
    setVisibility("hidden");
    stop = startAnalytics();
    expect(count).not.toHaveBeenCalled();
    setVisibility("visible");
    document.dispatchEvent(new Event("visibilitychange"));
    document.dispatchEvent(new Event("visibilitychange"));
    expect(count).toHaveBeenCalledTimes(1);
  });

  it("shows the privacy note when the snippet is present", () => {
    addSnippet();
    const note = analyticsPrivacyNote();
    expect(note).toContain("GoatCounter");
    expect(note).toContain("no cookies");
  });

  it("puts history back when stopped", () => {
    addSnippet();
    const before = history.pushState;
    stop = startAnalytics();
    expect(history.pushState).not.toBe(before);
    stop();
    expect(history.pushState).toBe(before);
    history.pushState(null, "", "/r/ABCD2345");
    expect(count).toHaveBeenCalledTimes(1);
  });
});
