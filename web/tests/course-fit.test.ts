import { expect, it } from "vitest";
import { courseFitObservations } from "../../src/lib/course-fit";

it("describes grade outcomes with stable thresholds and no personal prediction", () => {
  for (const [gpa, phrase] of [
    [3.5, "higher grades"],
    [3.1, "run lower"],
    [3.4, "close to the average"],
  ] as const) {
    expect(
      courseFitObservations({ gpa, reference: 3.3, group: "COMPSCI" }),
    ).toEqual([{ kind: "grades", text: expect.stringContaining(phrase) }]);
  }
  expect(
    courseFitObservations({ gpa: 3.4, reference: null, group: "COMPSCI" }),
  ).toEqual([]);
});
it("keeps lecture and discussion sizes separate and ignores empty or duplicated sections", () => {
  const sections = [
    { section_uid: "a", section_type: "LEC", enrolled: 150 },
    { section_uid: "a", section_type: "LEC", enrolled: 150 },
    { section_uid: "b", section_type: "LEC", enrolled: 250 },
    { section_uid: "c", section_type: "DIS", enrolled: 20 },
    { section_uid: "d", section_type: "DIS", enrolled: null },
    { section_uid: "e", section_type: "DIS", enrolled: 0 },
  ];
  expect(courseFitObservations({ group: "school", sections })).toEqual([
    {
      kind: "enrollment",
      text: expect.stringContaining("Lectures are large, with a median of 200"),
    },
    {
      kind: "enrollment",
      text: expect.stringContaining(
        "Discussion sections are small, with a median of 20",
      ),
    },
  ]);
});
it("omits unsupported claims and uses middle-sized section wording", () => {
  expect(courseFitObservations({ group: "school" })).toEqual([]);
  expect(
    courseFitObservations({
      group: "school",
      sections: [{ section_type: "LAB", enrolled: 40 }],
    }),
  ).toEqual([
    { kind: "enrollment", text: expect.stringContaining("Labs are mid-sized") },
  ]);
});
