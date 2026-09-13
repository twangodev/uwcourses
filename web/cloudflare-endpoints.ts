import { pathToFileURL } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import { openapiSpec } from "../src/lib/api/openapi";

export interface Operation {
  host: string;
  method: string;
  endpoint: string;
}

const methods = new Set([
  "get",
  "post",
  "put",
  "patch",
  "delete",
  "head",
  "options",
  "trace",
]);

function key(operation: Operation) {
  let parameter = 0;
  const endpoint = operation.endpoint.replace(
    /\{[^{}]+\}/g,
    () => `{var${++parameter}}`,
  );
  return `${operation.method.toUpperCase()} ${operation.host.toLowerCase()} ${endpoint}`;
}

// This project's spec has one absolute root server and no per-operation servers.
function openapiOperations(spec = openapiSpec()): Operation[] {
  if (spec.servers.length !== 1) throw new Error("Expected one OpenAPI server");
  const server = new URL(spec.servers[0].url);
  if (
    server.protocol !== "https:" ||
    server.pathname !== "/" ||
    server.port ||
    server.search ||
    server.hash
  )
    throw new Error(
      "Expected an HTTPS OpenAPI server without a base path or port",
    );
  const operations = new Map<string, Operation>();
  for (const [endpoint, value] of Object.entries(spec.paths)) {
    const item = value as Record<string, unknown>;
    if (item.servers || item.$ref)
      throw new Error(`Unsupported path override: ${endpoint}`);
    for (const [method, definition] of Object.entries(item)) {
      if (!methods.has(method)) continue;
      if (
        !definition ||
        typeof definition !== "object" ||
        "servers" in definition
      )
        throw new Error(`Unsupported operation: ${method} ${endpoint}`);
      const operation = {
        host: server.hostname,
        method: method.toUpperCase(),
        endpoint,
      };
      operations.set(key(operation), operation);
    }
  }
  return [...operations.values()].sort((a, b) => key(a).localeCompare(key(b)));
}

function monitoringPath(endpoint: string) {
  return endpoint
    .split("/")
    .map((segment) => {
      // Cloudflare variables must occupy a whole segment. This deliberately groups
      // HTML, JSON and Markdown detail requests into the same monitoring operation.
      const document = segment.match(/^(\{[^{}]+\})\.(?:json|md)$/);
      if (document) return document[1];
      if (/[{}]/.test(segment) && !/^\{[^{}]+\}$/.test(segment))
        throw new Error(`Unsupported Cloudflare path segment: ${segment}`);
      return segment;
    })
    .join("/");
}

export function endpointInventory(spec = openapiSpec()): Operation[] {
  const mapped = openapiOperations(spec).map((operation) => ({
    ...operation,
    endpoint: monitoringPath(operation.endpoint),
  }));
  return [
    ...new Map(mapped.map((operation) => [key(operation), operation])).values(),
  ];
}

// Only repair the eight malformed entries emitted by the original implementation.
// Do not turn this into a generic delete of encoded paths or stale operations.
const malformedPaths = new Set(
  [
    ["courses", "course"],
    ["departments", "subject"],
    ["explorer", "subject"],
    ["instructors", "instructor"],
  ].flatMap(([prefix, parameter]) =>
    ["json", "md"].map((format) => `/${prefix}/%7B${parameter}%7D.${format}`),
  ),
);

export async function syncEndpoints(
  desired: Operation[],
  options: {
    zoneId: string;
    token: string;
    apply: boolean;
    fetcher?: typeof fetch;
    sleep?: (ms: number) => Promise<void>;
  },
) {
  if (!/^[a-f0-9]{32}$/i.test(options.zoneId) || !options.token)
    throw new Error(
      "Set CLOUDFLARE_ZONE_ID (32 hex characters) and CLOUDFLARE_API_TOKEN",
    );
  const fetcher = options.fetcher ?? fetch;
  const base = `https://api.cloudflare.com/client/v4/zones/${options.zoneId}/api_gateway/operations`;
  async function request(
    suffix: string,
    operation?: Operation,
    method = operation ? "POST" : "GET",
  ) {
    const response = await fetcher(base + suffix, {
      method,
      headers: {
        Authorization: `Bearer ${options.token}`,
        "Content-Type": "application/json",
      },
      ...(operation ? { body: JSON.stringify(operation) } : {}),
      redirect: "error",
      signal: AbortSignal.timeout(30_000),
    });
    const body = (await response.json()) as {
      success: boolean;
      result:
        | (Operation & { operation_id?: string })[]
        | (Operation & { operation_id: string });
      errors?: { code: number }[];
      result_info?: { total_pages?: number };
    };
    if (!response.ok || body.success !== true)
      throw new Error(
        `Cloudflare request failed (HTTP ${response.status}, codes: ${body.errors?.map((e) => e.code).join(", ") || "unknown"})`,
      );
    return body;
  }
  async function list() {
    const operations: (Operation & { operation_id?: string })[] = [];
    for (let page = 1; ; page++) {
      const body = await request(`?page=${page}&per_page=50`);
      if (!Array.isArray(body.result))
        throw new Error("Invalid Cloudflare operation list");
      operations.push(...body.result);
      if (
        body.result_info?.total_pages !== undefined
          ? page >= body.result_info.total_pages
          : body.result.length < 50
      )
        return operations;
      if (page >= 1000)
        throw new Error("Cloudflare pagination did not terminate");
    }
  }
  const existing = await list();
  const known = new Set(existing.map(key));
  const unique = [
    ...new Map(
      desired.map((operation) => [key(operation), operation]),
    ).values(),
  ];
  const missing = unique.filter((operation) => !known.has(key(operation)));
  const desiredKeys = new Set(unique.map(key));
  const malformed = existing.filter((operation) => {
    if (
      operation.host !== "uwcourses.com" ||
      operation.method !== "GET" ||
      !malformedPaths.has(operation.endpoint)
    )
      return false;
    const replacement = {
      ...operation,
      endpoint: monitoringPath(decodeURIComponent(operation.endpoint)),
    };
    return desiredKeys.has(key(replacement));
  });
  for (const operation of malformed) {
    if (
      !operation.operation_id ||
      !/^[a-f0-9-]{36}$/i.test(operation.operation_id)
    )
      throw new Error(
        `Missing or invalid operation ID for malformed entry: ${operation.endpoint}`,
      );
  }
  if (existing.length + missing.length > 100)
    throw new Error(
      `Free zone limit exceeded: ${existing.length} existing + ${missing.length} missing > 100`,
    );
  if (options.apply && (missing.length || malformed.length)) {
    // Single-item creation is idempotent on Cloudflare; reruns also recover partial syncs.
    const accepted: {
      requested: Operation;
      returned: Operation;
      operation_id: string;
    }[] = [];
    for (const operation of missing) {
      const { result } = await request("/item", operation);
      if (
        Array.isArray(result) ||
        !result?.operation_id ||
        typeof result.endpoint !== "string" ||
        typeof result.host !== "string" ||
        typeof result.method !== "string"
      )
        throw new Error(
          `Invalid Cloudflare creation result for ${key(operation)}`,
        );
      const returned = {
        host: result.host,
        method: result.method,
        endpoint: result.endpoint,
      };
      accepted.push({
        requested: operation,
        returned,
        operation_id: result.operation_id,
      });
      console.error(
        `Cloudflare accepted ${key(operation)} as ${key(returned)} (${result.operation_id})`,
      );
    }
    // Check route semantics as well as presence: accepting a broader normalized
    // pattern must not silently count as monitoring the requested route separately.
    const changed = accepted.filter(
      (item) => key(item.requested) !== key(item.returned),
    );
    if (changed.length)
      throw new Error(
        `Cloudflare changed endpoint patterns: ${JSON.stringify(changed)}`,
      );
    const sleep = options.sleep ?? ((ms) => delay(ms));
    async function verify(deleted: boolean) {
      const waits = [0, 2000, 5000, 10000];
      for (const [attempt, wait] of waits.entries()) {
        if (wait) await sleep(wait);
        const observed = await list();
        const saved = new Set(observed.map(key));
        const absent = unique.filter((operation) => !saved.has(key(operation)));
        const remaining = deleted
          ? observed.filter((operation) =>
              malformed.some((old) => key(old) === key(operation)),
            )
          : [];
        if (!absent.length && !remaining.length) return;
        console.error(
          `Cloudflare inventory verification ${attempt + 1}/${waits.length}: ${absent.length} endpoints not yet listed`,
        );
        if (attempt === waits.length - 1)
          throw new Error(
            `Cloudflare endpoint verification failed: ${JSON.stringify({ missing: absent, remainingMalformed: remaining, observed, accepted })}`,
          );
      }
    }
    await verify(false);
    for (const operation of malformed) {
      console.error(
        `Removing malformed entry ${key(operation)} (${operation.operation_id})`,
      );
      await request(`/${operation.operation_id}`, undefined, "DELETE");
    }
    if (malformed.length) await verify(true);
  }
  return {
    existing: existing.length,
    missing,
    malformed,
    total: existing.length + missing.length - malformed.length,
  };
}

async function main() {
  const mode = process.argv[2];
  if (
    process.argv.length > 3 ||
    (mode && !["--plan", "--apply"].includes(mode))
  )
    throw new Error("Usage: bun run cloudflare:endpoints [--plan | --apply]");
  const desired = endpointInventory();
  if (!mode) {
    console.log(JSON.stringify(desired, null, 2));
    console.error(`${desired.length} OpenAPI endpoints; offline preview only.`);
    return;
  }
  const result = await syncEndpoints(desired, {
    zoneId: process.env.CLOUDFLARE_ZONE_ID ?? "",
    token: process.env.CLOUDFLARE_API_TOKEN ?? "",
    apply: mode === "--apply",
  });
  console.log(JSON.stringify(result, null, 2));
  console.error(
    mode === "--apply"
      ? "Endpoint inventory verified."
      : "Plan only; no changes made.",
  );
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  main().catch((error) => {
    console.error(
      error instanceof Error ? error.message : "Endpoint sync failed",
    );
    process.exitCode = 1;
  });
}
