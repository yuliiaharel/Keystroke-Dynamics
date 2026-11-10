/** Shared by playwright.analytics.config.ts and the specs here. */

/** Not a real GoatCounter site. Every request to it is intercepted
 * (see analytics.spec.ts); if one ever escaped, it would reach nothing. */
export const SITE_CODE = "e2e-test-site";

/** Its own port, so this suite and the main one (port 8000, see
 * ../README.md) can run at the same time. */
export const PORT = 8137;

/** count.js refuses to count on localhost and private addresses, which
 * is part of how production-only counting works. To test the real
 * script, the browser reaches the local server under a name that isn't
 * local (mapped in playwright.analytics.config.ts). */
export const HOST = "typingtwin.test";
