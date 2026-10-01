import { searchRequestPlatform } from "$lib/server/search-session";
import { withDatabaseAvailability } from "$lib/server/database-availability";
import { isFilteredDocument } from "$lib/server/documents/storage";
import { ZodError } from "zod";
import { building, dev } from "$app/environment";
import { redirect, isHttpError, type Handle } from "@sveltejs/kit";
import { representation, isDocument, alternateLinks } from "$lib/documents";
import { documentResponse } from "$lib/server/documents/response";
import { negotiatedFormat } from "$lib/server/content-negotiation";
import { cachedResponse, cachedApiResponse, isSearchApi } from "$lib/server/response-cache";

export const handle: Handle = async ({ event, resolve }) => {
  const path = event.url.pathname;
  const search = building ? "" : event.url.search;
  if (path.startsWith("/subjects/"))
    redirect(308, "/departments/" + path.slice("/subjects/".length) + search);
  if (path === "/live" || path === "/upload") redirect(308, "/search" + search);
  const negotiable = !event.isDataRequest && isDocument(path) &&
    ["GET", "HEAD"].includes(event.request.method);
  const format = negotiable ? negotiatedFormat(event.request.headers.get("accept")) : "html";
  const requested = representation(path) ??
    (format !== "html" ? { path, format } : null);
  const render = async () => {
    if (requested) {
      try {
        return await documentResponse(event, requested);
      } catch (error) {
        const status = isHttpError(error) ? error.status : 500;
        if (status === 500) console.error("Document response failed", error);
        return new Response(
          JSON.stringify({
            error: isHttpError(error)
              ? error.body.message
              : "Document unavailable",
            ...(dev && error instanceof ZodError
              ? { issues: error.issues }
              : {}),
          }),
          {
            status,
            headers: {
              "Content-Type": "application/json",
              "X-Robots-Tag": "noindex",
              "Cache-Control": "no-store",
            },
          },
        );
      }
    }
    const response = await resolve(event);
    if (event.isDataRequest || path.startsWith("/api/"))
      response.headers.set("X-Robots-Tag", "noindex");
    if (
      !event.isDataRequest &&
      response.status === 200 &&
      isDocument(path) &&
      response.headers.get("content-type")?.includes("text/html")
    )
      response.headers.append("Link", alternateLinks(path, event.url.search));
    return response;
  };
  const documentUrl = new URL(event.url);
  documentUrl.pathname = requested?.path || path;
  const needsDatabase =
    (path.startsWith("/api/") && !["/api/status", "/api/weather"].includes(path)) ||
    isFilteredDocument(documentUrl);
  const serve =
    !building && !dev && needsDatabase
      ? () => {
          if (event.platform) event.platform = searchRequestPlatform(event.platform);
          return withDatabaseAvailability(event.platform, render);
        }
      : render;
  const response = await (!building && !dev && (requested || isDocument(path))
    ? cachedResponse(event, serve, format)
    : !building && !dev && isSearchApi(path) ? cachedApiResponse(event, serve) : serve());
  if (negotiable) {
    // Set this after the internal cache: its key already contains the chosen format.
    const headers = new Headers(response.headers);
    const vary = headers.get("Vary")?.split(",").map((value) => value.trim()) ?? [];
    if (!vary.some((value) => ["*", "accept"].includes(value.toLowerCase())))
      headers.append("Vary", "Accept");
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
  }
  return response;
};
