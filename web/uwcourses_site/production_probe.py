"""Exercise the active production Worker from CI without a public bot challenge."""

from contextlib import contextmanager
import json
from pathlib import Path
import re
import time
from tempfile import TemporaryDirectory
from uuid import uuid4

import requests

from .deployment import wrangler
from .smoke import probe_json


WORKER = """
const paths = new Set(['/api/status', '/api/search', '/api/suggest', '/api/facets']);
export default {
  async fetch(request, env) {
    const incoming = new URL(request.url);
    if (request.method !== 'GET' || !paths.has(incoming.pathname) ||
        request.headers.get('X-Search-Probe') !== env.PROBE_TOKEN) {
      return new Response('Not found', { status: 404 });
    }
    const target = new URL(env.TARGET_ORIGIN);
    target.pathname = incoming.pathname;
    target.search = incoming.search;
    return env.PRODUCTION.fetch(target.href, {
      method: 'GET',
      headers: { Accept: 'application/json', 'Cache-Control': 'no-cache' }
    });
  }
};
"""


@contextmanager
def production_probe(config: Path, origin: str):
    settings = json.loads(config.read_text())
    worker = settings["name"]
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", worker):
        raise ValueError("Invalid production Worker name")
    token = uuid4().hex
    with TemporaryDirectory(prefix="uwcourses-probe-") as directory:
        root = Path(directory)
        (root / "worker.js").write_text(WORKER)
        probe_config = root / "wrangler.json"
        probe_config.write_text(
            json.dumps(
                {
                    "name": f"uwcourses-search-probe-{uuid4().hex[:16]}",
                    "main": "worker.js",
                    "compatibility_date": settings["compatibility_date"],
                    "workers_dev": True,
                    "preview_urls": False,
                    "services": [{"binding": "PRODUCTION", "service": worker}],
                    "vars": {"PROBE_TOKEN": token, "TARGET_ORIGIN": origin},
                }
            )
        )
        try:
            output = wrangler(probe_config, "deploy", capture=True)
            urls = re.findall(r"https://[a-zA-Z0-9.-]+\.workers\.dev", output)
            if len(urls) != 1:
                raise ValueError("Temporary production probe URL unavailable")
            headers = {"X-Search-Probe": token}
            for attempt in range(18):
                try:
                    probe_json(f"{urls[0]}/api/status", headers, timeout=5)
                    break
                except (requests.RequestException, ValueError):
                    if attempt == 17:
                        raise
                    print(
                        "Waiting for the temporary probe route to propagate", flush=True
                    )
                    time.sleep(5)
            print("Created authenticated production search probe", flush=True)
            yield urls[0], headers
        finally:
            wrangler(probe_config, "delete", "--force")
