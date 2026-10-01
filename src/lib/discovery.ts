export const gradeKeys = ["a", "ab", "b", "bc", "c", "d", "f"] as const;
export const gradeWeights = [4, 3.5, 3, 2.5, 2, 1, 0];
export function gradeSummary(
  rows: (Partial<Record<(typeof gradeKeys)[number], number | null>> & {
    term?: string;
  })[],
) {
  const counts = gradeKeys.map((key) =>
    rows.reduce((sum, row) => sum + Number(row[key] || 0), 0),
  );
  const count = counts.reduce((sum, n) => sum + n, 0);
  const terms = [
    ...new Set(
      rows
        .filter((row) => gradeKeys.some((key) => Number(row[key]) > 0))
        .flatMap((row) => (row.term ? [row.term] : [])),
    ),
  ].sort();
  return {
    counts,
    count,
    gpa: count
      ? counts.reduce((sum, n, i) => sum + n * gradeWeights[i], 0) / count
      : null,
    topShare: count ? ((counts[0] + counts[1]) / count) * 100 : null,
    firstTerm: terms[0],
    lastTerm: terms.at(-1),
  };
}
