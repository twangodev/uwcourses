export const distributionIds = [
  "tags",
  "subject",
  "term",
  "availability",
  "level",
  "credits",
  "gpa",
  "requisites",
  "season",
  "designation",
  "instructor",
  "days",
  "time",
  "mode",
] as const;
export type DistributionId = (typeof distributionIds)[number];
export type FacetBin = {
  value: string;
  label: string;
  count: number;
  matched: number;
  disabled?: boolean;
};
export type FacetDistribution = {
  total: number;
  matched: number;
  bins: FacetBin[];
  missing: number;
};
export type FacetResponse = {
  revision: string;
  distributions: Partial<Record<DistributionId, FacetDistribution>>;
};

export type FacetOption = { value: string; label: string; disabled?: boolean };
export type HistogramRange = {
  min: string;
  max: string;
  maxExclusive: boolean;
};

export function histogramBinRange(
  value: string,
  limit: number,
  interval?: number,
): HistogramRange {
  const lower = Number(value);
  const upper =
    interval === undefined
      ? lower
      : Math.min(limit, Number((lower + interval).toFixed(10)));
  return {
    min: String(lower),
    max: String(upper),
    maxExclusive: interval !== undefined && upper < limit,
  };
}

export function facetOptionBins(
  options: readonly FacetOption[],
  distribution?: FacetDistribution,
): FacetBin[] {
  const indexed = new Map(distribution?.bins.map((bin) => [bin.value, bin]));
  return options.map((option) => {
    const bin = indexed.get(option.value);
    return {
      ...bin,
      ...option,
      count: bin?.count ?? 0,
      matched: bin?.matched ?? 0,
    };
  });
}

/** Keep half-step spacing, without a long empty tail beyond the available values. */
export function creditHistogramBins(bins: FacetBin[]) {
  const last = bins.findLastIndex((bin) => bin.count > 0);
  return bins.slice(0, Math.max(13, last + 1));
}

/** Focus the axis on available GPAs; changing GPA bounds keeps the comparison fixed. */
export function gpaHistogramBins(bins: FacetBin[]) {
  const first = bins.findIndex((bin) => bin.count > 0);
  const last = bins.findLastIndex((bin) => bin.count > 0);
  if (first < 0) return bins;
  let start = Math.max(0, first - 1);
  let end = Math.min(bins.length, last + 2);
  const minimum = Math.min(10, bins.length);
  if (end - start < minimum) {
    start = Math.max(
      0,
      Math.min(bins.length - minimum, Math.floor((start + end - minimum) / 2)),
    );
    end = start + minimum;
  }
  return bins.slice(start, end);
}
