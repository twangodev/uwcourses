import { describe, expect, it, vi } from "vitest";
vi.mock("$app/environment", () => ({ building: true, dev: true }));
import { courseDistributions } from "../../src/lib/server/facets";
import { courseTagValues } from "../../src/lib/course-tags";
import { search } from "../../src/lib/server/data";

const url = (params: string) =>
  new URL(`http://localhost/api/facets?${params}`);

describe("live course distributions", () => {
  it("matches tag counts to card evidence across every page and combines tags with AND", async () => {
    const base = "subject=COMPSCI&availability=all";
    const first = await search(url(base));
    const pages = await Promise.all(
      Array.from({ length: Math.ceil(first.total / 30) - 1 }, (_, index) =>
        search(url(`${base}&page=${index + 2}`)),
      ),
    );
    const items = [first, ...pages].flatMap((page) => page.items);
    const tags = (await courseDistributions(url(base + "&facets=tags")))
      .distributions.tags!;
    expect(tags.total).toBe(items.length);
    for (const tag of courseTagValues) {
      const expected = items.filter((item) =>
        item.badges.some((badge: any) => badge.tag === tag),
      );
      const selected = await search(url(`${base}&tags=${tag}`));
      expect(selected.total, tag).toBe(expected.length);
      expect(tags.bins.find((bin) => bin.value === tag)?.count ?? 0, tag).toBe(
        expected.length,
      );
      expect(selected.items.every((item) => item.badges[0]?.tag === tag)).toBe(
        true,
      );
    }
    const selectedTags = "small-lectures,higher-grades";
    const selected = await search(url(`${base}&tags=${selectedTags}`));
    expect(selected.total).toBe(
      items.filter((item) =>
        selectedTags
          .split(",")
          .every((tag) => item.badges.some((badge: any) => badge.tag === tag)),
      ).length,
    );
    const after = (
      await courseDistributions(
        url(`${base}&tags=${selectedTags}&facets=tags,gpa`),
      )
    ).distributions;
    expect(after.tags!.matched).toBe(selected.total);
    expect(after.tags!.bins.map((bin) => [bin.value, bin.count])).toEqual(
      tags.bins.map((bin) => [bin.value, bin.count]),
    );
    expect(after.gpa!.total).toBe(selected.total);
    for (const bin of after.tags!.bins) {
      expect(bin.matched).toBe(
        selected.total === 0
          ? 0
          : (await search(url(`${base}&tags=${selectedTags},${bin.value}`)))
              .total,
      );
    }
  }, 30000);

  it("recomputes grade-tag eligibility for each department alternative", async () => {
    for (const params of [
      "availability=all&tags=higher-grades",
      "availability=all&subject=COMPSCI&tags=small-lectures,higher-grades",
      "availability=all&subject=COMPSCI,MATH&tags=higher-grades",
    ]) {
      const facets = (
        await courseDistributions(url(params + "&facets=subject"))
      ).distributions.subject!;
      expect(facets.matched).toBe((await search(url(params))).total);
      const context = url(params);
      context.searchParams.delete("subject");
      expect(facets.total).toBe((await search(context)).total);
      for (const subject of ["COMPSCI", "MATH", "ENGL", "BIOCHEM"]) {
        context.searchParams.set("subject", subject);
        const expected = await search(context);
        expect(
          facets.bins.find((bin) => bin.value === subject)?.count ?? 0,
          `${params}: ${subject}`,
        ).toBe(expected.total);
      }
    }
  }, 30000);

  it("counts every matching course, excludes its own filter, and preserves pagination", async () => {
    const params = "subject=COMPSCI&availability=all&level=700,800,900";
    const result = await courseDistributions(
      url(params + "&facets=level&page=2"),
    );
    const levels = result.distributions.level!;
    expect(levels.total).toBe(
      (await search(url("subject=COMPSCI&availability=all"))).total,
    );
    expect(levels.matched).toBe((await search(url(params))).total);
    expect(levels.total).toBeGreaterThan(30);
    for (const bin of levels.bins) {
      expect(bin.count).toBe(
        (
          await search(
            url(`subject=COMPSCI&availability=all&level=${bin.value}`),
          )
        ).total,
      );
      expect(bin.matched).toBe(Number(bin.value) >= 700 ? bin.count : 0);
    }
    expect(
      (await courseDistributions(url(params + "&facets=level&page=1")))
        .distributions,
    ).toEqual(result.distributions);
  });

  it("uses exactly the search schedule semantics for alternatives and matching overlays", async () => {
    const params =
      "subject=COMPSCI&days=mon,tue&days_match=any&time=morning&mode=in_person";
    const result = await courseDistributions(
      url(params + "&facets=days,time,mode"),
    );
    const current = await search(url(params));
    for (const key of ["days", "time", "mode"] as const) {
      for (const bin of result.distributions[key]!.bins) {
        const candidate = url(params);
        candidate.searchParams.set(key, bin.value);
        expect(bin.count).toBe((await search(candidate)).total);
        expect(bin.matched).toBeLessThanOrEqual(bin.count);
        expect(bin.matched).toBeLessThanOrEqual(current.total);
      }
    }
  });

  it("shows actual weekday distributions before choosing an only-these-days combination", async () => {
    const base = "subject=MATH&availability=all";
    const result = (await courseDistributions(url(base + "&facets=days")))
      .distributions.days!;
    for (const bin of result.bins) {
      expect(bin.count).toBe(
        (await search(url(base + `&days=${bin.value}&days_match=any`))).total,
      );
      expect(bin.matched).toBe(bin.count);
    }
    expect(
      result.bins.find((bin) => bin.value === "wed")!.count,
    ).toBeGreaterThan(0);
  });

  it("matches historical GPA bins to the selected five-year window, including missing grades", async () => {
    const base = "subject=COMPSCI&availability=all&term=1264";
    const selected = base + "&gpa_min=3.2&gpa_max=3.9";
    const gpa = (await courseDistributions(url(selected + "&facets=gpa")))
      .distributions.gpa!;
    expect(gpa.bins.map((bin) => Number(bin.value))).toEqual(
      Array.from({ length: 40 }, (_, index) => index / 10),
    );
    expect(gpa.bins.at(-1)!.label).toBe("3.9–4.0");
    expect(gpa.matched).toBe((await search(url(selected))).total);
    expect(
      gpa.bins.reduce((sum, bin) => sum + bin.count, 0) + gpa.missing,
    ).toBe(gpa.total);
    expect(gpa.bins.reduce((sum, bin) => sum + bin.matched, 0)).toBe(
      gpa.matched,
    );
    for (const bin of gpa.bins) {
      const lo = Number(bin.value),
        hi = lo === 3.9 ? 4 : lo + 0.1 - 1e-12;
      expect(bin.count).toBe(
        (await search(url(`${base}&gpa_min=${lo}&gpa_max=${hi}`))).total,
      );
    }
  });

  it("counts variable-credit courses once per possible credit value", async () => {
    const base = "subject=COMPSCI&availability=all";
    const credits = (
      await courseDistributions(
        url(base + "&credits_min=3&credits_max=4&facets=credits"),
      )
    ).distributions.credits!;
    expect(credits.bins.map((bin) => Number(bin.value))).toEqual(
      Array.from({ length: 41 }, (_, index) => index / 2),
    );
    for (const bin of credits.bins.filter((bin) => bin.count > 0)) {
      expect(bin.count).toBe(
        (
          await search(
            url(`${base}&credits_min=${bin.value}&credits_max=${bin.value}`),
          )
        ).total,
      );
    }
    expect(
      credits.bins.reduce((sum, bin) => sum + bin.count, 0),
    ).toBeGreaterThan(credits.total);
  });
  it("selects exactly the GPA courses represented by a histogram bin", async () => {
    const base = "subject=COMPSCI&availability=all";
    const original = (await courseDistributions(url(base + "&facets=gpa")))
      .distributions.gpa!;
    for (const bin of original.bins.filter((bin) => bin.count > 0)) {
      const upper = (Number(bin.value) + 0.1).toFixed(1);
      const selected = `${base}&gpa_min=${bin.value}&gpa_max=${upper}${upper === "4.0" ? "" : "&gpa_max_exclusive=true"}`;
      const result = (await courseDistributions(url(selected + "&facets=gpa")))
        .distributions.gpa!;
      expect((await search(url(selected))).total).toBe(bin.count);
      expect(result.matched).toBe(bin.count);
      expect(
        result.bins.filter((row) => row.matched > 0).map((row) => row.value),
      ).toEqual([bin.value]);
      expect(result.bins.map((row) => row.count)).toEqual(
        original.bins.map((row) => row.count),
      );
    }
  });

  it("keeps collection eligibility and distinct instructor identities", async () => {
    const ranked = (
      await courseDistributions(
        url("subject=COMPSCI&ranking=easiest&facets=level,gpa"),
      )
    ).distributions;
    expect(ranked.level!.matched).toBe(
      (await search(url("subject=COMPSCI&ranking=easiest"))).total,
    );
    expect(ranked.gpa!.missing).toBe(0);
    const instructors = (
      await courseDistributions(
        url("subject=COMPSCI&availability=all&facets=instructor"),
      )
    ).distributions.instructor!;
    expect(new Set(instructors.bins.map((bin) => bin.value)).size).toBe(
      instructors.bins.length,
    );
    for (const bin of instructors.bins)
      expect(bin.count).toBe(
        (
          await search(
            url(`subject=COMPSCI&availability=all&instructor=${bin.value}`),
          )
        ).total,
      );
  });

  it("counts alternate terms and availability against the same live filters", async () => {
    const base = "subject=COMPSCI&gpa_min=3.5";
    const facets = (
      await courseDistributions(url(base + "&facets=term,availability"))
    ).distributions;
    for (const bin of facets.term!.bins)
      expect(bin.count).toBe(
        (await search(url(`${base}&term=${bin.value}`))).total,
      );
    for (const bin of facets.availability!.bins)
      expect(bin.count).toBe(
        (await search(url(`${base}&availability=${bin.value}`))).total,
      );
  });

  it("deduplicates cross-listed courses and preserves uncertain requisites", async () => {
    const subject = (
      await courseDistributions(url("availability=all&facets=subject"))
    ).distributions.subject!;
    expect(subject.bins.find((bin) => bin.value === "COMPSCI")!.count).toBe(
      (await search(url("availability=all&subject=COMPSCI"))).total,
    );
    const requisites = (
      await courseDistributions(
        url("subject=COMPSCI&availability=all&facets=requisites"),
      )
    ).distributions.requisites!;
    expect(
      requisites.bins.find((bin) => bin.value === "unknown")?.disabled,
    ).toBe(true);
    expect(
      requisites.bins.find((bin) => bin.value === "none")?.count ?? 0,
    ).toBe(
      (await search(url("subject=COMPSCI&availability=all&requisites=none")))
        .total,
    );
  });

  it("keeps text search and exact course aliases consistent with the results", async () => {
    for (const q of ["CS 300", "programming"]) {
      const base = `q=${encodeURIComponent(q)}&availability=all`;
      const facets = (
        await courseDistributions(url(base + "&facets=subject,level,gpa"))
      ).distributions;
      const current = await search(url(base));
      expect(current.total).toBeGreaterThan(0);
      expect(facets.level!.matched).toBe(current.total);
      expect(facets.gpa!.matched).toBe(current.total);
      for (const bin of facets.subject!.bins)
        expect(bin.count, `${q}: ${bin.value}`).toBe(
          (
            await search(
              url(base + `&subject=${encodeURIComponent(bin.value)}`),
            )
          ).total,
        );
    }
  });

  it("rejects malformed filters instead of publishing fabricated counts", async () => {
    for (const params of [
      "facets=unknown",
      "tags=easy",
      "days=bogus",
      "gpa_min=nope",
      "term=wrong",
      "ranking=unknown",
      "availability=wrong",
    ])
      await expect(courseDistributions(url(params))).rejects.toMatchObject({
        status: 400,
      });
  });
});
