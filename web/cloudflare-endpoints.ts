import { pathToFileURL } from "node:url";
import { openapiSpec } from "../src/lib/api/openapi";

export interface Operation {
  host: string;
  method: string;
  endpoint: string;
}

const methods = new Set(["get", "post", "put", "patch", "delete", "head", "options", "trace"]);

function key(operation: Operation) {
  let parameter = 0;
  const endpoint = operation.endpoint.replace(/\{[^{}]+\}/g, () => `{var${++parameter}}`);
  return `${operation.method.toUpperCase()} ${operation.host.toLowerCase()} ${endpoint}`;
}

// This project's spec has one absolute root server and no per-operation servers.
export function endpointInventory(spec = openapiSpec()): Operation[] {
  if (spec.servers.length !== 1) throw new Error("Expected one OpenAPI server");
  const server = new URL(spec.servers[0].url);
  if (server.protocol !== "https:" || server.pathname !== "/" || server.port || server.search || server.hash)
    throw new Error("Expected an HTTPS OpenAPI server without a base path or port");
  const operations = new Map<string, Operation>();
  for (const [endpoint, value] of Object.entries(spec.paths)) {
    const item = value as Record<string, unknown>;
    if (item.servers || item.$ref) throw new Error(`Unsupported path override: ${endpoint}`);
    for (const [method, definition] of Object.entries(item)) {
      if (!methods.has(method)) continue;
      if (!definition || typeof definition !== "object" || "servers" in definition)
        throw new Error(`Unsupported operation: ${method} ${endpoint}`);
      const operation = { host: server.hostname, method: method.toUpperCase(), endpoint };
      operations.set(key(operation), operation);
    }
  }
  return [...operations.values()].sort((a, b) => key(a).localeCompare(key(b)));
}

export async function syncEndpoints(
  desired: Operation[],
  options: { zoneId: string; token: string; apply: boolean; fetcher?: typeof fetch },
) {
  if (!/^[a-f0-9]{32}$/i.test(options.zoneId) || !options.token)
    throw new Error("Set CLOUDFLARE_ZONE_ID (32 hex characters) and CLOUDFLARE_API_TOKEN");
  const fetcher = options.fetcher ?? fetch;
  const base = `https://api.cloudflare.com/client/v4/zones/${options.zoneId}/api_gateway/operations`;
  async function request(suffix: string, operation?: Operation) {
    const response = await fetcher(base + suffix, {
      method: operation ? "POST" : "GET",
      headers: { Authorization: `Bearer ${options.token}`, "Content-Type": "application/json" },
      ...(operation ? { body: JSON.stringify(operation) } : {}),
      redirect: "error",
      signal: AbortSignal.timeout(30_000),
    });
    const body = await response.json() as {
      success: boolean;
      result: Operation[] | (Operation & { operation_id: string });
      errors?: { code: number }[];
      result_info?: { total_pages?: number };
    };
    if (!response.ok || body.success !== true)
      throw new Error(`Cloudflare request failed (HTTP ${response.status}, codes: ${body.errors?.map(e => e.code).join(", ") || "unknown"})`);
    return body;
  }
  async function list() {
    const operations: Operation[] = [];
    for (let page = 1; ; page++) {
      const body = await request(`?page=${page}&per_page=50`);
      if (!Array.isArray(body.result)) throw new Error("Invalid Cloudflare operation list");
      operations.push(...body.result);
      if (body.result_info?.total_pages !== undefined
        ? page >= body.result_info.total_pages
        : body.result.length < 50) return operations;
      if (page >= 1000) throw new Error("Cloudflare pagination did not terminate");
    }
  }
  const existing = await list();
  const known = new Set(existing.map(key));
  const unique = [...new Map(desired.map(operation => [key(operation), operation])).values()];
  const missing = unique.filter(operation => !known.has(key(operation)));
  if (existing.length + missing.length > 100)
    throw new Error(`Free zone limit exceeded: ${existing.length} existing + ${missing.length} missing > 100`);
  if (options.apply && missing.length) {
    // Single-item creation is idempotent on Cloudflare; reruns also recover partial syncs.
    for (const operation of missing) await request("/item", operation);
    const saved = new Set((await list()).map(key));
    if (unique.some(operation => !saved.has(key(operation))))
      throw new Error("Cloudflare did not list every requested endpoint after sync; rerun to verify");
  }
  return { existing: existing.length, missing, total: existing.length + missing.length };
}

async function main() {
  const mode = process.argv[2];
  if (process.argv.length > 3 || (mode && !["--plan", "--apply"].includes(mode)))
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
  console.error(mode === "--apply" ? "Endpoint inventory verified." : "Plan only; no changes made.");
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(error => {
    console.error(error instanceof Error ? error.message : "Endpoint sync failed");
    process.exitCode = 1;
  });
}
