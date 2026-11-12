# Typing Twin: Visitor Analytics Plan

Repository: `yuliiaharel/Keystroke-Dynamics`

## Goal

See how many people visit typingtwin.com, where they come from, and what device they use, without cookies, a consent banner, or any room data leaving the site.

This must be live before the public announcement, because launch-day visits can't be recovered afterward.

## Before running this

I do these myself. Claude Code can't.

1. Create a free GoatCounter account at `https://www.goatcounter.com/signup` and pick a site code, such as `typingtwin`.
2. In GoatCounter's settings, leave "collect referrer", "browser and OS", "screen size", and "country" on. Turn off region-level location and session tracking beyond the default.
3. Give Claude Code the site code when starting the session.

## Rules for Claude Code

1. Follow `CLAUDE.md`.
2. Work on a new `analytics` branch from the latest `master`, separate from `rooms`. Push the branch. Never push to or merge into `master`, because that deploys.
3. Do only what this plan asks.
4. If the code contradicts this plan, stop and ask me.

## Decisions already made

| Area | Decision |
|---|---|
| Provider | GoatCounter, hosted. Cookieless, so no consent banner |
| What is counted | Page views only. No custom events, no names, no scores, no timings |
| Room links | Every `/r/<code>` path is reported as `/r/*`. A room code never reaches GoatCounter |
| Query strings | Dropped from the reported path |
| Where it runs | Production only. Never on localhost, in tests, or in Playwright |
| Configuration | The site code comes from a build-time or environment setting. An empty value turns analytics off |

## Work

### 1. Snippet

Add the GoatCounter script to the page shell, loaded `async`, only when the site code is set:

```html
<script>
  window.goatcounter = {
    path: function (p) {
      p = p.split('?')[0];
      return /^\/r\//.test(p) ? '/r/*' : p;
    },
  };
</script>
<script data-goatcounter="https://SITE_CODE.goatcounter.com/count"
        async src="https://gc.zgo.at/count.js"></script>
```

Put the path function in a small tested module instead of inline, if that fits the frontend build better.

### 2. Navigation inside the app

GoatCounter counts once per page load. If the frontend changes the URL without a full load, for example when "Start a party" opens a room, count each such navigation once with `window.goatcounter.count({ path: ... })`, using the same path function. Don't count the same view twice.

### 3. Page details that could leak

- Check that the page title sent to GoatCounter is the generic one, and never includes a room code or player name.
- Check that room pages have no `<link rel="canonical">` containing the code, because GoatCounter prefers the canonical URL over the path.
- Set `Referrer-Policy: strict-origin-when-cross-origin` if it isn't already set, so a room code isn't sent to other sites as a referrer.

### 4. Security headers

If the app sends a Content-Security-Policy, allow only what the snippet needs: the script from `https://gc.zgo.at`, and the count request to `https://SITE_CODE.goatcounter.com`. Don't loosen anything else.

### 5. Privacy text

Add one or two sentences to the privacy text: the site counts page visits with GoatCounter, without cookies, and never sends room codes, names, signatures, or scores.

## Done when

- Unit tests cover the path function: `/` stays `/`, `/r/ABCD2345` and `/r/abcd-2345` become `/r/*`, and query strings are dropped.
- A test confirms the script tag is absent when the site code is empty.
- A Playwright test, with the count request intercepted, confirms that opening a room link sends `/r/*` and that the request contains no room code anywhere, including title and referrer.
- The existing Playwright tests make no request to GoatCounter.
- Frontend typecheck, tests, and build pass. `ruff`, `mypy`, and `pytest` pass if any backend file changed.

## After I merge

- [ ] Open typingtwin.com in a private window, and see the visit in the GoatCounter dashboard within a minute
- [ ] Open a room link, and see `/r/*` in the dashboard, never a code
- [ ] No Content-Security-Policy errors in the browser console
- [ ] In GoatCounter, add my own IP to the ignore list, so my testing doesn't count

## Prompt

```text
Read ANALYTICS_PLAN.md and carry it out. The GoatCounter site code is <code>. Run the Done when checks, tell me which files load the snippet and how the site code is configured, push the analytics branch, and stop.
```
