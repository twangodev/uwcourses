import type { Claim, OfficialLearningOutcome } from "./types";

export const activityLabels = {
  programming: "Programming",
  "data-analysis": "Data analysis",
  "mathematical-reasoning": "Mathematical reasoning",
  writing: "Writing",
  "lab-work": "Lab work",
  presentations: "Presentations",
} as const;

export function activityLabel(value: string) {
  return activityLabels[value as keyof typeof activityLabels] ?? value;
}

/** Group identical displayed statements while retaining every source observation. */
export function groupedLearningOutcomes(outcomes: OfficialLearningOutcome[]) {
  const groups = new Map<
    string,
    { text: string; sources: OfficialLearningOutcome[] }
  >();
  for (const outcome of outcomes) {
    const key = JSON.stringify([
      outcome.text,
      outcome.term ?? null,
      outcome.catalog_year ?? null,
    ]);
    const group = groups.get(key);
    if (group) group.sources.push(outcome);
    else groups.set(key, { text: outcome.text, sources: [outcome] });
  }
  return [...groups.values()];
}

export function learningEvidence(
  claim: Claim,
  outcomes: OfficialLearningOutcome[] = [],
  description = "",
) {
  const records = Array.isArray(claim.evidence)
    ? claim.evidence
    : claim.citations || [];
  return records.flatMap((value) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return [];
    const record = value as Record<string, unknown>;
    if (typeof record.quote !== "string" || !record.quote.trim()) return [];
    let outcome: OfficialLearningOutcome | undefined;
    if (record.field === "official_learning_outcomes") {
      if (
        !Number.isInteger(record.outcome_index) ||
        Number(record.outcome_index) < 0
      )
        return [];
      outcome = outcomes[Number(record.outcome_index)];
      if (
        !outcome ||
        !outcome.text.includes(record.quote) ||
        !outcome.source_url ||
        record.source_url !== outcome.source_url
      )
        return [];
    } else if (record.field === "description") {
      if (!description || !description.includes(record.quote)) return [];
    } else return [];
    return [
      {
        ...outcome,
        ...record,
        source: outcome?.source || "Official course text",
        source_url:
          typeof record.source_url === "string"
            ? record.source_url
            : outcome?.source_url || null,
        text: record.quote,
        quote: record.quote,
        observed_at: outcome?.observed_at,
        catalog_year: outcome?.catalog_year,
        term: outcome?.term,
      },
    ];
  });
}

/** Never display derived learning claims without their supporting passage. */
export function supportedLearningClaims(
  claims: Claim[] = [],
  outcomes: OfficialLearningOutcome[] = [],
  description = "",
) {
  return claims.filter((claim) => {
    const records = Array.isArray(claim.evidence)
      ? claim.evidence
      : claim.citations || [];
    return (
      claim.text?.trim() &&
      records.length > 0 &&
      learningEvidence(claim, outcomes, description).length === records.length
    );
  });
}
