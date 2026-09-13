"""Publish a verified website release with native Wrangler commands.

A single D1 is marked unavailable during imports, then verified before publishing.
No shell is involved; a failed import/verification never proceeds to deployment.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
from uuid import uuid4
from typing import Any

import requests


@dataclass(frozen=True)
class Release:
    revision: str
    projection: str
    courses: int

    @classmethod
    def read(cls, path: Path) -> "Release":
        data = json.loads(path.read_text())
        if (
            data.get("limited") is not False
            or not re.fullmatch(r"[a-f0-9]{40}", data.get("revision", ""))
            or not re.fullmatch(r"[a-f0-9]{64}", data.get("projection_id", ""))
            or not isinstance(data.get("courses"), int)
            or data["courses"] < 1
        ):
            raise ValueError("Deployment requires a complete, pinned dataset release")
        return cls(data["revision"], data["projection_id"], data["courses"])


def worker_state(account: str, token: str, worker: str) -> dict[str, str] | None:
    response = requests.get(
        f"https://api.cloudflare.com/client/v4/accounts/{account}/workers/scripts/{worker}/settings",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    data = response.json()
    if data.get("success") is not True:
        raise RuntimeError("Cloudflare could not read the current Worker settings")
    names = {"DATA_PROJECTION", "SITE_COMMIT"}
    return {
        binding["name"]: binding.get("text", binding.get("id"))
        for binding in data["result"]["bindings"]
        if (binding.get("name") in names and "text" in binding)
        or binding.get("type") == "d1"
    }


def wrangler(config: Path, *args: str, capture: bool = False) -> str:
    result = subprocess.run(
        ["bun", "x", "--no-install", "wrangler", "--config", str(config), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout or ""


def verify_database(output: str, release: Release) -> Any:
    results = json.loads(output)
    if not results or results[0].get("success") is False:
        raise ValueError("D1 verification failed")
    row = results[0]["results"][0]
    status = json.loads(row["status"])
    if (
        row["ready"] != "true"
        or row["courses"] != release.courses
        or status.get("projection_id") != release.projection
        or status.get("revision") != release.revision
    ):
        raise ValueError("Database does not match the built release")
    return results


def current_commit(commit: str) -> bool:
    """Check main after acquiring the deployment lock, before any production writes."""
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not repository:
        return True
    response = requests.get(
        f"https://api.github.com/repos/{repository}/commits/main",
        headers={
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "Cache-Control": "no-cache",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["sha"] == commit


def deploy(config: Path, site: Path, first: bool = False) -> None:
    release = Release.read(site / "status.json")
    settings = json.loads(config.read_text())
    worker = settings["name"]
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", worker):
        raise ValueError("Invalid Worker name")
    databases = settings["d1_databases"]
    if len(databases) != 1 or databases[0]["binding"] != "DB":
        raise ValueError("Configure one D1 database with binding DB")
    account = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    token = os.environ["CLOUDFLARE_API_TOKEN"]
    if not re.fullmatch(r"[a-fA-F0-9]{32}", account) or not token:
        raise ValueError("Set valid Cloudflare account credentials")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    if not current_commit(commit):
        print(f"Skipping superseded release {commit}", flush=True)
        return
    state = worker_state(account, token, worker)
    if state is None and not first:
        raise ValueError("Worker does not exist; enable first deployment explicitly")
    reuse = database_matches(config, release)
    print(f"Release {release.revision}: import={not reuse}", flush=True)
    if not reuse:
        parts = sorted((site / "sql").glob("*.sql"))
        if not parts:
            raise ValueError("No dataset SQL import files found")
        # This precedes every destructive import statement. Requests fail closed
        # while ready is false/missing or the database belongs to another release.
        wrangler(
            config,
            "d1",
            "execute",
            "DB",
            "--remote",
            "--command",
            "CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT); "
            "INSERT OR REPLACE INTO metadata VALUES('ready','false');",
        )
        for part in parts:
            wrangler(config, "d1", "execute", "DB", "--remote", "--file", str(part))
    output = wrangler(
        config,
        "d1",
        "execute",
        "DB",
        "--remote",
        "--json",
        "--command",
        "SELECT (SELECT value FROM metadata WHERE key='ready') ready, "
        "(SELECT value FROM metadata WHERE key='status') status, "
        "(SELECT count(*) FROM courses) courses",
        capture=True,
    )
    report = verify_database(output, release)
    (site / "d1-check.json").write_text(json.dumps(report, indent=2) + "\n")
    if worker_state(account, token, worker) != state:
        raise RuntimeError("Worker changed during preparation; refusing to replace it")
    wrangler(
        config,
        "d1",
        "execute",
        "DB",
        "--remote",
        "--command",
        f"INSERT OR IGNORE INTO metadata VALUES('serving','{uuid4().hex}');",
    )
    wrangler(
        config,
        "deploy",
        "--var",
        f"SITE_COMMIT:{commit}",
        "--var",
        f"DATA_PROJECTION:{release.projection}",
        "--var",
        f"DEPLOYED_AT:{datetime.now(timezone.utc).isoformat()}",
    )
    if output_path := os.environ.get("GITHUB_OUTPUT"):
        with Path(output_path).open("a") as output_file:
            output_file.write("deployed=true\n")


def database_matches(config: Path, release: Release) -> bool:
    # Inspect the database itself so a retry after failed Worker publication can
    # reuse an already verified import, even if the live Worker is still older.
    output = wrangler(
        config,
        "d1",
        "execute",
        "DB",
        "--remote",
        "--json",
        "--command",
        "SELECT count(*) tables FROM sqlite_master WHERE type='table' AND name IN ('metadata','courses')",
        capture=True,
    )
    if json.loads(output)[0]["results"][0]["tables"] != 2:
        return False
    output = wrangler(
        config,
        "d1",
        "execute",
        "DB",
        "--remote",
        "--json",
        "--command",
        "SELECT (SELECT value FROM metadata WHERE key='ready') ready, "
        "(SELECT value FROM metadata WHERE key='status') status, "
        "(SELECT count(*) FROM courses) courses",
        capture=True,
    )
    try:
        verify_database(output, release)
        return True
    except (ValueError, TypeError, KeyError, IndexError):
        return False
