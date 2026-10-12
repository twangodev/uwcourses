"""Verify the deployed release and its database-backed search endpoints."""

import time
from urllib.parse import urlencode
from uuid import uuid4

import requests

from .deployment import Release

PROBE_HEADERS = {
    "Cache-Control": "no-cache",
    "Accept": "application/json",
    "User-Agent": "uwcourses-deploy/1",
}


def probe_json(
    url: str,
    headers: dict[str, str] | None = None,
    *,
    timeout: float = 15,
):
    response = requests.get(
        url, headers={**PROBE_HEADERS, **(headers or {})}, timeout=timeout
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as failure:
        raise requests.HTTPError(
            f"{failure}; cf-ray={response.headers.get('CF-Ray', 'none')}; "
            f"response={response.text[:300]!r}",
            response=response,
        ) from failure
    return response.json()


def smoke_check(
    base_url: str,
    release: Release,
    commit: str,
    *,
    headers: dict[str, str] | None = None,
) -> None:
    probe = uuid4().hex
    paths = [
        ("/api/status", {}),
        ("/api/search", {"q": "math"}),
        ("/api/search", {"q": "smith", "kind": "instructor"}),
        ("/api/suggest", {"q": "math"}),
        ("/api/facets", {"facets": "gpa"}),
    ]
    for attempt in range(6):
        try:
            for path, params in paths:
                # Each attempt exercises readiness and queries, even if a previous
                # successful probe was cached at this edge location.
                query = urlencode(
                    {
                        **params,
                        "revision": release.revision,
                        "_probe": f"{probe}-{attempt}",
                    }
                )
                data = probe_json(f"{base_url.rstrip('/')}{path}?{query}", headers)
                if data.get("revision") != release.revision:
                    raise ValueError(f"{path}: unexpected dataset revision")
                if path == "/api/status":
                    if (
                        data.get("site_commit") != commit
                        or data.get("projection_id") != release.projection
                    ):
                        raise ValueError(
                            "Live website does not match the deployed release"
                        )
                elif path == "/api/facets":
                    if not data.get("distributions", {}).get("gpa", {}).get("total"):
                        raise ValueError("Live GPA filters returned no data")
                elif not data.get("items"):
                    raise ValueError(f"{path}: live search returned no results")
            print(
                "Verified live course search, instructor search, suggestions and filters",
                flush=True,
            )
            return
        except (requests.RequestException, ValueError) as failure:
            if attempt == 5:
                raise
            print(f"Live search check failed: {failure}; retrying in 5s", flush=True)
            time.sleep(5)
