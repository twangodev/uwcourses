import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

const coverage = JSON.parse(readFileSync(".site/import/campus.json", "utf8"));
const date = coverage.from;
const now = new Date(`${date}T15:00:00Z`);
async function mockCampus(page: import("@playwright/test").Page) {
  await page.route(`**/campus/**${date}.json`, (route) =>
    route.fulfill({
      json: {
        date,
        buildings: [
          {
            sessions: [
              {
                startsAt: +now - 60000,
                endsAt: +now + 3600000,
                room: "100",
                enrolled: 30,
                courses: [{ code: "COMPSCI 300", section: "LEC 001" }],
                instructors: ["Example Instructor"],
              },
            ],
            name: "Science",
            latitude: 43.075,
            longitude: -89.408,
            events: [
              [+now - 60000, 1, 0],
              [+now + 3600000, 0, 1],
            ],
          },
        ],
        events: [
          [+now - 60000, 100, 0],
          [+now + 600000, 20, 0],
          [+now + 3600000, 0, 120],
        ],
        enrollmentEvents: [
          [+now - 60000, 20372, 0, 95, 0],
          [+now + 3600000, 0, 20372, 0, 95],
        ],
      },
    }),
  );
  await page.route("**/api/weather", (route) =>
    route.fulfill({
      json: {
        available: true,
        temperatureF: 72,
        description: "Fair",
        observedAt: "2026-09-10T14:45:00Z",
        source: "National Weather Service · KMSN",
        sourceUrl: "https://www.weather.gov/wrh/timeseries?site=KMSN",
      },
    }),
  );
}

test("campus facts show estimated enrollment over a local map, with accessible context", async ({
  page,
}) => {
  await page.clock.setFixedTime(now);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockCampus(page);
  await page.goto("/");
  const scene = page.locator(".campus-scene");
  await expect(scene).toContainText("students scheduled in class right now");
  await expect(
    scene
      .locator(".fact-value")
      .getByRole("img", { name: "20,350", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".campus-map")).toBeVisible();
  await expect(
    page.locator('.building-heat[data-building="Science"]'),
  ).toHaveAttribute("data-meetings", "1");
  expect(
    Number(
      await page
        .locator('.building-heat[data-building="Science"]')
        .getAttribute("fill-opacity"),
    ),
  ).toBeCloseTo(
    0.08 + Math.sqrt(1 / Math.max(1, coverage.maxConcurrentClasses)) * 0.3,
  );
  await expect(page.locator(".heat-legend")).toHaveAttribute(
    "aria-label",
    `Square-root color scale: 0 to ${coverage.maxConcurrentClasses} concurrent classes per building. Reference fixed across the published schedule.`,
  );

  await scene.getByRole("button", { name: "About this campus fact" }).click();
  await expect(page.getByRole("tooltip")).toContainText("not live attendance");
  await page.keyboard.press("Escape");
  await expect(scene.locator(".live-students")).toContainText(
    "students scheduled now",
  );
  await expect(
    scene.getByRole("button", { name: "Next campus fact" }),
  ).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    )
    .toBe(true);
  await expect(
    page.getByRole("combobox", { name: "Search courses or topics" }),
  ).toBeVisible();
});

test("campus facts rotate with NumberFlow and pause on hover", async ({
  page,
}) => {
  await page.clock.install({ time: now });
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await mockCampus(page);
  await page.goto("/");
  const scene = page.locator(".campus-scene");
  await expect(scene).toContainText("students scheduled in class right now");
  const number = await scene.locator(".fact-value").elementHandle();
  await page.clock.fastForward(8500);
  await expect(scene).toContainText("classes in session right now");
  expect(
    await number!.evaluate(
      (el) => el === document.querySelector(".fact-value"),
    ),
  ).toBe(true);
  await scene.locator(".fact-value").hover();
  await page.clock.fastForward(17000);
  await expect(scene).toContainText("classes in session right now");
  await page.mouse.move(0, 0);
  for (let i = 0; i < 3; i++) await page.clock.fastForward(8100);
  await expect(scene.locator(".fact-value .period")).toHaveText("AM");
  await expect(scene.locator(".fact-value .colon")).toHaveText(":");
  await expect(scene.locator(".live-students")).toBeVisible();
});

test("out-of-coverage dates use solar facts without inventing attendance", async ({
  page,
}) => {
  await page.clock.install({ time: new Date("2000-01-01T06:00:00Z") });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.route("**/api/weather", (route) => route.abort());
  await page.goto("/");
  const scene = page.locator(".campus-scene");
  await expect(scene).toContainText("sunrise over Madison");
  await expect(scene).not.toContainText("students");
  await expect(scene).not.toContainText("class meetings");
  await page.clock.fastForward(17000);
  await expect(scene).toContainText("sunrise over Madison");
});

test("building outlines open useful class details by hover, keyboard and tap", async ({
  page,
}) => {
  await page.clock.setFixedTime(now);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockCampus(page);
  await page.goto("/");
  const outline = page.getByRole("button", {
    name: "Science: 1 classes in session",
    exact: true,
  });
  await outline.hover();
  const panel = page.getByRole("tooltip", { name: "Science details" });
  await expect(panel).toBeVisible();
  await expect(panel).toContainText("COMPSCI 300");
  await expect(panel).toContainText("Room 100");
  await expect(panel.getByRole("link")).toHaveCount(0);
  // Pointer coordinates anchor the panel; its measured size keeps it on screen.
  await outline.dispatchEvent("pointermove", {
    pointerType: "mouse",
    clientX: 300,
    clientY: 120,
  });
  await expect.poll(async () => (await panel.boundingBox())?.x).toBe(316);
  await outline.dispatchEvent("pointermove", {
    pointerType: "mouse",
    clientX: 340,
    clientY: 140,
  });
  await expect.poll(async () => (await panel.boundingBox())?.x).toBe(356);
  const viewport = page.viewportSize()!;
  await outline.dispatchEvent("pointermove", {
    pointerType: "mouse",
    clientX: viewport.width - 4,
    clientY: viewport.height - 4,
  });
  await expect
    .poll(async () => {
      const box = (await panel.boundingBox())!;
      return (
        box.x >= 12 &&
        box.y >= 12 &&
        box.x + box.width <= viewport.width - 12 &&
        box.y + box.height <= viewport.height - 12
      );
    })
    .toBe(true);
  await page.mouse.move(0, 0);
  await expect(panel).not.toBeVisible();
  await outline.focus();
  await expect(panel).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(panel).not.toBeVisible();
  await page.keyboard.press("Enter");
  const details = page.getByRole("region", { name: "Science details" });
  await expect(details).toBeVisible();
  await expect(
    details.getByRole("link", { name: "COMPSCI 300" }),
  ).toHaveAttribute("href", "/courses/COMPSCI_300");
  await expect(details).toContainText("Example Instructor");
  await details.getByRole("button", { name: "Close building details" }).click();
  await expect(details).not.toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await outline.click();
  await expect(details).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    )
    .toBe(true);
});

test("landing course-search content and SEO are present in server HTML", async ({
  request,
}) => {
  const response = await request.get("/");
  expect(response.status()).toBe(200);
  const html = await response.text();
  expect(html).toContain("Search UW–Madison courses</h1>");
  expect(html).toContain(
    "Compare grades, prerequisites, and professor reviews.",
  );
  expect(html).toContain(
    "Search UW–Madison Courses, Grades &amp; Reviews | uwcourses</title>",
  );
  expect(html).toContain('rel="canonical" href="https://uwcourses.com/"');
  expect(html).toContain('content="index,follow,max-image-preview:large"');
  expect(html).toContain('"@type":"WebSite"');
  expect(html).toContain('href="/departments"');
});

test("course-search intro fades into the first statistic without moving search", async ({
  page,
}) => {
  await page.clock.install({ time: now });
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await mockCampus(page);
  await page.goto("/");
  await page.evaluate(() => document.fonts.ready);
  await expect(page.locator(".intro .welcome")).toContainText("UW–Madison");
  // Let the existing page-entry motion settle before measuring the stat handoff.
  await page
    .locator(".landing-copy")
    .evaluate((el) =>
      Promise.all(el.getAnimations().map((animation) => animation.finished)),
    );
  const search = page.locator(".landing-search");
  const before = await search.boundingBox();
  await page.clock.fastForward(1800);
  await expect(page.locator(".fact-value")).toBeVisible();
  await page.clock.fastForward(600);
  await expect(page.locator(".intro")).toHaveCount(0);
  const after = await search.boundingBox();
  expect(Math.abs(after!.y - before!.y)).toBeLessThan(1);
});

test("missing daily schedule is distinguished from zero active classes", async ({
  page,
}) => {
  await page.clock.setFixedTime(now);
  await mockCampus(page);
  await page.route(`**/campus/**${date}.json`, (route) =>
    route.fulfill({ status: 404, body: "Missing schedule" }),
  );
  await page.goto("/");
  await expect(page.locator(".map-caption")).toContainText(
    "Schedule unavailable for today",
  );

  await page.route(`**/campus/**${date}.json`, (route) =>
    route.fulfill({ json: { date, events: [], buildings: [] } }),
  );
  await page.reload();
  await expect(page.locator(".campus-scene")).toContainText(
    "classes in session right now",
  );
  await expect(
    page.locator(".fact-value").getByRole("img", { name: "0", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".map-caption")).not.toContainText(
    "Schedule unavailable for today",
  );
});
