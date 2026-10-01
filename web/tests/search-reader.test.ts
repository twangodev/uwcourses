import { describe, expect, it, vi } from "vitest";
import { z } from "zod";
vi.mock("$lib/server/runtime", () => ({ building: false, dev: false }));
import { searchRead, searchReadQueue } from "../../src/lib/server/search-reader";

function fixture() {
  const result = { success: true, results: [{ count: 3 }], meta: { rows_read: 4, duration: 2, served_by_primary: false, served_by_region: "WNAM" } };
  const statement = { bind: vi.fn().mockReturnThis(), all: vi.fn(async () => result), first: vi.fn(), raw: vi.fn(), run: vi.fn() };
  const client = { prepare: vi.fn(() => statement), batch: vi.fn(async (rows: unknown[]) => rows.map(() => result)) };
  const report = vi.fn();
  const platform = { readContext: { client, report } } as unknown as App.Platform;
  return { platform, client, statement, result, report };
}
const row = z.object({ count: z.number().int().nonnegative() });
describe("validated search reads", () => {
  it("batches independent reads and preserves each decoder", async () => {
    const { platform, client, report } = fixture();
    const read = searchReadQueue(platform);
    const results = await Promise.all([read(row, "SELECT ? count", [3]), read(row, "SELECT ? count", [4])]);
    expect(results).toEqual([[{ count: 3 }], [{ count: 3 }]]);
    expect(client.batch).toHaveBeenCalledOnce();
    expect(report).toHaveBeenCalledWith(expect.objectContaining({ family: "facets", rows_read: 4, primary: false, statements: 2 }));
  });
  it("rejects invalid rows instead of asserting the requested type", async () => {
    const { platform, result } = fixture();
    result.results[0].count = -1;
    await expect(searchRead(platform, row, "SELECT count")).rejects.toBeInstanceOf(z.ZodError);
  });
  it("rejects invalid binds before querying D1", async () => {
    const { platform, client } = fixture();
    await expect(searchRead(platform, row, "SELECT ?", [undefined])).rejects.toThrow("parameter");
    await expect(searchRead(platform, row, "SELECT ?", [])).rejects.toThrow("count mismatch");
    expect(client.prepare).not.toHaveBeenCalled();
  });
  it("packs large valid filter combinations into a constant JSON binding", async () => {
    const { platform, client, statement } = fixture();
    await searchRead(platform, row, `SELECT ${Array(101).fill("?").join(",")}`, Array(101).fill(1));
    expect(client.prepare.mock.calls[0][0]).toContain("search_bindings AS MATERIALIZED");
    expect(statement.bind.mock.calls[0]).toHaveLength(1);
    expect(JSON.parse(statement.bind.mock.calls[0][0])).toHaveLength(101);
  });
  it("rejects every queued read when the batch fails", async () => {
    const { platform, client } = fixture();
    client.batch.mockRejectedValueOnce(new Error("D1 unavailable"));
    const read = searchReadQueue(platform);
    const results = await Promise.allSettled([read(row, "SELECT count"), read(row, "SELECT count")]);
    expect(results.every((result) => result.status === "rejected")).toBe(true);
  });
});
