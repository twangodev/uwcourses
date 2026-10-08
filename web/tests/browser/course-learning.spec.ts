import { expect, test } from "@playwright/test";
import { courseLearningRelease } from "../../../src/lib/course-learning-release";

test("official learning outcomes and citations render before and after hydration", async ({
  browser,
  page,
  baseURL,
}) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const initialPage = await context.newPage();
  await initialPage.goto(`${baseURL}/courses/COMPSCI_300`);
  const outcome =
    "List and describe common operations for List, Stack, Queue, Priority Queue, Tree.";
  for (const coursePage of [initialPage, page]) {
    if (coursePage === page) {
      await page.goto("/courses/COMPSCI_300");
      await expect(page.locator("html")).toHaveAttribute(
        "data-hydrated",
        "true",
      );
    }
    const outcomes = coursePage.getByRole("region", {
      name: "Official learning outcomes",
      exact: true,
    });
    await expect(outcomes).toBeVisible();
    const statement = outcomes.locator("li").filter({ hasText: outcome });
    await expect(statement.locator("p")).toHaveText(outcome);
    await expect(
      statement.getByRole("link", { name: "catalog", exact: true }),
    ).toHaveAttribute("href", "https://guide.wisc.edu/courses/comp_sci/");
    await expect(statement).toContainText("Catalog 2026-2027");
  }
  await context.close();
});

test("release hides activity filters even when supplied in the search URL", async ({
  page,
}) => {
  test.skip(
    courseLearningRelease.activitySearch,
    "Activity search is enabled for this release",
  );
  await page.goto(
    "/search?subject=COMPSCI&availability=all&activity=programming",
  );
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  await expect(
    page.getByRole("button", { name: "Learning activity", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", {
      name: "Remove Learning activity: Programming",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(page.locator(".discovery-card").first()).toBeVisible();
});

test("learning activity filter preserves other filters and can be removed", async ({
  page,
}) => {
  test.skip(
    !courseLearningRelease.activitySearch,
    "Activity search awaits pilot acceptance",
  );
  await page.goto("/search?subject=COMPSCI&availability=all");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  await page
    .getByRole("button", { name: "Learning activity", exact: true })
    .click();
  await page.getByRole("option", { name: "Programming", exact: true }).click();
  await expect(page).toHaveURL(/activity=programming/);
  const selected = new URL(page.url());
  expect(selected.searchParams.get("subject")).toBe("COMPSCI");
  expect(selected.searchParams.get("availability")).toBe("all");
  const chip = page.getByRole("button", {
    name: "Remove Learning activity: Programming",
    exact: true,
  });
  await expect(chip).toHaveText("Learning activity: Programming");
  await expect(chip).toBeVisible();
  await chip.click();
  await expect(page).not.toHaveURL(/activity=/);
  expect(new URL(page.url()).searchParams.get("subject")).toBe("COMPSCI");
  await expect(page.locator(".discovery-card").first()).toBeVisible();
});
