import { expect, it, vi } from "vitest";
vi.mock("$app/environment", () => ({ building: true, dev: true }));
import {
  bayesianRating,
  adjustInstructorRating,
} from "../../src/lib/instructor-ratings";
import { pageData, query, search } from "../../src/lib/server/data";
import { instructorRatingPrior } from "../../src/lib/server/instructor-ratings";

it("shrinks small samples toward the prior and rewards well-supported quality", () => {
  expect(bayesianRating(5, 3, 3.66)).toBeLessThan(
    bayesianRating(4.5, 200, 3.66)!,
  );
  expect(bayesianRating(4.5, 10000, 3.66)).toBeCloseTo(4.5, 2);
  expect(bayesianRating(3.66, 10, 3.66)).toBeCloseTo(3.66);
  expect(bayesianRating(null, 10, 3.66)).toBeNull();
  expect(bayesianRating(5, 0, 3.66)).toBeNull();
  expect(bayesianRating(5, 10, null)).toBeNull();
});
it("uses valid quality count rather than total comments and preserves source ratings", () => {
  const raw = { quality: 5, quality_count: 3, review_count: 100 };
  const adjusted = adjustInstructorRating(raw, 3.66);
  expect(adjusted.bayesian_quality).toBe(bayesianRating(5, 3, 3.66));
  expect(adjusted.quality).toBe(5);
  expect(raw).not.toHaveProperty("bayesian_quality");
});
it("uses deduplicated reviews and applies the same score on course, profile and search pages", async () => {
  const [expected] = await query(
    undefined,
    "SELECT AVG(json_extract(payload,'$.quality_rating')) mean FROM reviews WHERE json_extract(payload,'$.quality_rating') BETWEEN 1 AND 5",
  );
  expect(await instructorRatingPrior()).toBe(expected.mean);
  const [fixture] = await query(
    undefined,
    `
    SELECT c.uid, json_extract(i.value,'$.instructor_uid') instructor_uid
    FROM courses c JOIN json_each(c.payload,'$.instructors') i
    WHERE json_extract(i.value,'$.ratings.quality_count') >= 10
    ORDER BY c.uid LIMIT 1
  `,
  );
  expect(fixture).toBeDefined();
  const course = await pageData("courses", fixture.uid);
  const teacher = course.instructors.find(
    (i: any) => i.instructor_uid === fixture.instructor_uid,
  );
  const profile = await pageData("instructors", teacher.instructor_uid);
  expect(profile.ratings.bayesian_quality).toBe(
    teacher.ratings.bayesian_quality,
  );
  expect(profile.ratings.quality).toBe(teacher.ratings.quality);
  expect(profile.ratings.quality_count).toBe(teacher.ratings.quality_count);
  expect(profile.ratings.bayesian_quality).toBeCloseTo(
    bayesianRating(
      profile.ratings.quality,
      profile.ratings.quality_count,
      expected.mean,
    )!,
  );
  const results = await search(
    new URL(
      "http://localhost/search?kind=instructor&q=" +
        encodeURIComponent(teacher.name),
    ),
  );
  expect(
    results.items.find((row) => row.instructor_uid === teacher.instructor_uid)
      ?.bayesian_quality,
  ).toBeCloseTo(profile.ratings.bayesian_quality);
});
