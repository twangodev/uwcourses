import type { DistributionId, FacetResponse } from "./facet-distributions";

/** Owns request cancellation and loading state; filter components only render data. */
export function createFacetDistributions(
  getFilters: () => Record<string, string>,
  getRevision: () => string,
) {
  let group = $state<readonly DistributionId[]>([]);
  let context = $state<DistributionId | null>(null);
  let data = $state<FacetResponse["distributions"]>({});
  let pending = $state(false);
  let error = $state("");
  const cache = new Map<string, FacetResponse["distributions"]>();
  const params = $derived.by(() => {
    const query = new URLSearchParams({
      ...getFilters(),
      revision: getRevision(),
    });
    query.set(
      "facets",
      [...new Set([...group, ...(context ? [context] : [])])].join(","),
    );
    query.delete("page");
    query.delete("sort");
    query.sort();
    return query.toString();
  });

  $effect(() => {
    const query = new URLSearchParams(params);
    const requested = (query.get("facets") || "")
      .split(",")
      .filter(Boolean) as DistributionId[];
    if (!requested.length) {
      pending = false;
      return;
    }
    query.delete("facets");
    const key = query.toString();
    const cached = cache.get(key);
    if (cached) data = cached;
    const missing = requested.filter((id) => !cached?.[id]);
    error = "";
    if (!missing.length) {
      pending = false;
      return;
    }
    query.set("facets", missing.join(","));
    const href = `/api/facets?${query}`;
    const controller = new AbortController();
    pending = true;
    error = "";
    const timer = setTimeout(async () => {
      try {
        const response = await fetch(href, { signal: controller.signal });
        if (!response.ok)
          throw new Error(
            response.status === 409
              ? "Dataset updated. Reload this page."
              : "Distributions are unavailable. Please try again.",
          );
        const result = (await response.json()) as FacetResponse;
        if (!controller.signal.aborted) {
          data = { ...cached, ...result.distributions };
          cache.delete(key);
          cache.set(key, data);
          if (cache.size > 24) cache.delete(cache.keys().next().value!);
        }
      } catch (cause) {
        if (!controller.signal.aborted) {
          data = {};
          error =
            cause instanceof Error
              ? cause.message
              : "Distributions unavailable.";
        }
      } finally {
        if (!controller.signal.aborted) pending = false;
      }
    }, 100);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  });

  return {
    get data() {
      return data;
    },
    get pending() {
      return pending;
    },
    get error() {
      return error;
    },
    requestGroup(ids: readonly DistributionId[]) {
      group = ids;
    },
    requestContext(id: DistributionId, open: boolean) {
      if (open) context = id;
      else if (context === id) context = null;
    },
  };
}
