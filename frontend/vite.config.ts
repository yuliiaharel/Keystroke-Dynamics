import { defineConfig } from "vite";

// Builds the capture module and its page-wiring entry points into
// plain ES module files under the backend's static directory -- no
// content hashing, so the Jinja templates can reference stable
// filenames (static/js/create-profile.js, static/js/authenticate.js).
export default defineConfig({
  build: {
    outDir: "../src/keystroke_dynamics/static/js",
    emptyOutDir: true,
    lib: {
      entry: {
        "create-profile": "src/pages/create-profile.ts",
        authenticate: "src/pages/authenticate.ts",
        party: "src/pages/party.ts",
      },
      formats: ["es"],
      fileName: (_format, entryName) => `${entryName}.js`,
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    // e2e/ holds Playwright specs, run separately via `npm run e2e` --
    // vitest's default glob would otherwise also pick them up.
    include: ["src/**/*.test.ts"],
  },
});
