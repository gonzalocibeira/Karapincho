// SPDX-License-Identifier: GPL-3.0-or-later
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/health", route => route.fulfill({ json: {
    app: "karapincho", version: "0.1.0", ready: true, missing: [], token: "test",
    shutting_down: false, max_bytes: 2 * 1024 ** 3, max_minutes: 20,
  }}));
  await page.route("**/api/jobs", route => route.fulfill({ json: [] }));
  await page.route("**/api/benchmarks", route => route.fulfill({ json: {
    baseline: { hardware: "Apple M2 · 8 GB", os: "macOS", fixtures: [] },
    latest: { status: "idle" },
  }}));
  await page.goto("/");
});

test("studio and About are usable without accessibility violations", async ({ page }) => {
  await expect(page.getByRole("heading", { name: /next karaoke night/i })).toBeVisible();
  await expect(page.getByRole("button", { name: "Create song" })).toBeDisabled();
  const studioResults = await new AxeBuilder({ page }).analyze();
  expect(studioResults.violations.filter(v => ["critical", "serious"].includes(v.impact || ""))).toEqual([]);
  await page.getByRole("button", { name: "About" }).click();
  await expect(page.getByRole("heading", { name: "AI-assisted development" })).toBeVisible();
  await expect(page.getByText(/Gonzalo directed the project/)).toBeVisible();
  const aboutResults = await new AxeBuilder({ page }).analyze();
  expect(aboutResults.violations.filter(v => ["critical", "serious"].includes(v.impact || ""))).toEqual([]);
});

test("setup diagnostics name missing components", async ({ page }) => {
  await page.route("**/api/health", route => route.fulfill({ json: {
    app: "karapincho", version: "0.1.0", ready: false,
    missing: ["demucs", "torchcrepe"], token: "test", shutting_down: false,
    max_bytes: 2 * 1024 ** 3, max_minutes: 20,
  }}));
  await page.reload();
  await expect(page.getByText(/Setup is incomplete: demucs, torchcrepe/)).toBeVisible();
});

test("primary navigation works from the keyboard", async ({ page }) => {
  const about = page.getByRole("button", { name: "About" });
  for (let index = 0; index < 8; index += 1) {
    await page.keyboard.press("Tab");
    if (await about.evaluate(element => element === document.activeElement)) break;
  }
  await expect(about).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Karapincho." })).toBeVisible();
});
