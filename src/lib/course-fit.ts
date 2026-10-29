type Section = {
  section_uid?: string;
  section_type?: string;
  section_number?: string;
  enrolled?: number | null;
};

/** Describe observed outcomes and enrollment, never inferred workload or personal success. */
export function courseFitObservations({
  gpa,
  reference,
  group,
  sections = [],
}: {
  gpa?: number | null;
  reference?: number | null;
  group: string;
  sections?: Section[];
}) {
  const sentences: { text: string; kind: "grades" | "enrollment" }[] = [];
  if (
    gpa != null &&
    reference != null &&
    Number.isFinite(gpa) &&
    Number.isFinite(reference)
  ) {
    const delta = Math.round((gpa - reference) * 100) / 100;
    sentences.push({
      kind: "grades",
      text:
        delta >= 0.2
          ? `Students tend to earn higher grades here than in other ${group} courses.`
          : delta <= -0.2
            ? `Grades tend to run lower here than in other ${group} courses.`
            : `Grade outcomes are close to the average across ${group} courses.`,
    });
  }
  const unique = [
    ...new Map(
      sections.map((section, index) => [
        section.section_uid ||
          `${section.section_type}:${section.section_number ?? index}`,
        section,
      ]),
    ).values(),
  ];
  for (const [type, noun] of [
    ["LEC", "Lectures"],
    ["DIS", "Discussion sections"],
    ["LAB", "Labs"],
  ]) {
    const sizes = unique
      .filter(
        (s) =>
          s.section_type === type &&
          typeof s.enrolled === "number" &&
          s.enrolled > 0,
      )
      .map((s) => s.enrolled!)
      .sort((a, b) => a - b);
    if (!sizes.length) continue;
    const median = Math.round(
      (sizes[Math.floor((sizes.length - 1) / 2)] +
        sizes[Math.floor(sizes.length / 2)]) /
        2,
    );
    const scale =
      median <= 30 ? "small" : median >= 100 ? "large" : "mid-sized";
    sentences.push({
      kind: "enrollment",
      text: `${noun} are ${scale}, with a median of ${median.toLocaleString("en-US")} enrolled students in the recorded sections.`,
    });
    if (type !== "LEC") break;
  }
  return sentences;
}
