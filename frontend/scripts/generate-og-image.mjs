#!/usr/bin/env node
// Generates static/img/party-preview.png -- the Open Graph/Twitter
// preview image (PARTY_LAUNCH_PLAN.md Part 1 section 9), a 1200x630
// screenshot of og-image.html's three decorative signature rings.
//
// Uses @playwright/test's own bundled chromium (already a
// devDependency for e2e tests) instead of adding an image library
// like Pillow/cairosvg just for this one build-time asset.
//
// Run from frontend/: node scripts/generate-og-image.mjs

import { chromium } from "@playwright/test";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const htmlPath = join(__dirname, "og-image.html");
const outPath = join(__dirname, "../../src/keystroke_dynamics/static/img/party-preview.png");

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1200, height: 630 } });
await page.goto(`file://${htmlPath}`);
await page.screenshot({ path: outPath });
await browser.close();

console.log(`Wrote ${outPath}`);
