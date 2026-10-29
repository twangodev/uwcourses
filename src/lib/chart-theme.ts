/** A–F colors are identical in previews, histories, and analytical charts. */
export const gradeColors = [
  "var(--grade-a)",
  "var(--grade-ab)",
  "var(--grade-b)",
  "var(--grade-bc)",
  "var(--grade-c)",
  "var(--grade-d)",
  "var(--grade-f)",
];
export const chartAxis = { tickOcclusion: true, tickSpacing: 90 };
export const percentLabel = (value: number) => `${value.toFixed(1)}%`;
