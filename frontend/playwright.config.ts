import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  // All specs share one live server process, and its rate limiters
  // (api/rate_limit.py) are process-global, in-memory state keyed by
  // client IP -- every Playwright request comes from localhost, so
  // concurrent spec files exhaust the same shared budget. Run serially.
  workers: 1,
  retries: 0,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:8000",
  },
});
