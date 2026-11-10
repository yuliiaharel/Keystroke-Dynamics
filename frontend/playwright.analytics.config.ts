import { defineConfig } from "@playwright/test";

import { HOST, PORT, SITE_CODE } from "./e2e-analytics/settings";

/**
 * The visitor-counting specs (e2e-analytics/), kept apart from
 * playwright.config.ts because they need the one thing the main suite
 * must never have: a server started with GOATCOUNTER_SITE_CODE set.
 * Unlike the main suite, this one starts its own server -- public
 * mode, no database -- on its own port.
 */
export default defineConfig({
  testDir: "./e2e-analytics",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  use: {
    baseURL: `http://${HOST}:${PORT}`,
    launchOptions: { args: [`--host-resolver-rules=MAP ${HOST} 127.0.0.1`] },
  },
  webServer: {
    command: `uv run uvicorn keystroke_dynamics.main:app --host 127.0.0.1 --port ${PORT}`,
    cwd: "..",
    url: `http://127.0.0.1:${PORT}/health`,
    reuseExistingServer: false,
    env: { DEBUG: "true", ENABLE_ACCOUNTS: "false", GOATCOUNTER_SITE_CODE: SITE_CODE },
  },
});
