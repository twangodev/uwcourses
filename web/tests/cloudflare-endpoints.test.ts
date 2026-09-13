import { expect, it, vi } from "vitest";
import { endpointInventory, syncEndpoints, type Operation } from "../cloudflare-endpoints";

const operation: Operation = { host: "uwcourses.com", method: "GET", endpoint: "/api/courses/{uid}/grades" };
const options = { zoneId: "a".repeat(32), token: "test-token", apply: true };
const reply = (result: unknown, total_pages = 1) => Response.json({ success: true, result, result_info: { total_pages } });

it("extracts the current document and interaction routes without response schemas", () => {
  const inventory = endpointInventory();
  expect(inventory).toHaveLength(40);
  expect(inventory).toContainEqual(operation);
  expect(inventory).toContainEqual({ host: "uwcourses.com", method: "GET", endpoint: "/courses/{course}.json" });
  expect(inventory.every(item => Object.keys(item).sort().join() === "endpoint,host,method")).toBe(true);
});

it("reads all pages and recognizes Cloudflare's normalized parameter names", async () => {
  const fetcher = vi.fn<typeof fetch>()
    .mockResolvedValueOnce(reply([{ ...operation, endpoint: "/unrelated" }], 2))
    .mockResolvedValueOnce(reply([{ ...operation, endpoint: "/api/courses/{var1}/grades" }], 2));
  const result = await syncEndpoints([operation], { ...options, fetcher });
  expect(result.missing).toEqual([]);
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(fetcher.mock.calls[1][0]).toContain("page=2");
  expect(fetcher.mock.calls.every(([, init]) => init?.method === "GET")).toBe(true);
});

it("plans without writing, adds only missing operations, and verifies them", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(reply([]));
  expect((await syncEndpoints([operation], { ...options, apply: false, fetcher })).missing).toEqual([operation]);
  expect(fetcher).toHaveBeenCalledTimes(1);
  fetcher.mockReset()
    .mockResolvedValueOnce(reply([]))
    .mockResolvedValueOnce(reply({ ...operation, operation_id: "saved" }))
    .mockResolvedValueOnce(reply([operation]));
  await syncEndpoints([operation], { ...options, fetcher });
  expect(fetcher.mock.calls[1][0]).toMatch(/\/operations\/item$/);
  expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body))).toEqual(operation);
  expect(fetcher).toHaveBeenCalledTimes(3);
});

it("rejects zone-wide capacity overflow before any writes", async () => {
  const existing = Array.from({ length: 100 }, (_, i) => ({ ...operation, host: "other.uwcourses.com", endpoint: `/item/${i}` }));
  const fetcher = vi.fn<typeof fetch>()
    .mockResolvedValueOnce(reply(existing.slice(0, 50), 2))
    .mockResolvedValueOnce(reply(existing.slice(50), 2));
  await expect(syncEndpoints([operation], { ...options, fetcher })).rejects.toThrow("Free zone limit exceeded");
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("stops on API failure and detects an incomplete verification", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ success: false, errors: [{ code: 10000 }] }, { status: 403 }));
  await expect(syncEndpoints([operation], { ...options, fetcher })).rejects.toThrow("HTTP 403");
  expect(fetcher).toHaveBeenCalledTimes(1);
  fetcher.mockReset()
    .mockResolvedValueOnce(reply([]))
    .mockResolvedValueOnce(reply(operation))
    .mockResolvedValueOnce(reply([]));
  await expect(syncEndpoints([operation], { ...options, fetcher })).rejects.toThrow("did not list every requested endpoint");
});
