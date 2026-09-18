import type {} from "webmcp-types";
import { expect, test } from "@playwright/test";

test.use({
  launchOptions: { args: ["--enable-experimental-web-platform-features"] },
});

test("native WebMCP searches courses and retrieves details and grades", async ({
  page,
  browser,
}) => {
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  test.skip(
    !(await page.evaluate(() => Boolean(document.modelContext))),
    "This Chromium build does not expose native WebMCP.",
  );
  await expect
    .poll(() =>
      page.evaluate(async () =>
        (await document.modelContext!.getTools())
          .map((tool) => tool.name)
          .sort(),
      ),
    )
    .toEqual([
      "get_course",
      "get_course_grades",
      "get_department",
      "get_department_catalog",
      "get_instructor",
      "get_instructor_courses",
      "get_instructor_history",
      "get_instructor_reviews",
      "list_departments",
      "open_course",
      "open_department",
      "open_explorer",
      "open_instructor",
      "open_search",
      "search_courses",
      "search_instructors",
    ]);
  const result = await page.evaluate(
    async (legacyArguments) => {
      const context = document.modelContext!;
      const tools = await context.getTools();
      async function call(name: string, input: object) {
        return JSON.parse(
          await context.executeTool(
            tools.find((tool) => tool.name === name)!,
            // Chromium before 155 takes JSON text; current types describe objects.
            (legacyArguments ? JSON.stringify(input) : input) as object,
          ),
        );
      }
      const search = await call("search_courses", {
        q: "CS 300",
        availability: "all",
      });
      const item = search.items[0];
      return {
        item,
        course: await call("get_course", { course: item.course_id }),
        grades: await call("get_course_grades", {
          course_uid: item.course_uid,
        }),
      };
    },
    Number(browser.version().split(".")[0]) < 155,
  );
  expect(result.item.course_id).toBe("COMPSCI 300");
  expect(result.course.course_id).toBe("COMPSCI 300");
  expect(result.course.document).toBe("/courses/COMPSCI_300.json");
  expect(result.grades.revision).toBeTruthy();
});

test("the site hydrates without WebMCP support", async ({ page }) => {
  await page.addInitScript(() =>
    Object.defineProperty(document, "modelContext", { value: undefined }),
  );
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  expect(errors).toEqual([]);
});
