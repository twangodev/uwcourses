import { test, expect } from "@playwright/test";
const instructor = "instructor_a65e64df990aa3bab98ee125";
test("department overview stays historical while finder and term statistics change", async ({
  page,
}) => {
  await page.goto("/departments/COMPSCI");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const overview = page.getByRole("region", {
    name: "Department overview",
    exact: true,
  });
  await expect(overview).toContainText("How grades break down");
  const before = await overview
    .locator('[role="img"]')
    .evaluateAll((nodes) => nodes.map((n) => n.getAttribute("aria-label")));
  await expect(page.locator(".discovery-card").first()).toContainText(
    "Offering recorded · Fall 2026",
  );
  await overview.screenshot({
    animations: "disabled",
    path: "/tmp/uwcourses-design-audit/department-overview.png",
  });
  await page.getByRole("button", { name: "Term", exact: true }).click();
  await page.getByRole("option", { name: "Spring 2026", exact: true }).click();
  await expect(
    page
      .getByRole("region", { name: "Selected-term department statistics" })
      .first(),
  ).toContainText("Spring 2026");
  expect(
    await overview
      .locator('[role="img"]')
      .evaluateAll((nodes) => nodes.map((n) => n.getAttribute("aria-label"))),
  ).toEqual(before);
  await page
    .getByRole("button", { name: "Course availability", exact: true })
    .click();
  await page.getByRole("option", { name: "Full catalog", exact: true }).click();
  await expect(page.locator(".discovery-card").first()).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
});
test("instructor reviews show original comments, paginate and filter by course", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`/instructors/${instructor}`);
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const reviews = page.locator(".student-reviews");
  await expect(reviews.locator(".student-review")).toHaveCount(6);
  await expect(reviews).toContainText("Original student reviews");
  await reviews.screenshot({
    animations: "disabled",
    path: "/tmp/uwcourses-design-audit/instructor-reviews.png",
  });
  await reviews
    .getByRole("button", { name: "Read more reviews", exact: true })
    .click();
  await expect(reviews.locator(".student-review")).toHaveCount(12);
  await page
    .getByRole("button", { name: "Reviews for course", exact: true })
    .click();
  await page.getByRole("option", { name: "COMPSCI 300", exact: true }).click();
  await expect(page.getByRole("listbox")).toHaveCount(0);
  await expect(reviews.locator(".student-review")).toHaveCount(6);
  await expect(reviews.locator(".review-meta").first()).toContainText(
    "COMPSCI 300",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  expect(errors).toEqual([]);
});
test("dedicated course collections preserve department filters and fixed rankings", async ({ page }) => {
  await page.goto("/departments/COMPSCI");
  await page.getByRole("navigation", { name: "Course collections" }).getByRole("link", { name: "Easiest courses" }).click();
  await expect(page).toHaveURL(/\/departments\/COMPSCI\/easiest/);
  await expect(page.getByRole("heading", { name: "Easiest courses in Computer Sciences", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Department", exact: true })).toHaveCount(0);
  await expect(page.locator(".discovery-card").first()).toContainText("#1");
  await expect(page.getByRole("button", { name: "Sort courses", exact: true })).toHaveCount(0);
  await page.getByRole("navigation", { name: "Course collections" }).getByRole("link", { name: "Hardest courses" }).click();
  await expect(page).toHaveURL(/\/departments\/COMPSCI\/hardest/);
  await expect(page.getByRole("heading", { name: "Hardest courses in Computer Sciences", exact: true })).toBeVisible();
  await expect(page.locator(".discovery-card").first()).toContainText("COMPSCI");
  await page.reload();
  await expect(page.getByRole("button", { name: "Department", exact: true })).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});


test("department rankings are available without JavaScript and cannot switch subjects through query parameters", async ({ browser, page, baseURL }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const staticPage = await context.newPage();
  await staticPage.goto(new URL("/departments/COMPSCI/easiest", baseURL).href);
  await expect(staticPage.getByRole("heading", { name: "Easiest courses in Computer Sciences", exact: true })).toBeVisible();
  await expect(staticPage.locator(".discovery-card").first()).toContainText("COMPSCI");
  await context.close();
  await page.goto("/departments/COMPSCI/easiest?subject=MATH&ranking=hardest");
  await expect(page.locator(".discovery-card").first()).toContainText("COMPSCI");
  await expect(page.getByRole("heading", { name: "Easiest courses in Computer Sciences", exact: true })).toBeVisible();
  const response = await page.goto("/departments/NOTADEPARTMENT/easiest");
  expect(response?.status()).toBe(404);
});

test("main navigation opens the instructor directory on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: "instructors", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Find a professor", exact: true })).toBeVisible();
  await expect(page.getByLabel("Search instructors")).toBeVisible();
  await expect(page.locator(".course-row").first()).toContainText("adjusted");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});


test("department names appear in search, headings and SEO metadata", async ({ page }) => {
  await page.goto("/subjects");
  await page.getByLabel("Find a department").fill("computer sciences");
  const link = page.locator('.department-grid a[href="/departments/COMPSCI"]');
  await expect(link).toContainText("Computer Sciences");
  await link.click();
  await expect(page.getByRole("heading", { name: "Computer Sciences", exact: true })).toBeVisible();
  await expect(page).toHaveTitle("Computer Sciences Courses, Grades & Reviews | UW–Madison");
  await expect(page.locator('meta[name="description"]')).toHaveAttribute("content", /Browse Computer Sciences \(COMPSCI\) courses at UW–Madison/);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("course filters combine on search, departments, and collections", async ({ page }) => {
  test.setTimeout(60000);
  await page.goto("/search");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const finder = page.getByRole("region", { name: "Find courses" });
  const graduate = finder.getByRole("button", { name: "Graduate", exact: true });
  if (!(await graduate.isVisible())) await page.getByText("Filters", { exact: true }).click();
  await graduate.click();
  await expect(page).toHaveURL(/level=700(%2C|,)800(%2C|,)900/);
  await finder.getByRole("checkbox", { name: "In person", exact: true }).check();
  await finder.getByLabel("Historical GPA at least").fill("3");
  await finder.getByLabel("Historical GPA at least").blur();
  await expect(page).toHaveURL(/gpa_min=3/);
  await expect(page).toHaveURL(/mode=in_person/);
  await expect(finder.getByRole("list", { name: "Active filters" })).toBeVisible();
  const card = page.locator(".discovery-card a").first();
  await expect(card).toBeVisible();
  await card.click();
  await expect(page).toHaveURL(/\/courses\//);
  await page.goBack();
  await finder.getByRole("button", { name: /Remove Course number/ }).click();
  await expect(page).not.toHaveURL(/level=/);

  await page.goto("/departments/COMPSCI");
  const department = page.getByRole("region", { name: "Find courses" });
  const monday = department.getByRole("button", { name: "Mon", exact: true });
  if (!(await monday.isVisible())) await page.getByText("Filters", { exact: true }).click();
  await monday.click();
  await department.getByRole("button", { name: "Requisites", exact: true }).click();
  await page.getByRole("option", { name: "No requisites listed", exact: true }).click();
  await expect(page).toHaveURL(/days=mon/);
  await expect(page).toHaveURL(/requisites=none/);
  await page.getByRole("button", { name: "Term", exact: true }).click();
  await page.getByRole("option", { name: "Spring 2026", exact: true }).click();
  await expect(page).toHaveURL(/term=1264/);

  await page.goto("/courses/easiest");
  const ranked = page.getByRole("region", { name: "Find courses" });
  const credits = ranked.getByLabel("At least this many credits");
  if (!(await credits.isVisible())) await page.getByText("Filters", { exact: true }).click();
  await credits.fill("3");
  await ranked.getByLabel("At least this many credits").blur();
  await expect(page).toHaveURL(/credits_min=3/);
  await expect(page.locator(".discovery-card").first()).toContainText("#1");
  await expect(page.getByRole("button", { name: "Sort courses", exact: true })).toHaveCount(0);

  for (const path of ["/search?level=700,800,900&mode=in_person", "/departments/COMPSCI?days=mon", "/courses/easiest?credits_min=3"]) {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(path);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  }
  const designation = page.getByRole("group", { name: "Catalog designation" });
  if (await designation.getByRole("checkbox").count()) {
    await designation.getByRole("checkbox").first().check();
    await expect(page).toHaveURL(/designation=/);
  } else {
    await expect(designation).toContainText("not in this snapshot");
  }
});

test('cross-listed course headings stay within a narrow viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/search?availability=all');
  const heading = page.locator('.card-heading a').first();
  await heading.locator('.code').evaluate(e => e.textContent = 'AAE/ANTHRO/C&ESOC/GEOG/HISTORY/LACIS/POLISCI/PORTUG/SOC/SPANISH 982');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
