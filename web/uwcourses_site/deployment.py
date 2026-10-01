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
import sys
import time
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
    try:
        result = subprocess.run(
            ["bun", "x", "--no-install", "wrangler", "--config", str(config), *args],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as failure:
        print(failure.stdout or "", end="", flush=True)
        print(failure.stderr or "", end="", file=sys.stderr, flush=True)
        raise
    if not capture:
        print(result.stdout or "", end="", flush=True)
    print(result.stderr or "", end="", file=sys.stderr, flush=True)
    return result.stdout or ""


def cancelled_import(failure: subprocess.CalledProcessError) -> bool:
    output = (failure.stdout or "") + (failure.stderr or "")
    return "Cancelled due to no poll() received" in output


def import_part(config: Path, part: Path) -> None:
    delays = (2, 5, 10)
    for attempt in range(len(delays) + 1):
        try:
            wrangler(config, "d1", "execute", "DB", "--remote", "--file", str(part))
            return
        except subprocess.CalledProcessError as failure:
            # D1 explicitly cancels and rolls back this file. A lost response or
            # arbitrary SQL failure does not establish that replay is safe.
            if not cancelled_import(failure) or attempt == len(delays):
                raise
            delay = delays[attempt]
            print(
                f"D1 cancelled {part.name}; retry {attempt + 1}/{len(delays)} "
                f"in {delay}s",
                flush=True,
            )
            time.sleep(delay)


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


def database_report(config: Path) -> str | None:
    output = wrangler(
        config,
        "d1",
        "execute",
        "DB",
        "--remote",
        "--json",
        "--command",
        "SELECT count(*) tables FROM sqlite_master WHERE type='table' "
        "AND name IN ('metadata','courses')",
        capture=True,
    )
    if json.loads(output)[0]["results"][0]["tables"] != 2:
        return None
    return wrangler(
        config,
        "d1",
        "execute",
        "DB",
        "--remote",
        "--json",
        "--command",
        "SELECT (SELECT value FROM metadata WHERE key='ready') ready, "
        "(SELECT value FROM metadata WHERE key='status') status, "
        "(SELECT value FROM metadata WHERE key='serving') serving, "
        "(SELECT count(*) FROM courses) courses",
        capture=True,
    )


@dataclass(frozen=True)
class PublishedDatabase:
    status: str
    courses: int
    serving: str

    @classmethod
    def read(cls, report: str) -> "PublishedDatabase":
        results = json.loads(report)
        if not results or results[0].get("success") is not True:
            raise ValueError("D1 state could not be verified")
        row = results[0]["results"][0]
        status = json.loads(row["status"])
        if (
            row["courses"] < 1
            or row["courses"] != status.get("courses")
            or not re.fullmatch(r"[a-f0-9]{32}", row.get("serving") or "")
        ):
            raise ValueError("Published database is incomplete")
        return cls(row["status"], row["courses"], row["serving"])


def published_database(
    config: Path, state: dict[str, str] | None
) -> PublishedDatabase | None:
    if state is None or not re.fullmatch(
        r"[a-f0-9]{64}", state.get("DATA_PROJECTION") or ""
    ):
        return None
    settings = json.loads(config.read_text())
    if state.get("DB") != settings["d1_databases"][0]["database_id"]:
        return None
    report = database_report(config)
    if report is None:
        return None
    try:
        snapshot = PublishedDatabase.read(report)
        if json.loads(snapshot.status).get("projection_id") == state.get(
            "DATA_PROJECTION"
        ):
            return snapshot
    except (ValueError, TypeError, KeyError, IndexError):
        pass
    return None


def restore_readiness(config: Path, snapshot: PublishedDatabase) -> None:
    report = database_report(config)
    if report is None or PublishedDatabase.read(report) != snapshot:
        raise ValueError("Previous database changed; search remains unavailable")

    def quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    wrangler(
        config,
        "d1",
        "execute",
        "DB",
        "--remote",
        "--command",
        "UPDATE metadata SET value='true' WHERE key='ready' AND value='false' "
        f"AND (SELECT value FROM metadata WHERE key='status')={quote(snapshot.status)} "
        f"AND (SELECT value FROM metadata WHERE key='serving')={quote(snapshot.serving)} "
        f"AND (SELECT count(*) FROM courses)={snapshot.courses};",
    )
    report = database_report(config)
    if (
        report is None
        or PublishedDatabase.read(report) != snapshot
        or json.loads(report)[0]["results"][0]["ready"] != "true"
    ):
        raise ValueError("Previous database readiness could not be restored")
    print("Restored search for the verified previous release", flush=True)


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
        previous = published_database(config, state)
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
        for index, part in enumerate(parts):
            try:
                import_part(config, part)
            except subprocess.CalledProcessError as failure:
                if index == 0 and previous and cancelled_import(failure):
                    try:
                        if worker_state(account, token, worker) != state:
                            raise RuntimeError(
                                "Worker changed; refusing readiness recovery"
                            )
                        restore_readiness(config, previous)
                    except Exception as recovery:
                        print(f"Readiness recovery failed: {recovery}", file=sys.stderr)
                raise
    output = database_report(config)
    if output is None:
        raise ValueError("Imported database tables are missing")
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
    output = database_report(config)
    if output is None:
        return False
    try:
        verify_database(output, release)
        return True
    except (ValueError, TypeError, KeyError, IndexError):
        return False
