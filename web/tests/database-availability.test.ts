import { expect, it, vi } from "vitest";
import publishedStatus from "../../.site/import/status.json";
const { read, databaseSpy } = vi.hoisted(() => ({
  read: vi.fn(),
  databaseSpy: vi.fn(),
}));
vi.mock("../../src/lib/server/database", () => ({
  database: databaseSpy.mockImplementation(() => ({
    select: () => ({ from: () => ({ where: read }) }),
  })),
}));
import { withDatabaseAvailability } from "../../src/lib/server/database-availability";
const ready = [
  { key: "serving", value: "a".repeat(32) },
  { key: "ready", value: "true" },
  { key: "status", value: JSON.stringify(publishedStatus) },
];
it("serves queries only while the database matches the static documents", async () => {
  read.mockReset().mockResolvedValue(ready);
  const render = vi.fn(async () => "results");
  expect(await withDatabaseAvailability(undefined, render)).toBe("results");
  expect(read).toHaveBeenCalledTimes(2);
  for (const state of [
    [],
    ready.filter((row) => row.key !== "serving"),
    [{ key: "ready", value: "false" }],
    [
      ...ready.filter((row) => row.key !== "status"),
      { key: "status", value: '{"projection_id":"old"}' },
    ],
  ]) {
    read.mockReset().mockResolvedValue(state);
    render.mockClear();
    await expect(
      withDatabaseAvailability(undefined, render),
    ).rejects.toMatchObject({ status: 503 });
    expect(render).not.toHaveBeenCalled();
  }
});
it("discards results when an import starts during a request", async () => {
  read.mockReset().mockResolvedValue([]).mockResolvedValueOnce(ready);
  await expect(
    withDatabaseAvailability(undefined, async () => "partial results"),
  ).rejects.toMatchObject({ status: 503 });
});
it("turns a dropped schema into maintenance but preserves unrelated query failures", async () => {
  read.mockReset().mockRejectedValue(new Error("no such table: metadata"));
  await expect(
    withDatabaseAvailability(undefined, async () => "results"),
  ).rejects.toMatchObject({ status: 503 });
  read.mockReset().mockResolvedValue(ready);
  const failure = new Error("query bug");
  await expect(
    withDatabaseAvailability(undefined, async () => {
      throw failure;
    }),
  ).rejects.toBe(failure);
});

it("rejects mixed results even if an import completes with the same projection", async () => {
  const next = ready.map((row) =>
    row.key === "serving" ? { ...row, value: "b".repeat(32) } : row,
  );
  read.mockReset().mockResolvedValue(next).mockResolvedValueOnce(ready);
  await expect(
    withDatabaseAvailability(undefined, async () => "mixed results"),
  ).rejects.toMatchObject({ status: 503 });
});

it("anchors readiness through the request session and checks completion on primary", async () => {
  read.mockReset().mockResolvedValue(ready);
  databaseSpy.mockClear();
  await withDatabaseAvailability(undefined, async () => "results");
  expect(databaseSpy.mock.calls.map(([, primary]) => primary)).toEqual([
    false,
    true,
  ]);
});
it("rejects a changed serving token when a query fails during replacement", async () => {
  const next = ready.map((row) =>
    row.key === "serving" ? { ...row, value: "b".repeat(32) } : row,
  );
  read.mockReset().mockResolvedValue(next).mockResolvedValueOnce(ready);
  await expect(
    withDatabaseAvailability(undefined, async () => {
      throw new Error("query failed");
    }),
  ).rejects.toMatchObject({ status: 503 });
});
