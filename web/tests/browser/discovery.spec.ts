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
test("dedicated course collections preserve department filters and fixed rankings", async ({
  page,
}) => {
  await page.goto("/departments/COMPSCI");
  await page
    .getByRole("navigation", { name: "Course collections" })
    .getByRole("link", { name: "Easiest courses" })
    .click();
  await expect(page).toHaveURL(/\/departments\/COMPSCI\/easiest/);
  await expect(
    page.getByRole("heading", {
      name: "Easiest courses in Computer Sciences",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Department", exact: true }),
  ).toHaveCount(0);
  await expect(page.locator(".discovery-card").first()).toContainText("#1");
  await expect(
    page.getByRole("button", { name: "Sort courses", exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("navigation", { name: "Course collections" })
    .getByRole("link", { name: "Hardest courses" })
    .click();
  await expect(page).toHaveURL(/\/departments\/COMPSCI\/hardest/);
  await expect(
    page.getByRole("heading", {
      name: "Hardest courses in Computer Sciences",
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.locator(".discovery-card").first()).toContainText(
    "COMPSCI",
  );
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Department", exact: true }),
  ).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("department rankings are available without JavaScript and cannot switch subjects through query parameters", async ({
  browser,
  page,
  baseURL,
}) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const staticPage = await context.newPage();
  await staticPage.goto(new URL("/departments/COMPSCI/easiest", baseURL).href);
  await expect(
    staticPage.getByRole("heading", {
      name: "Easiest courses in Computer Sciences",
      exact: true,
    }),
  ).toBeVisible();
  await expect(staticPage.locator(".discovery-card").first()).toContainText(
    "COMPSCI",
  );
  await context.close();
  await page.goto("/departments/COMPSCI/easiest?subject=MATH&ranking=hardest");
  await expect(page.locator(".discovery-card").first()).toContainText(
    "COMPSCI",
  );
  await expect(
    page.getByRole("heading", {
      name: "Easiest courses in Computer Sciences",
      exact: true,
    }),
  ).toBeVisible();
  const response = await page.goto("/departments/NOTADEPARTMENT/easiest");
  expect(response?.status()).toBe(404);
});

test("main navigation opens the instructor directory on mobile", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "instructors", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Find a professor", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Search instructors")).toBeVisible();
  await expect(page.locator(".course-row").first()).toContainText("adjusted");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("department names appear in search, headings and SEO metadata", async ({
  page,
}) => {
  await page.goto("/subjects");
  await page.getByLabel("Find a department").fill("computer sciences");
  const link = page.locator('.department-grid a[href="/departments/COMPSCI"]');
  await expect(link).toContainText("Computer Sciences");
  await link.click();
  await expect(
    page.getByRole("heading", { name: "Computer Sciences", exact: true }),
  ).toBeVisible();
  await expect(page).toHaveTitle(
    "Computer Sciences Courses, Grades & Reviews | UW–Madison",
  );
  await expect(page.locator('meta[name="description"]')).toHaveAttribute(
    "content",
    /Browse Computer Sciences \(COMPSCI\) courses at UW–Madison/,
  );
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("course filters combine on search, departments, and collections", async ({
  page,
}) => {
  test.setTimeout(60000);
  await page.goto("/search");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const finder = page.getByRole("region", { name: "Find courses" });
  await expect(finder.locator(".filter-panel")).toHaveCount(0);
  await finder
    .getByRole("button", { name: "Course details", exact: true })
    .click();
  await finder.getByRole("button", { name: "Graduate", exact: true }).click();
  await expect(page).toHaveURL(/level=700(%2C|,)800(%2C|,)900/);
  await finder.getByRole("button", { name: "Schedule", exact: true }).click();
  await finder.getByRole("button", { name: "In person", exact: true }).click();
  await finder.getByRole("button", { name: "Grades", exact: true }).click();
  await finder.getByRole("button", { name: "At least 3", exact: true }).click();
  await expect(page).toHaveURL(/gpa_min=3/);
  await expect(page).toHaveURL(/mode=in_person/);
  await expect(
    finder.getByRole("button", { name: "Remove Graduate", exact: true }),
  ).toBeVisible();
  await page.locator(".discovery-card a").first().click();
  await expect(page).toHaveURL(/\/courses\//);
  await page.goBack();
  await finder
    .getByRole("button", { name: "Remove Graduate", exact: true })
    .click();
  await expect(page).not.toHaveURL(/level=/);
  await expect(page).toHaveURL(/gpa_min=3/);
  await expect(page).toHaveURL(/mode=in_person/);

  await page.goto("/departments/COMPSCI");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  await finder.getByRole("button", { name: "Schedule", exact: true }).click();
  await finder.getByRole("button", { name: "Mon", exact: true }).click();
  await finder.getByRole("button", { name: "Day match", exact: true }).click();
  await page
    .getByRole("option", { name: "At least one selected day", exact: true })
    .click();
  await finder
    .getByRole("button", { name: "Course details", exact: true })
    .click();
  await finder
    .getByRole("button", { name: "No requisites listed", exact: true })
    .click();
  await expect(page).toHaveURL(/days=mon/);
  await expect(page).toHaveURL(/days_match=any/);
  await expect(page).toHaveURL(/requisites=none/);
  await page.getByRole("button", { name: "Term", exact: true }).click();
  await page.getByRole("option", { name: "Spring 2026", exact: true }).click();
  await expect(page).toHaveURL(/term=1264/);
  await finder
    .getByRole("button", { name: "Clear filters", exact: true })
    .click();
  await expect(page).toHaveURL(/term=1264/);
  await expect(page).not.toHaveURL(/days=|days_match=|requisites=/);
  await expect(
    finder.getByRole("button", { name: "Department", exact: true }),
  ).toHaveCount(0);

  await page.goto("/courses/easiest");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  await finder
    .getByRole("button", { name: "Course details", exact: true })
    .click();
  await finder
    .getByRole("spinbutton", { name: "Credits at least", exact: true })
    .fill("3");
  await finder
    .getByRole("spinbutton", { name: "Credits at least", exact: true })
    .press("Tab");
  await expect(page).toHaveURL(/credits_min=3/);
  await expect(page.locator(".discovery-card").first()).toContainText("#1");
  await expect(
    finder.getByRole("button", { name: "Sort courses", exact: true }),
  ).toHaveCount(0);

  for (const path of [
    "/search?level=700,800,900&mode=in_person",
    "/departments/COMPSCI?days=mon",
    "/courses/easiest?credits_min=3",
  ]) {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(path);
    await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
    for (const group of [
      "Course details",
      "Schedule",
      "Grades",
      "Instructor",
    ]) {
      await finder.getByRole("button", { name: group, exact: true }).click();
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
      ).toBeLessThanOrEqual(390);
    }
  }
});

test("active filters survive reload and clear without losing search context", async ({
  page,
}) => {
  await page.goto(
    "/search?q=programming&term=1272&availability=all&sort=gpa&level=300,400&days=mon,tue&days_match=any&time=morning,afternoon&mode=in_person&credits_min=2.5&credits_max=4&gpa_min=2.5&gpa_max=3.9",
  );
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const finder = page.getByRole("region", { name: "Find courses" });
  await finder
    .getByRole("button", { name: "Course details", exact: true })
    .click();
  for (const band of ["300–399", "400–499"])
    await expect(
      finder.getByRole("button", { name: band, exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
  await expect(
    finder.getByRole("spinbutton", { name: "Credits at least", exact: true }),
  ).toHaveValue("2.5");
  await finder.getByRole("button", { name: "Schedule", exact: true }).click();
  for (const day of ["Mon", "Tue"])
    await expect(
      finder.getByRole("button", { name: day, exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
  for (const time of ["Morning", "Afternoon"])
    await expect(
      finder.getByRole("button", { name: time, exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
  await finder
    .getByRole("button", { name: "Close filters", exact: true })
    .click();
  await expect(
    finder.getByRole("button", { name: "Schedule", exact: true }),
  ).toBeFocused();
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  await finder
    .getByRole("button", { name: "Remove Meets on Mon, Tue", exact: true })
    .click();
  await expect(page).not.toHaveURL(/days=|days_match=/);
  await expect(page).toHaveURL(/time=morning/);
  await finder
    .getByRole("button", { name: "Clear filters", exact: true })
    .click();
  await expect(finder.locator(".filter-chip")).toHaveCount(0);
  await expect(page).not.toHaveURL(
    /level=|days=|time=|mode=|credits_min=|credits_max=|gpa_min=|gpa_max=/,
  );
  const params = new URL(page.url()).searchParams;
  expect(Object.fromEntries(params)).toEqual({
    q: "programming",
    term: "1272",
    availability: "all",
    sort: "gpa",
  });
});

test("instructor filters support keyboard selection and removal", async ({
  page,
}) => {
  await page.goto("/search");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const finder = page.getByRole("region", { name: "Find courses" });
  await finder.getByRole("button", { name: "Instructor", exact: true }).click();
  const input = finder.getByRole("combobox", {
    name: "Search instructors",
    exact: true,
  });
  const suggestions = page.waitForResponse(
    (response) =>
      response.url().includes("/api/suggest?") &&
      new URL(response.url()).searchParams.get("kind") === "instructor",
  );
  await input.fill("Hobbes Legault");
  const suggested = (await (await suggestions).json()).items[0].instructor_uid;
  await expect(
    finder.getByRole("option", { name: /^Hobbes Legault/ }).first(),
  ).toBeVisible();
  await input.press("Escape");
  await expect(
    finder.getByRole("listbox", {
      name: "Instructor suggestions",
      exact: true,
    }),
  ).toHaveCount(0);
  await input.press("ArrowDown");
  await expect(
    finder.getByRole("option", { name: /^Hobbes Legault/ }).first(),
  ).toBeVisible();
  await input.press("ArrowDown");
  await expect(input).toHaveAttribute("aria-activedescendant", /.+-0$/);
  await input.press("Enter");
  await expect(page).toHaveURL(new RegExp(`instructor=${suggested}`));
  await expect(
    finder.getByRole("button", {
      name: "Remove Instructor: Hobbes Legault",
      exact: true,
    }),
  ).toBeVisible();
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  await finder
    .getByRole("button", {
      name: "Remove Instructor: Hobbes Legault",
      exact: true,
    })
    .click();
  await expect(page).not.toHaveURL(/instructor=/);
});

test("cross-listed course headings stay within a narrow viewport", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/search?availability=all");
  const heading = page.locator(".card-heading a").first();
  await heading
    .locator(".code")
    .evaluate(
      (e) =>
        (e.textContent =
          "AAE/ANTHRO/C&ESOC/GEOG/HISTORY/LACIS/POLISCI/PORTUG/SOC/SPANISH 982"),
    );
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
});
