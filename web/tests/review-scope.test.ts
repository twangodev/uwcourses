import { expect, it } from "vitest";
import { render } from "svelte/server";
import Claims from "../../src/lib/components/Claims.svelte";
import { claimSchema } from "../../src/lib/api/schemas";
import { importedCourse, importedAsset } from "./browser/dataset";

it("frames new and legacy review claims as past feedback without changing their prose", () => {
  const course = importedCourse(
    "json_array_length(payload,'$.evidence.reviews') > 0",
  );
  const source = course.evidence.reviews
    .flatMap(importedAsset)
    .find((r: any) => r.comment && r.instructor_name);
  expect(source).toBeDefined();
  const legacy = claimSchema.parse({
    text: source.comment,
    citations: [{ ...source, type: "review" }],
  });
  const scoped = claimSchema.parse({
    ...legacy,
    evidence_scope: "past_student_reviews",
  });
  const html = render(Claims, { props: { claims: [scoped, legacy] } }).body;
  expect(html.match(/Past student reviews/g)).toHaveLength(1);
  expect(html.match(/data-citation-trigger/g)).toHaveLength(2);
  const escape = (s: string) =>
    s.replaceAll("&", "&amp;").replaceAll("<", "&lt;");
  expect(html).toContain(escape(source.instructor_name));
  expect(html.split(escape(source.comment))).toHaveLength(3);
  expect(scoped.text).toBe(legacy.text);
});
