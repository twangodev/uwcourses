import { expect, test, type Page } from "@playwright/test";
import { documentSchemas } from "../../../src/lib/api/schemas";

test("statistics documents negotiate formats and select historical terms", async ({
  request,
}) => {
  const response = await request.get("/stats.json");
  expect(response.status()).toBe(200);
  const document = await response.json();
  expect(documentSchemas.Statistics.safeParse(document).success).toBe(true);
  const stats = document.data.schoolStats;
  expect(stats.selectedTerm).toBe(document.dataset.term);
  const earlier = Object.keys(stats.terms)
    .filter((t) => t < stats.selectedTerm && stats.terms[t].gradeCount > 0)
    .sort()
    .at(-1)!;
  const selected = await (
    await request.get(`/stats.json?term=${earlier}`)
  ).json();
  expect(selected.data.schoolStats.selectedTerm).toBe(earlier);
  expect(
    (await (await request.get("/stats.json")).json()).data.schoolStats
      .selectedTerm,
  ).toBe(document.dataset.term);
  const md = await request.get(`/stats?term=${earlier}`, {
    headers: { Accept: "text/markdown" },
  });
  expect(md.headers()["content-type"]).toContain("text/markdown");
  expect(await md.text()).toContain("school Stats");
  expect(md.headers().vary.toLowerCase()).toContain("accept");
  expect((await request.get("/stats.json?term=bad")).status()).toBe(400);
});

async function closeCard(page: Page) {
  const close = page.getByRole("button", { name: "Close statistics" });
  if (await close.count()) {
    await close.click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
  }
}
async function openCard(page: Page, title: string) {
  await closeCard(page);
  await page.getByRole("button", { name: title, exact: true }).click();
  await expect(
    page.getByRole("dialog", { name: title, exact: true }),
  ).toBeVisible();
}

test("statistics dialogs are readable on mobile and respond to term changes", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/stats");
  await expect(
    page.getByRole("heading", { name: "UW–Madison statistics." }),
  ).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "Previous term" }).click();
  await expect(page).toHaveURL(/stats\?term=/);
  await openCard(page, "Campus activity");
  const selected = await (
    await page.request.get(`/stats.json${new URL(page.url()).search}`)
  ).json();
  const stats = selected.data.schoolStats;
  if (stats.terms[stats.selectedTerm].schedule.meetings > 0) {
    await expect(
      page.getByRole("dialog").locator('.map svg [role="button"]').first(),
    ).toBeVisible();
    await expect(
      page.getByText("We don’t have a building schedule", { exact: false }),
    ).toHaveCount(0);
  } else {
    await expect(
      page.getByText("We don’t have a building schedule", { exact: false }),
    ).toBeVisible();
  }
  await closeCard(page);
  await page.getByRole("button", { name: "Next term" }).click();
  await openCard(page, "Busiest hour");
  await page.locator(".heatmap button").first().focus();
  await expect(page.locator(".heat-detail")).toContainText(
    "meetings across the recorded term",
  );
  await openCard(page, "Campus activity");
  await page.locator('.map svg [role="button"]').first().focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".map .caption")).toContainText(
    "scheduled enrollment visits",
  );
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
    "href",
    "https://uwcourses.com/stats",
  );
});

test("academic dialogs drill into subjects, find courses, and show descriptive grade statistics", async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 1280, height: 1000 });
  const doc = await (await request.get("/stats.json")).json();
  const term = doc.data.schoolStats.academics.term;
  await page.goto(`/stats?term=${term}`);
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  await expect(
    page.getByText("courses with recorded grades", { exact: true }),
  ).toBeVisible();
  await openCard(page, "What Madison studies");
  const tree = page.locator(".treemap");
  await tree.getByRole("button").first().focus();
  await page.keyboard.press("Enter");
  await expect(tree.locator("a").first()).toHaveAttribute(
    "href",
    /^\/courses\//,
  );
  await page.getByRole("button", { name: "← All subjects" }).click();
  await openCard(page, "Find your course");
  const dot = page.locator('.dot-chart circle[tabindex="0"]');
  const previous = await dot.getAttribute("aria-label");
  await dot.focus();
  await page.keyboard.press("ArrowRight");
  await expect(dot).not.toHaveAttribute("aria-label", previous!);
  await page.getByLabel("Find a course in the dot plot").fill("CS 300");
  await expect(page.locator(".dot-detail a")).toHaveAttribute(
    "href",
    "/courses/COMPSCI_300",
  );
  await openCard(page, "Popular courses over time");
  await page.locator(".rank-legend button").first().click();
  await expect(page.locator(".rank-legend button").first()).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await openCard(page, "Grades");
  await expect(page.locator(".distribution-metrics")).toContainText(
    "Std. deviation",
  );
  await expect(
    page.getByRole("heading", { name: "Cumulative distribution" }),
  ).toBeVisible();
  await expect(page.locator('.grade-cdf svg[role="figure"]')).toBeVisible();
  await page.locator("summary").filter({ hasText: "Grades over time" }).click();
  await expect(
    page.getByRole("heading", { name: "How the grade mix has changed" }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page
      .getByRole("dialog")
      .evaluate((e) => e.scrollWidth <= e.clientWidth),
  ).toBe(true);
});

test("grade Sankey retains named departments, course links, and term selection in a dialog", async ({
  page,
  request,
}) => {
  const doc = await (await request.get("/stats.json")).json();
  const academics = doc.data.schoolStats.academics;
  expect(
    academics.courses.every(
      (c: { count: number; grades: number[] }) =>
        c.grades.reduce((s, v) => s + v, 0) === c.count,
    ),
  ).toBe(true);
  await page.goto("/stats");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  await openCard(page, "Grade flows");
  const flow = page.locator(".grade-flow");
  const departments = flow.getByRole("button", {
    name: /^Explore .* grade flow$/,
  });
  await departments.first().focus();
  await page.keyboard.press("Enter");
  await expect(departments).toHaveCount(1);
  await expect(flow.locator("a").first()).toHaveAttribute(
    "href",
    /^\/courses\//,
  );
  await flow
    .getByRole("button", { name: "← All departments", exact: true })
    .click();
  await expect(departments).toHaveCount(12);
  const count = new Set(
    academics.courses.flatMap((c: { subjects: string[] }) => c.subjects),
  ).size;
  await expect(flow.locator(".pagination")).toContainText(
    `Departments 1–12 of ${count}`,
  );
  await flow.getByRole("button", { name: "Next grade flows" }).click();
  await expect(flow.locator(".pagination")).toContainText(
    `Departments 13–24 of ${count}`,
  );
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await flow
      .locator(".flow-scroll")
      .evaluate((e) => e.scrollWidth > e.clientWidth),
  ).toBe(true);
  await closeCard(page);
  await page.getByRole("button", { name: "Previous term" }).click();
  await openCard(page, "Grade flows");
  await expect(
    flow.getByRole("button", { name: "← All departments", exact: true }),
  ).toHaveCount(0);
  await expect(flow.locator(".flow-chart svg")).toBeVisible();
});

test("cards open focus-trapped dialogs without rearranging the grid and return focus on dismissal", async ({
  page,
}) => {
  await page.goto("/stats");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  await expect(page.locator(".stats-card")).toHaveCount(9);
  await expect(page.locator(".grade-flow,.dot-chart,.rank-chart")).toHaveCount(
    0,
  );
  const trigger = page.getByRole("button", {
    name: "Grade flows",
    exact: true,
  });
  await trigger.focus();
  const positions = () =>
    page.locator(".stats-card").evaluateAll((es) =>
      es.map((e) => {
        const el = e as HTMLElement;
        return [el.offsetLeft, el.offsetTop, el.clientWidth, el.clientHeight];
      }),
    );
  const before = await positions();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Grade flows", exact: true });
  await expect(dialog).toBeVisible();
  expect(await positions()).toEqual(before);
  await page.keyboard.press("Shift+Tab");
  expect(await dialog.evaluate((e) => e.contains(document.activeElement))).toBe(
    true,
  );
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await trigger.click();
  await page.mouse.click(3, 3);
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("statistics distinguish an uncovered term from a recorded building schedule", async ({
  page,
  request,
}) => {
  const document = await (await request.get("/stats.json")).json();
  const stats = document.data.schoolStats;
  const uncovered = Object.keys(stats.terms).find(
    (term) => stats.terms[term].schedule.meetings === 0,
  );
  expect(uncovered).toBeTruthy();
  await page.goto(`/stats?term=${uncovered}`);
  await openCard(page, "Campus activity");
  await expect(
    page.getByText("We don’t have a building schedule", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("dialog").locator('.map svg [role="button"]'),
  ).toHaveCount(0);
});
