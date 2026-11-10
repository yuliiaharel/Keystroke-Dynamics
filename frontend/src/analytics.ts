/**
 * Visitor counting with GoatCounter (docs/plans/active/ANALYTICS_PLAN.md):
 * page views only, no cookies, and nothing about a room or a player.
 *
 * The page shell (templates/party.html) adds GoatCounter's count.js
 * only when GOATCOUNTER_SITE_CODE is set, and tells it not to count on
 * its own (`no_onload`). Every count is made here instead, with the
 * path, title, and referrer all passed explicitly. count.js loads
 * `async`, so it can run before or after this module; if it counted by
 * itself it could send a raw /r/<code> path before anything here had a
 * chance to rewrite it. This way, if this module never runs, nothing
 * is counted at all.
 */

/** Sent as the page title for every view, instead of `document.title`,
 * so a title that one day shows a room or a player can't reach
 * GoatCounter. Matches the <title> in templates/party.html. */
export const REPORTED_TITLE = "Typing Twin Party";

const ROOM_PATH = /^\/r\//;

/** The path GoatCounter is told about: no query string, and every room
 * link collapsed to one row so a room code never leaves the site. */
export function reportedPath(path: string): string {
  const withoutQuery = path.split("?")[0] || "/";
  return ROOM_PATH.test(withoutQuery) ? "/r/*" : withoutQuery;
}

/** The referrer GoatCounter is told about. A visit that arrived from
 * this site's own pages has the full previous URL as its referrer,
 * which may be a room link, and says nothing about where visitors come
 * from anyway -- so it's reported as no referrer. Other sites' URLs
 * are passed through. */
export function reportedReferrer(referrer: string, ownOrigin: string): string {
  if (!referrer) return "";
  try {
    return new URL(referrer).origin === ownOrigin ? "" : referrer;
  } catch {
    return "";
  }
}

interface GoatCounter {
  count?: (vars: { path: string; title: string; referrer: string }) => void;
}

const goatcounter = (): GoatCounter | undefined =>
  (window as unknown as { goatcounter?: GoatCounter }).goatcounter;

const snippet = (): HTMLScriptElement | null =>
  document.querySelector<HTMLScriptElement>("script[data-goatcounter]");

/** The privacy section's sentence about visit counting, shown only
 * when the page was served with the snippet, so the text matches what
 * the page does. */
export function analyticsPrivacyNote(): string {
  if (!snippet()) return "";
  return `<p class="small">This site counts page visits with GoatCounter, which sets no cookies. It sees which page was opened, the site that linked here, and the browser, screen size, and country. Room codes, names, signatures, and scores are never sent to it: every room link is counted as the same page.</p>`;
}

let stop: (() => void) | null = null;

/** Counts this page view, and one more each time the page changes its
 * own URL to a different reported path. Does nothing when the snippet
 * is absent, or when already started. Returns a function that undoes
 * it (tests use it; the page never needs to). */
export function startAnalytics(): () => void {
  const tag = snippet();
  if (!tag) return () => {};
  if (stop) return stop;

  let lastCounted: string | null = null;

  const countView = (): void => {
    const count = goatcounter()?.count;
    if (!count) return; // count.js hasn't run yet; its load event calls this again.
    // A tab opened in the background is counted once it's looked at,
    // the same rule count.js applies when it counts by itself.
    if (document.visibilityState !== "visible") return;
    const path = reportedPath(location.pathname);
    // The same view is never counted twice. Moving between two rooms
    // is /r/* both times, so it's one view, by design.
    if (path === lastCounted) return;
    // Only the first view carries the referrer; later ones are moves
    // inside the page, not new arrivals.
    const referrer =
      lastCounted === null ? reportedReferrer(document.referrer, location.origin) : "";
    lastCounted = path;
    count({ path, title: REPORTED_TITLE, referrer });
  };

  // pushState and replaceState fire no event, so the only way to see
  // the page change its own URL (opening a room from "Start a party")
  // without every caller remembering to report it is to wrap them.
  const originals = { pushState: history.pushState, replaceState: history.replaceState };
  for (const method of ["pushState", "replaceState"] as const) {
    const original = originals[method];
    history[method] = function (this: History, ...args: Parameters<History["pushState"]>): void {
      original.apply(this, args);
      countView();
    };
  }
  window.addEventListener("popstate", countView);
  document.addEventListener("visibilitychange", countView);
  tag.addEventListener("load", countView);
  countView();

  stop = (): void => {
    history.pushState = originals.pushState;
    history.replaceState = originals.replaceState;
    window.removeEventListener("popstate", countView);
    document.removeEventListener("visibilitychange", countView);
    tag.removeEventListener("load", countView);
    stop = null;
  };
  return stop;
}
