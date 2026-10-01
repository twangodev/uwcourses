import { describe, expect, it } from "vitest";
import {
  creditHistogramBins,
  facetOptionBins,
  gpaHistogramBins,
  histogramBinRange,
  type FacetBin,
} from "../../src/lib/facet-distributions";

describe("facet presentation", () => {
  it("selects exact half-open GPA intervals, includes 4.0 in the last bin, and selects discrete credits", () => {
    expect(histogramBinRange("3.5", 4, 0.1)).toEqual({
      min: "3.5",
      max: "3.6",
      maxExclusive: true,
    });
    expect(histogramBinRange("3.9", 4, 0.1)).toEqual({
      min: "3.9",
      max: "4",
      maxExclusive: false,
    });
    expect(histogramBinRange("0", 4, 0.1)).toEqual({
      min: "0",
      max: "0.1",
      maxExclusive: true,
    });
    expect(histogramBinRange("3", 20)).toEqual({
      min: "3",
      max: "3",
      maxExclusive: false,
    });
  });
  it("keeps unavailable choices and source identities while applying live counts", () => {
    const bins = facetOptionBins(
      [
        { value: "uid-one", label: "Same instructor" },
        { value: "uid-two", label: "Same instructor" },
        { value: "unknown", label: "Unparsed", disabled: true },
      ],
      {
        total: 10,
        matched: 2,
        missing: 0,
        bins: [
          {
            value: "uid-one",
            label: "Old display label",
            count: 5,
            matched: 2,
          },
          {
            value: "unknown",
            label: "Unparsed",
            count: 5,
            matched: 0,
            disabled: true,
          },
        ],
      },
    );
    expect(bins.map((bin) => bin.value)).toEqual([
      "uid-one",
      "uid-two",
      "unknown",
    ]);
    expect(bins[0]).toMatchObject({
      label: "Same instructor",
      count: 5,
      matched: 2,
    });
    expect(bins[1]).toMatchObject({ count: 0, matched: 0 });
    expect(bins[2].disabled).toBe(true);
  });

  it("shortens empty credit tails while preserving spacing and available alternatives", () => {
    const bins: FacetBin[] = Array.from({ length: 41 }, (_, index) => ({
      value: String(index / 2),
      label: `${index / 2} credits`,
      count: index === 6 ? 10 : 0,
      matched: index === 6 ? 2 : 0,
    }));
    const compact = creditHistogramBins(bins);
    expect(compact.map((bin) => Number(bin.value))).toEqual(
      Array.from({ length: 13 }, (_, index) => index / 2),
    );
    expect(compact.reduce((sum, bin) => sum + bin.count, 0)).toBe(10);
    bins[20].count = 5;
    const alternatives = creditHistogramBins(bins);
    expect(alternatives.at(-1)?.value).toBe("10");
    expect(alternatives.at(-1)?.matched).toBe(0);
    expect(alternatives.reduce((sum, bin) => sum + bin.count, 0)).toBe(15);
  });

  it("focuses GPA on available values while preserving gaps and alternatives outside the selected bounds", () => {
    const bins: FacetBin[] = Array.from({ length: 40 }, (_, index) => ({
      value: String(index / 10),
      label: String(index / 10),
      count: [28, 33, 37, 39].includes(index) ? 10 : 0,
      matched: index >= 37 ? 10 : 0,
    }));
    const visible = gpaHistogramBins(bins);
    expect(visible[0].value).toBe("2.7");
    expect(visible.at(-1)!.value).toBe("3.9");
    expect(visible.reduce((sum, bin) => sum + bin.count, 0)).toBe(40);
    expect(visible.find((bin) => bin.value === "2.8")!.matched).toBe(0);
    expect(visible.find((bin) => bin.value === "2.9")!.count).toBe(0);
    expect(
      gpaHistogramBins(bins.map((bin) => ({ ...bin, matched: 0 }))).map(
        (bin) => bin.value,
      ),
    ).toEqual(visible.map((bin) => bin.value));
  });

  it("keeps context around a narrow GPA cluster and handles empty or full-range results", () => {
    const bins: FacetBin[] = Array.from({ length: 40 }, (_, index) => ({
      value: String(index / 10),
      label: String(index / 10),
      count: 0,
      matched: 0,
    }));
    expect(gpaHistogramBins(bins)).toEqual(bins);
    expect(gpaHistogramBins([])).toEqual([]);
    bins[39].count = 10;
    expect(gpaHistogramBins(bins).map((bin) => bin.value)).toEqual(
      Array.from({ length: 10 }, (_, index) => String((index + 30) / 10)),
    );
    bins[39].count = 0;
    bins[20].count = 10;
    const centered = gpaHistogramBins(bins);
    expect(centered[0].value).toBe("1.5");
    expect(centered.at(-1)!.value).toBe("2.4");
    bins[0].count = bins[39].count = 10;
    expect(gpaHistogramBins(bins)).toEqual(bins);
  });
});
