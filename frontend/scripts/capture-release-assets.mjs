// SPDX-License-Identifier: GPL-3.0-or-later
import { chromium } from "@playwright/test";
import { fileURLToPath } from "node:url";
import path from "node:path";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
let recent = [];
let songsFolder = null;

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
await page.route("**/api/jobs/feed?*", route => route.fulfill({ json: { active: [], recent, next: null } }));
await page.route("**/api/settings", route => route.fulfill({ json: { songs_folder: songsFolder } }));
await page.route("**/api/benchmarks", route => route.fulfill({ json: {
  baseline: { hardware: "Apple Silicon", os: "macOS", fixtures: [] },
  latest: { status: "idle" },
} }));

await page.goto(process.env.KARAPINCHO_PREVIEW_URL || "http://127.0.0.1:4173/", { waitUntil: "networkidle" });
await page.getByRole("heading", { name: /next karaoke night/i }).waitFor();

const here = path.dirname(fileURLToPath(import.meta.url));
const output = path.resolve(here, "../../docs/assets/screenshot-studio.png");
await page.screenshot({ path: output, fullPage: true });
console.log(output);

// Stable demonstration data keeps release screenshots independent of personal jobs.
songsFolder = "/Music/UltraStar/Songs";
recent = [{
  id: "a".repeat(32), title: "La Cucaracha", status: "completed", stage: "package",
  progress: 1, warnings: ["Review automatic lyrics before singing."], error: null,
  created: 1, elapsed_seconds: 121, started_at: null, cancel_requested: false,
  source_type: "file", processing_mode: "quality", cleaned_at: null,
  export_receipt: {}, local_available: true,
}];
await page.reload({ waitUntil: "networkidle" });
await page.getByRole("button", { name: "Add to karaoke" }).waitFor();
await page.getByText("1 quality notice", { exact: true }).click();
const readyOutput = path.resolve(here, "../../docs/assets/screenshot-ready.png");
await page.screenshot({ path: readyOutput, fullPage: true });
console.log(readyOutput);
await browser.close();
