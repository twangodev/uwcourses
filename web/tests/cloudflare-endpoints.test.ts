import { expect, it, vi } from "vitest";
import {
  endpointInventory,
  syncEndpoints,
  type Operation,
} from "../cloudflare-endpoints";

const operation: Operation = {
  host: "uwcourses.com",
  method: "GET",
  endpoint: "/api/courses/{uid}/grades",
};
const options = {
  zoneId: "a".repeat(32),
  token: "test-token",
  apply: true,
  sleep: async () => {},
};
const reply = (result: unknown, total_pages = 1) =>
  Response.json({ success: true, result, result_info: { total_pages } });

it("extracts the current document and interaction routes without response schemas", () => {
  const inventory = endpointInventory();
  expect(inventory).toHaveLength(36);
  expect(inventory).toContainEqual(operation);
  expect(inventory).toContainEqual({
    host: "uwcourses.com",
    method: "GET",
    endpoint: "/courses/{course}",
  });
  expect(inventory).toContainEqual({
    host: "uwcourses.com",
    method: "GET",
    endpoint: "/departments/{subject}/catalog.json",
  });
  expect(
    inventory.every((item) =>
      item.endpoint
        .split("/")
        .every(
          (segment) => !segment.includes("{") || /^\{[^{}]+\}$/.test(segment),
        ),
    ),
  ).toBe(true);
  expect(
    inventory.every(
      (item) => Object.keys(item).sort().join() === "endpoint,host,method",
    ),
  ).toBe(true);
});

it("reads all pages and recognizes Cloudflare's normalized parameter names", async () => {
  const fetcher = vi
    .fn<typeof fetch>()
    .mockResolvedValueOnce(reply([{ ...operation, endpoint: "/unrelated" }], 2))
    .mockResolvedValueOnce(
      reply([{ ...operation, endpoint: "/api/courses/{var1}/grades" }], 2),
    );
  const result = await syncEndpoints([operation], { ...options, fetcher });
  expect(result.missing).toEqual([]);
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(fetcher.mock.calls[1][0]).toContain("page=2");
  expect(fetcher.mock.calls.every(([, init]) => init?.method === "GET")).toBe(
    true,
  );
});

it("plans without writing, adds only missing operations, and verifies them", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(reply([]));
  expect(
    (await syncEndpoints([operation], { ...options, apply: false, fetcher }))
      .missing,
  ).toEqual([operation]);
  expect(fetcher).toHaveBeenCalledTimes(1);
  fetcher
    .mockReset()
    .mockResolvedValueOnce(reply([]))
    .mockResolvedValueOnce(reply({ ...operation, operation_id: "saved" }))
    .mockResolvedValueOnce(reply([operation]));
  await syncEndpoints([operation], { ...options, fetcher });
  expect(fetcher.mock.calls[1][0]).toMatch(/\/operations\/item$/);
  expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body))).toEqual(operation);
  expect(fetcher).toHaveBeenCalledTimes(3);
});

it("rejects zone-wide capacity overflow before any writes", async () => {
  const existing = Array.from({ length: 100 }, (_, i) => ({
    ...operation,
    host: "other.uwcourses.com",
    endpoint: `/item/${i}`,
  }));
  const fetcher = vi
    .fn<typeof fetch>()
    .mockResolvedValueOnce(reply(existing.slice(0, 50), 2))
    .mockResolvedValueOnce(reply(existing.slice(50), 2));
  await expect(
    syncEndpoints([operation], { ...options, fetcher }),
  ).rejects.toThrow("Free zone limit exceeded");
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("stops on API failure and detects an incomplete verification", async () => {
  const fetcher = vi
    .fn<typeof fetch>()
    .mockResolvedValue(
      Response.json(
        { success: false, errors: [{ code: 10000 }] },
        { status: 403 },
      ),
    );
  await expect(
    syncEndpoints([operation], { ...options, fetcher }),
  ).rejects.toThrow("HTTP 403");
  expect(fetcher).toHaveBeenCalledTimes(1);
  fetcher
    .mockReset()
    .mockResolvedValueOnce(reply([]))
    .mockResolvedValueOnce(reply({ ...operation, operation_id: "saved" }))
    .mockImplementation(async () => reply([]));
  await expect(
    syncEndpoints([operation], { ...options, fetcher }),
  ).rejects.toThrow('"missing":[{"host":"uwcourses.com"');
  expect(fetcher).toHaveBeenCalledTimes(6);
});

it("waits for inventory visibility without repeating successful writes", async () => {
  const fetcher = vi
    .fn<typeof fetch>()
    .mockResolvedValueOnce(reply([]))
    .mockResolvedValueOnce(reply({ ...operation, operation_id: "saved" }))
    .mockResolvedValueOnce(reply([]))
    .mockResolvedValueOnce(reply([]))
    .mockResolvedValueOnce(reply([operation]));
  const sleep = vi.fn(async () => {});
  await syncEndpoints([operation], { ...options, fetcher, sleep });
  expect(sleep.mock.calls).toEqual([[2000], [5000]]);
  expect(
    fetcher.mock.calls.filter(([, init]) => init?.method === "POST"),
  ).toHaveLength(1);
});

it("reports unexpected normalization instead of silently accepting broader coverage", async () => {
  const requested = { ...operation, endpoint: "/courses/{course}.json" };
  const fetcher = vi
    .fn<typeof fetch>()
    .mockResolvedValueOnce(reply([]))
    .mockResolvedValueOnce(
      reply({
        ...operation,
        endpoint: "/courses/{var1}",
        operation_id: "saved",
      }),
    );
  await expect(
    syncEndpoints([requested], { ...options, fetcher }),
  ).rejects.toThrow("Cloudflare changed endpoint patterns");
  expect(fetcher).toHaveBeenCalledTimes(2);
});

const replacement = { ...operation, endpoint: "/courses/{course}" };
const malformed = {
  ...operation,
  endpoint: "/courses/%7Bcourse%7D.json",
  operation_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
};

it("plans the exact malformed-entry repair without writing", async () => {
  const unrelated = { ...malformed, host: "other.uwcourses.com" };
  const fetcher = vi
    .fn<typeof fetch>()
    .mockResolvedValue(reply([malformed, unrelated]));
  const plan = await syncEndpoints([replacement], {
    ...options,
    apply: false,
    fetcher,
  });
  expect(plan.malformed).toEqual([malformed]);
  expect(plan.total).toBe(2);
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("verifies replacements before deleting malformed entries and safely reruns", async () => {
  const unrelated = { ...malformed, endpoint: "/unrelated/%7Bvalue%7D.json" };
  let saved = [malformed, unrelated];
  const fetcher = vi.fn<typeof fetch>(async (url, init) => {
    if (init?.method === "POST") {
      const body = JSON.parse(String(init.body));
      expect(body.endpoint).toBe("/courses/{course}");
      const created = {
        ...body,
        endpoint: "/courses/{var1}",
        operation_id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
      };
      saved.push(created);
      return reply(created);
    }
    if (init?.method === "DELETE") {
      expect(saved.some((item) => item.endpoint === "/courses/{var1}")).toBe(
        true,
      );
      expect(url).toMatch(new RegExp(`/${malformed.operation_id}$`));
      saved = saved.filter((item) => item !== malformed);
      return reply({ operation_id: malformed.operation_id });
    }
    return reply(saved);
  });
  await syncEndpoints([replacement], { ...options, fetcher });
  expect(fetcher.mock.calls.map(([, init]) => init?.method)).toEqual([
    "GET",
    "POST",
    "GET",
    "DELETE",
    "GET",
  ]);
  expect(saved).toContainEqual(unrelated);
  fetcher.mockClear();
  await syncEndpoints([replacement], { ...options, fetcher });
  expect(fetcher.mock.calls.map(([, init]) => init?.method)).toEqual(["GET"]);
});

it("never removes malformed entries if replacement verification fails", async () => {
  const fetcher = vi
    .fn<typeof fetch>()
    .mockResolvedValueOnce(reply([malformed]))
    .mockResolvedValueOnce(reply({ ...replacement, operation_id: "saved" }))
    .mockImplementation(async () => reply([malformed]));
  await expect(
    syncEndpoints([replacement], { ...options, fetcher }),
  ).rejects.toThrow("endpoint verification failed");
  expect(fetcher.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(
    false,
  );
});
