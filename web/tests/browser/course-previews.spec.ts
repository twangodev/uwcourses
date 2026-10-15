import { test, expect } from "@playwright/test";
import { importedCourse } from "./dataset";
import { courseUrl } from "../../../src/lib/format";

test("long course previews remain fully readable on a narrow screen", async ({
  page,
  request,
}) => {
  const fixture = importedCourse(`
    length(coalesce(nullif(json_extract(payload,'$.llm_summary'),''), description)) =
    (SELECT max(length(coalesce(nullif(json_extract(payload,'$.llm_summary'),''), description))) FROM courses)
  `);
  const query = new URLSearchParams({
    q: fixture.course_id,
    availability: "all",
  });
  const response = await request.get(`/api/search?${query}`);
  expect(response.ok()).toBe(true);
  const expected = (await response.json()).items.find(
    (course: any) => course.course_uid === fixture.course_uid,
  );
  expect(expected?.description).toBeTruthy();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/search?${query}`);
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true");
  const card = page.locator(".discovery-card").filter({
    has: page.locator(`a[href="${courseUrl(fixture.course_id)}"]`),
  });
  const description = card.locator(".course-description");
  await expect(description).toHaveText(expected.description);
  await expect
    .poll(() =>
      description.evaluate(
        (element) => element.scrollHeight <= element.clientHeight,
      ),
    )
    .toBe(true);
});
