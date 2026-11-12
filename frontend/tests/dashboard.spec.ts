import { test, expect } from "@playwright/test";
test("sign in, empty register, filters and camera denial", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill("admin@example.test");
  await page.getByLabel("Password", { exact: true }).fill("test-password-123");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(
    page.getByRole("heading", { name: "Incident register" }),
  ).toBeVisible();
  await expect(page.getByText("No incidents in this view")).toBeVisible();
  await page
    .getByLabel("type filter", { exact: true })
    .selectOption("fire_smoke");
  await expect(page.getByText("No incidents in this view")).toBeVisible();
  const user = await (await page.request.get("/api/v1/auth/me")).json();
  const locations = await (await page.request.get("/api/v1/locations")).json();
  const result = await page.request.post("/api/v1/sources", {
    headers: { "X-CSRF-Token": user.csrf_token },
    data: {
      name: "Browser acceptance camera",
      location_id: locations.items[0].id,
      kind: "browser",
    },
  });
  const source = await result.json();
  await expect(
    page
      .getByLabel("Live source")
      .locator("option", { hasText: "Browser acceptance camera" }),
  ).toBeAttached({ timeout: 10000 });
  await page.getByLabel("Live source").selectOption(source.id);
  await page.addInitScript(() =>
    Object.defineProperty(navigator.mediaDevices, "getUserMedia", {
      value: () =>
        Promise.reject(
          new DOMException("Camera permission denied", "NotAllowedError"),
        ),
    }),
  );
  await page.evaluate(() =>
    Object.defineProperty(navigator.mediaDevices, "getUserMedia", {
      value: () =>
        Promise.reject(
          new DOMException("Camera permission denied", "NotAllowedError"),
        ),
    }),
  );
  await page.getByRole("button", { name: "Start capture" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Camera permission denied",
  );
  await page.screenshot({ path: "test-results/dashboard.png", fullPage: true });
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
});

test("successful browser capture and a fresh reconnect session", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill("admin@example.test");
  await page.getByLabel("Password", { exact: true }).fill("test-password-123");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(
    page.getByRole("heading", { name: "Incident register" }),
  ).toBeVisible();
  const user = await (await page.request.get("/api/v1/auth/me")).json();
  const locations = await (await page.request.get("/api/v1/locations")).json();
  const response = await page.request.post("/api/v1/sources", {
    headers: { "X-CSRF-Token": user.csrf_token },
    data: {
      name: "Capture reconnect check",
      location_id: locations.items[0].id,
      kind: "browser",
    },
  });
  const source = await response.json();
  await expect(
    page
      .getByLabel("Live source")
      .locator("option", { hasText: "Capture reconnect check" }),
  ).toBeAttached({ timeout: 10000 });
  await page.getByLabel("Live source").selectOption(source.id);
  const state = async () => {
    const response = await page.request.get("/api/v1/sources");
    return (await response.json()).items.find((s: any) => s.id === source.id);
  };
  await page.getByRole("button", { name: "Start capture" }).click();
  await expect
    .poll(async () => (await state()).last_sequence)
    .toBeGreaterThanOrEqual(1);
  const generation = (await state()).generation;
  await page.getByRole("button", { name: "Stop capture" }).click();
  await expect.poll(async () => (await state()).active).toBe(false);
  await page.getByRole("button", { name: "Start capture" }).click();
  await expect
    .poll(async () => (await state()).generation)
    .toBe(generation + 1);
  await expect
    .poll(async () => (await state()).last_sequence)
    .toBeGreaterThanOrEqual(1);
  await page.getByRole("button", { name: "Stop capture" }).click();
});

test("review actions update the incident and show review history", async ({
  page,
}) => {
  const incident: any = {
    id: "00000000-0000-0000-0000-000000000001",
    slug: "body_state",
    subtype: "deep_bend",
    start_at: null,
    start_offset: 1,
    end_offset: 5,
    score: 0.99,
    uncertain: false,
    evaluation_only: true,
    review_status: "pending",
    evidence: [],
    reviews: [],
    predictions: [],
  };
  // Explicit browser fixture; backend review persistence is checked separately on PostgreSQL.
  await page.route("**/api/v1/incidents**", async (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON();
      incident.review_status = body.decision;
      incident.reviews.push({ decision: body.decision, notes: body.notes });
      await route.fulfill({ json: incident });
    } else {
      const detail = new URL(route.request().url()).pathname.includes(
        incident.id,
      );
      await route.fulfill({
        json: detail
          ? incident
          : { items: [incident], total: 1, page: 1, limit: 25 },
      });
    }
  });
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill("admin@example.test");
  await page.getByLabel("Password", { exact: true }).fill("test-password-123");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("button", { name: "Review", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page
    .getByLabel("Review notes")
    .fill("Reviewed explicit browser fixture");
  await page.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("1 recorded reviews");
  await page.getByRole("button", { name: "Close review" }).click();
  await expect(
    page.getByRole("table").getByText("confirmed", { exact: true }),
  ).toBeVisible();
});

test("uploaded footage uses selected models and exposes playback results", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill("admin@example.test");
  await page.getByLabel("Password", { exact: true }).fill("test-password-123");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Incident register" }),
  ).toBeVisible();
  const auth = await (await page.request.get("/api/v1/auth/me")).json();
  const locations = await (await page.request.get("/api/v1/locations")).json();
  const response = await page.request.post("/api/v1/sources", {
    headers: { "X-CSRF-Token": auth.csrf_token },
    data: {
      name: "Video workspace camera",
      location_id: locations.items[0].id,
      kind: "upload",
    },
  });
  const source = await response.json();
  await expect(
    page
      .getByLabel("Upload source")
      .locator("option", { hasText: "Video workspace camera" }),
  ).toBeAttached({ timeout: 10000 });
  await page.getByLabel("Upload source").selectOption(source.id);
  await page
    .getByRole("group", { name: "Models to test" })
    .getByRole("checkbox", { name: "Fire & smoke", exact: true })
    .check();
  await page
    .getByRole("checkbox", { name: "Allow evaluation-only models" })
    .check();
  await page
    .getByLabel("Video recording", { exact: true })
    .setInputFiles(
      "../tests/fixtures/datasets/phone_usage/videos/test/evaluation_0.mp4",
    );
  await page
    .getByRole("button", { name: "Queue recording", exact: true })
    .click();
  await expect(page.getByLabel("Processing progress")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "completed", exact: true }),
  ).toBeVisible({ timeout: 30000 });
  await expect(
    page.getByRole("heading", { name: "Alert timeline" }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Evaluation testing: these results are not qualified for production.",
    ),
  ).toBeVisible();
  await expect(page.locator(".video-stage video")).toHaveAttribute(
    "src",
    /\/api\/v1\/jobs\/.+\/video/,
  );
  const jobs = await (await page.request.get("/api/v1/jobs")).json();
  const details = await (
    await page.request.get("/api/v1/jobs/" + jobs.items[0].id)
  ).json();
  expect(Object.keys(details.snapshot.cards)).toEqual(["fire_smoke"]);
  await page.reload();
  await expect(page.locator(".job-history button").first()).toBeVisible();
});
