// SPDX-License-Identifier: GPL-3.0-or-later
import { chromium } from "@playwright/test";
import { fileURLToPath } from "node:url";
import path from "node:path";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });

await page.route("**/api/health", route => route.fulfill({ json: {
  app: "karapincho",
  version: "0.1.0",
  ready: true,
  missing: [],
  token: "release-screenshot",
  shutting_down: false,
  max_bytes: 2 * 1024 ** 3,
  max_minutes: 20,
} }));
await page.route("**/api/jobs", route => route.fulfill({ json: [] }));
await page.route("**/api/benchmarks", route => route.fulfill({ json: {
  baseline: { hardware: "Apple Silicon", os: "macOS", fixtures: [] },
  latest: { status: "idle" },
} }));

await page.goto("http://127.0.0.1:4173/", { waitUntil: "networkidle" });
await page.getByRole("heading", { name: /next karaoke night/i }).waitFor();

const here = path.dirname(fileURLToPath(import.meta.url));
const output = path.resolve(here, "../../docs/assets/screenshot-studio.png");
await page.screenshot({ path: output, fullPage: true });
await browser.close();
console.log(output);
