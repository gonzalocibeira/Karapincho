// SPDX-License-Identifier: GPL-3.0-or-later
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/health", (route) =>
    route.fulfill({
      json: {
        app: "karapincho",
        version: "0.1.0",
        ready: true,
        missing: [],
        token: "test",
        shutting_down: false,
        max_bytes: 2 * 1024 ** 3,
        max_minutes: 20,
      },
    }),
  );
  await page.route("**/api/jobs/feed?*", (route) =>
    route.fulfill({ json: { active: [], recent: [], next: null } }),
  );
  await page.route("**/api/settings", (route) =>
    route.fulfill({ json: { songs_folder: null } }),
  );
  await page.route("**/api/benchmarks", (route) =>
    route.fulfill({
      json: {
        baseline: { hardware: "Apple M2 · 8 GB", os: "macOS", fixtures: [] },
        latest: { status: "idle" },
      },
    }),
  );
  await page.goto("/");
});

test("studio and About are usable without accessibility violations", async ({
  page,
}) => {
  await expect(
    page.getByRole("heading", { name: /next karaoke night/i }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Create song" }),
  ).toBeDisabled();
  const studioResults = await new AxeBuilder({ page }).analyze();
  expect(
    studioResults.violations.filter((v) =>
      ["critical", "serious"].includes(v.impact || ""),
    ),
  ).toEqual([]);
  await page.getByRole("button", { name: "About" }).click();
  await expect(
    page.getByRole("heading", { name: "AI-assisted development" }),
  ).toBeVisible();
  await expect(page.getByText(/Gonzalo directed the project/)).toBeVisible();
  const aboutResults = await new AxeBuilder({ page }).analyze();
  expect(
    aboutResults.violations.filter((v) =>
      ["critical", "serious"].includes(v.impact || ""),
    ),
  ).toEqual([]);
});

test("setup diagnostics name missing components", async ({ page }) => {
  await page.route("**/api/health", (route) =>
    route.fulfill({
      json: {
        app: "karapincho",
        version: "0.1.0",
        ready: false,
        missing: ["demucs", "torchcrepe"],
        token: "test",
        shutting_down: false,
        max_bytes: 2 * 1024 ** 3,
        max_minutes: 20,
      },
    }),
  );
  await page.reload();
  await expect(
    page.getByText(/Setup is incomplete: demucs, torchcrepe/),
  ).toBeVisible();
});

test("primary navigation works from the keyboard", async ({ page }) => {
  const about = page.getByRole("button", { name: "About" });
  for (let index = 0; index < 8; index += 1) {
    await page.keyboard.press("Tab");
    if (await about.evaluate((element) => element === document.activeElement))
      break;
  }
  await expect(about).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", { name: "Karapincho." }),
  ).toBeVisible();
});

const completed = {
  id: "a".repeat(32),
  title: "Artist — A song",
  status: "completed",
  stage: "package",
  progress: 1,
  warnings: ["Some lyrics may need checking."],
  error: null,
  created: 1,
  elapsed_seconds: 65,
  started_at: null,
  cancel_requested: false,
  source_type: "file",
  processing_mode: "quality",
  cleaned_at: null,
  export_receipt: {},
  local_available: true,
};

test("completed job exports, handles collision, and cleans up without losing receipt", async ({
  page,
}, testInfo) => {
  let job = { ...completed };
  await page.route("**/api/jobs/feed?*", (route) =>
    route.fulfill({ json: { active: [], recent: [job], next: null } }),
  );
  await page.route("**/api/settings", (route) =>
    route.fulfill({ json: { songs_folder: "/Music/Songs" } }),
  );
  const exports: unknown[] = [];
  await page.route("**/api/jobs/*/export", (route) => {
    const body = route.request().postDataJSON();
    exports.push(body);
    if (body.collision !== "keep_both")
      return route.fulfill({
        status: 409,
        json: { detail: { code: "destination_exists", message: "Exists" } },
      });
    job = {
      ...job,
      export_receipt: { path: "/Music/Songs/Artist - A song (2)" },
    };
    return route.fulfill({ json: job });
  });
  await page.route("**/api/jobs/*/cleanup", (route) => {
    if (route.request().method() === "GET")
      return route.fulfill({ json: { bytes: 512 * 1024 ** 2 } });
    job = { ...job, cleaned_at: 2 as any, local_available: false };
    return route.fulfill({ json: job });
  });
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Bring your next song." }),
  ).toBeVisible();
  await page.screenshot({
    path: `/private/tmp/karapincho-ready-${testInfo.project.name}.png`,
    fullPage: true,
  });
  const readyResults = await new AxeBuilder({ page }).analyze();
  expect(
    readyResults.violations.filter((v) =>
      ["critical", "serious"].includes(v.impact || ""),
    ),
  ).toEqual([]);
  await page.getByRole("button", { name: "Add to karaoke" }).click();
  await expect(
    page.getByRole("group", { name: "Existing song" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Keep both", exact: true }).click();
  await expect(
    page.getByText("Added to your karaoke Songs folder."),
  ).toBeVisible();
  expect(exports).toEqual([{}, { collision: "keep_both" }]);
  await page.getByText("More options", { exact: true }).click();
  await page.getByRole("button", { name: "Clean up…", exact: true }).click();
  await expect(page.getByText(/Free 512.0 MB/)).toBeVisible();
  await page
    .getByRole("button", { name: "Clean up local files", exact: true })
    .click();
  await expect(page.getByText("Cleaned up", { exact: true })).toBeVisible();
  await expect(
    page.getByText("/Music/Songs/Artist - A song (2)", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Add to karaoke" }),
  ).toHaveCount(0);
});

test("Fast creation shows active progress and queue with usable source tabs", async ({
  page,
}, testInfo) => {
  let active: any[] = [];
  await page.route("**/api/jobs/feed?*", (route) =>
    route.fulfill({ json: { active, recent: [], next: null } }),
  );
  await page.route("**/api/jobs/url", async (route) => {
    expect(route.request().postDataJSON().processing_mode).toBe("fast");
    const job = {
      ...completed,
      status: "queued",
      processing_mode: "fast",
      progress: 0,
      stage: "acquire",
    };
    active = [
      {
        ...completed,
        id: "b".repeat(32),
        title: "Currently processing",
        status: "running",
        stage: "pitch",
        progress: 0.7,
        activity: "Detected pitch 45%",
      },
      job,
    ];
    await route.fulfill({ status: 202, json: job });
  });
  await page.reload();
  await page.getByRole("tab", { name: "YouTube link" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Upload video" })).toBeFocused();
  await expect(page.getByRole("tab", { name: "Upload video" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.keyboard.press("ArrowLeft");
  await page
    .getByLabel("YOUTUBE VIDEO URL")
    .fill("https://youtube.com/watch?v=abcdefghijk");
  await page.getByRole("radio", { name: /Fast/ }).check();
  await page.getByRole("button", { name: "Create song", exact: true }).click();
  await expect(page.getByText(/Queue position 1/)).toBeVisible();
  await expect(page.getByText("Detected pitch 45%")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "In progress 2" }),
  ).toBeVisible();
  await page.screenshot({
    path: `/private/tmp/karapincho-active-${testInfo.project.name}.png`,
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  const results = await new AxeBuilder({ page }).analyze();
  expect(
    results.violations.filter((v) =>
      ["critical", "serious"].includes(v.impact || ""),
    ),
  ).toEqual([]);
});

test("folder picker cancellation does not export or show success", async ({
  page,
}) => {
  let exportCalls = 0;
  await page.route("**/api/jobs/feed?*", (route) =>
    route.fulfill({ json: { active: [], recent: [completed], next: null } }),
  );
  await page.route("**/api/settings/choose-folder", (route) =>
    route.fulfill({ json: { songs_folder: null, cancelled: true } }),
  );
  await page.route("**/api/jobs/*/export", (route) => {
    exportCalls++;
    return route.fulfill({ json: completed });
  });
  await page.reload();
  await page.getByRole("button", { name: "Add to karaoke" }).click();
  await expect(
    page.getByRole("button", { name: "Add to karaoke" }),
  ).toBeEnabled();
  expect(exportCalls).toBe(0);
  await expect(
    page.getByText("Added to your karaoke Songs folder."),
  ).toHaveCount(0);
});

test("recent jobs load in bounded pages", async ({ page }) => {
  await page.route("**/api/jobs/feed?*", (route) => {
    const older = new URL(route.request().url()).searchParams.has("before");
    return route.fulfill({
      json: {
        active: [],
        recent: [
          {
            ...completed,
            id: older ? "b".repeat(32) : completed.id,
            title: older ? "Older song" : "Recent song",
          },
        ],
        next: older ? null : completed.id,
      },
    });
  });
  await page.reload();
  await page.getByRole("button", { name: "Load older jobs" }).click();
  await expect(
    page.getByRole("heading", { name: "Older song", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Recent song", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Load older jobs" }),
  ).toHaveCount(0);
});

test("refresh waits for completion, slows when idle, and suspends while hidden", async ({
  page,
}) => {
  await page.clock.install();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Choose folder" }),
  ).toBeEnabled();
  let calls = 0;
  let held: (() => Promise<void>) | undefined;
  await page.route("**/api/jobs/feed?*", (route) => {
    calls++;
    if (calls === 1) {
      held = () =>
        route.fulfill({ json: { active: [], recent: [], next: null } });
      return;
    }
    return route.fulfill({ json: { active: [], recent: [], next: null } });
  });
  await page.clock.runFor(15010);
  await expect.poll(() => calls).toBe(1);
  await page.clock.runFor(5000);
  expect(calls).toBe(1);
  await held!();
  await expect(
    page.getByRole("button", { name: "Choose folder" }),
  ).toBeEnabled();
  await page.clock.runFor(14000);
  expect(calls).toBe(1);
  await page.clock.runFor(1100);
  await expect.poll(() => calls).toBe(2);
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: true,
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.clock.runFor(60000);
  expect(calls).toBe(2);
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: false,
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect.poll(() => calls).toBe(3);
});
