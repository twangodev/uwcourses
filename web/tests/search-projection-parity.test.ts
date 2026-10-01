import { expect, it, vi } from "vitest";
vi.mock("$app/environment", () => ({ building: true, dev: true }));
import * as projection from "../../src/lib/server/search-projection";
import { searchCourses } from "../../src/lib/server/data";
import { courseDistributions } from "../../src/lib/server/facets";
import published from "../../.site/import/status.json";

it.skipIf(!projection.searchProjection(published.term).available)(
  "projected cards and distributions preserve canonical results",
  async () => {
    const original = projection.searchProjection;
    const override = vi.spyOn(projection, "searchProjection");
    try {
      for (const params of [
        "subject=COMPSCI&availability=all&tags=small-lectures,higher-grades",
        "subject=MATH&availability=all&gpa_min=3.5&sort=gpa",
        "subject=COMPSCI&availability=all&term=1252",
        "subject=COMPSCI&availability=all&term=1282&tags=higher-grades",
      ]) {
        const url = new URL(`http://localhost/api/search?${params}`);
        override.mockImplementation(original);
        const projected = await searchCourses(url);
        const projectedFacets = await courseDistributions(
          new URL(url + "&facets=tags,gpa,subject"),
        );
        override.mockReturnValue({ available: false, window: false });
        const canonical = await searchCourses(url);
        const canonicalFacets = await courseDistributions(
          new URL(url + "&facets=tags,gpa,subject"),
        );
        expect(
          projected.items.map(
            ({ course_uid, description, badges, discovery }) => ({
              course_uid,
              description,
              badges,
              history: discovery?.history,
              claim: discovery?.claim,
              reviewFiles: discovery?.reviewFiles,
            }),
          ),
          params,
        ).toEqual(
          canonical.items.map(
            ({ course_uid, description, badges, discovery }) => ({
              course_uid,
              description,
              badges,
              history: discovery?.history,
              claim: discovery?.claim,
              reviewFiles: discovery?.reviewFiles,
            }),
          ),
        );
        expect(projected.total, params).toBe(canonical.total);
        expect(projectedFacets, params).toEqual(canonicalFacets);
      }
    } finally {
      override.mockRestore();
    }
  },
  30000,
);

it("large schedule combinations retain coherent counts within D1 bind limits", async () => {
  const params = new URLSearchParams({
    availability: "all",
    subject: published.departments
      .slice(0, 12)
      .map((row) => row.subject)
      .join(","),
    level: "0,100,200,300,400,500,600,700,800,900",
    gpa_min: "0",
    gpa_max: "4",
    credits_min: "0",
    credits_max: "20",
    days: "mon,tue,wed,thu,fri,sat,sun",
    time: "morning,afternoon,evening",
    mode: "in_person,online,mixed",
    facets: "days,time,mode",
  });
  const url = new URL(`http://localhost/api/facets?${params}`);
  const distributions = (await courseDistributions(url)).distributions;
  const selected = await searchCourses(url);
  for (const id of ["days", "time", "mode"]) {
    expect(distributions[id]!.matched).toBe(selected.total);
    expect(distributions[id]!.missing).toBeGreaterThanOrEqual(0);
  }
});
