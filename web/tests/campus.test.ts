import { buildingOutlines } from "../../src/lib/campus-buildings";
import { describe, expect, it } from "vitest";
import {
  campusHeat,
  campusIntensity,
  campusFacts,
  type CampusDay,
  campusCount,
  madisonDate,
  madisonLight,
} from "../../src/lib/campus";
import { madisonWeather } from "../../src/lib/server/weather";

describe("Madison campus clock", () => {
  it("uses Madison's date across midnight and DST", () => {
    expect(madisonDate(new Date("2026-09-10T02:00:00Z"))).toBe("2026-09-09");
    expect(madisonDate(new Date("2026-11-01T06:30:00Z"))).toBe("2026-11-01");
    expect(madisonDate(new Date("2026-11-01T07:30:00Z"))).toBe("2026-11-01");
  });
  it("ends meetings exactly at their end time", () => {
    const day = {
      date: "2026-09-09",
      events: [
        [100, 2, 0],
        [200, 1, 2],
        [300, 0, 1],
      ] as [number, number, number][],
    };
    expect(campusCount(day, 99)).toBe(0);
    expect(campusCount(day, 100)).toBe(2);
    expect(campusCount(day, 200)).toBe(1);
    expect(campusCount(day, 300)).toBe(0);
  });
  it("computes sunrise and sunset for Madison", () => {
    expect(madisonLight(new Date("2026-09-09T18:00:00Z"))?.phase).toBe("day");
    expect(madisonLight(new Date("2026-09-09T06:00:00Z"))?.phase).toBe("night");
  });
});
describe("weather observations", () => {
  const now = Date.parse("2026-09-09T18:00:00Z");
  const observation = (timestamp: string, value: number | null = 20) => ({
    properties: {
      timestamp,
      temperature: { value, unitCode: "wmoUnit:degC" },
      textDescription: "Fair",
    },
  });
  const fetcher = (value: unknown) =>
    (async () => Response.json(value)) as typeof fetch;
  it("converts fresh Celsius observations", async () => {
    expect(
      await madisonWeather(fetcher(observation("2026-09-09T17:45:00Z")), now),
    ).toMatchObject({ available: true, temperatureF: 68 });
  });
  it("does not invent weather when missing, stale or invalid", async () => {
    for (const value of [
      {},
      observation("2026-09-09T12:00:00Z"),
      observation("2026-09-10T12:00:00Z"),
      observation("2026-09-09T17:45:00Z", null),
    ]) {
      expect(await madisonWeather(fetcher(value), now)).toMatchObject({
        available: false,
        temperatureF: null,
      });
    }
  });
});

describe("rotating campus facts", () => {
  const now = new Date("2026-09-10T15:00:00Z");
  const day: CampusDay = {
    date: "2026-09-10",
    events: [
      [+now, 10, 0],
      [+now + 600000, 2, 0],
      [+now + 3600000, 0, 12],
    ],
    enrollmentEvents: [[+now, 20372, 0, 9, 0]],
  };
  it("rounds enrollment estimates and requires sufficient active coverage", () => {
    expect(
      campusFacts(day, now, null).find((f) => f.id === "students")?.value,
    ).toBe(20350);
    expect(
      campusFacts(
        { ...day, enrollmentEvents: [[+now, 20372, 0, 8, 0]] },
        now,
        null,
      ).some((f) => f.id === "students"),
    ).toBe(false);
    expect(
      campusFacts({ ...day, enrollmentEvents: undefined }, now, null).some(
        (f) => f.id === "students",
      ),
    ).toBe(false);
  });
  it("derives upcoming meetings and the earliest daily peak from event boundaries", () => {
    const facts = campusFacts(day, now, null);
    expect(facts.find((f) => f.id === "now")?.value).toBe(10);
    expect(facts.find((f) => f.id === "soon")?.value).toBe(2);
    expect(facts.find((f) => f.id === "today")?.value).toBe(12);
    expect(facts.find((f) => f.id === "peak")?.value).toBe("10:10 AM");
    expect(
      campusFacts(day, new Date(+now + 3600000), null).find(
        (f) => f.id === "now",
      )?.value,
    ).toBe(0);
  });
  it("does not reuse yesterday's schedule or fabricate attendance outside coverage", () => {
    expect(
      campusFacts(day, new Date("2026-09-11T15:00:00Z"), null).map((f) => f.id),
    ).toEqual(["sun"]);
  });
});

describe("building heat", () => {
  it("projects buildings onto the same map and ends activity at the meeting boundary", () => {
    const now = Date.parse("2026-09-10T15:00:00Z");
    const building = {
      name: "Science",
      latitude: 43.075,
      longitude: -89.408,
      events: [
        [now, 3, 0],
        [now + 60000, 0, 3],
      ] as [number, number, number][],
    };
    const day: CampusDay = {
      date: "2026-09-10",
      events: [],
      buildings: [building, { ...building, name: "Off map", longitude: -90 }],
    };
    expect(campusHeat(day, now)).toHaveLength(1);
    expect(campusHeat(day, now)[0].x).toBeCloseTo(450);
    expect(campusHeat(day, now)[0].y).toBeCloseTo(252.5);
    expect(campusHeat(day, now)[0].count).toBe(3);
    expect(campusHeat(day, now - 1)).toEqual([]);
    expect(campusHeat(day, now + 60000)).toEqual([]);
    expect(campusHeat(day, now + 86400000)).toEqual([]);
  });
});

describe("campus building footprints", () => {
  it("preserves official multipart footprints and holes, and accepts source aliases", () => {
    const outer = [
      [0, 0],
      [40, 0],
      [40, 40],
      [0, 40],
      [0, 0],
    ];
    const hole = [
      [10, 10],
      [30, 10],
      [30, 30],
      [10, 30],
      [10, 10],
    ];
    const annex = [
      [60, 0],
      [100, 0],
      [100, 40],
      [60, 40],
      [60, 0],
    ];
    const official = [
      {
        id: "uw-map:366",
        name: "Computer Sciences",
        names: ["Computer Sciences", "Computer Sciences and Statistics"],
        points: outer,
        polygons: [[outer, hole], [annex]],
      },
    ];
    const result = buildingOutlines(
      [{ name: "Unknown", x: 80, y: 20, count: 3 }],
      official,
    );
    expect(result[0].id).toBe("uw-map:366");
    expect(result[0].path.match(/M/g)).toHaveLength(3);
    expect(
      buildingOutlines([{ name: "Unknown", x: 20, y: 20, count: 3 }], official),
    ).toEqual([]);
    expect(
      buildingOutlines(
        [{ name: "Computer Sciences and Statistics", x: 20, y: 20, count: 3 }],
        official,
      )[0].id,
    ).toBe("uw-map:366");
  });
  const footprints = [
    {
      id: "a",
      name: "Science Hall",
      points: [
        [0, 0],
        [10, 0],
        [10, 10],
        [0, 10],
        [0, 0],
      ],
    },
    {
      id: "b",
      name: "Library",
      points: [
        [20, 0],
        [30, 0],
        [30, 10],
        [20, 10],
        [20, 0],
      ],
    },
  ];
  it("uses containing geometry and combines activity mapped to the same footprint", () => {
    const outlines = buildingOutlines(
      [
        { name: "Science", x: 5, y: 5, count: 3 },
        { name: "Science annex", x: 6, y: 5, count: 2 },
      ],
      footprints,
    );
    expect(outlines).toHaveLength(1);
    expect(outlines[0]).toMatchObject({
      id: "a",
      count: 5,
      path: "M0,0L10,0L10,10L0,10L0,0Z",
    });
  });
  it("does not guess between equally close buildings or highlight distant footprints", () => {
    expect(
      buildingOutlines(
        [{ name: "Unknown", x: 15, y: 5, count: 3 }],
        footprints,
      ),
    ).toEqual([]);
    expect(
      buildingOutlines(
        [{ name: "Science Hall", x: 300, y: 300, count: 3 }],
        footprints,
      ),
    ).toEqual([]);
  });
});

it("uses a bounded square-root scale with a stable schedule reference", () => {
  expect(campusIntensity(0, 100)).toBe(0);
  expect(campusIntensity(25, 100)).toBe(0.5);
  expect(campusIntensity(100, 100)).toBe(1);
  expect(campusIntensity(150, 100)).toBe(1);
  expect(campusIntensity(0, 0)).toBe(0);
});
