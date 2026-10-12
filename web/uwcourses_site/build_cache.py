"""Exact-input website caches; never scrape, infer, or publish to Hugging Face."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from uuid import uuid4

import requests

ROOT = Path(__file__).resolve().parents[2]
STAGES = {
    "import": ROOT / ".site/import",
    "documents": ROOT / ".site/documents",
    "social": ROOT / ".site/social",
    "browser": ROOT / ".site/browser-state",
}
PLAN = ROOT / ".site/plan.json"
RUNTIMES = "cache-v1:python3.12:node25:bun1.4.0"


def fingerprint(patterns, parent="", root=ROOT):
    digest = hashlib.sha256((RUNTIMES + parent).encode())
    files = sorted(
        {p for pattern in patterns for p in root.glob(pattern) if p.is_file()}
    )
    if not files:
        raise ValueError("No cache inputs matched")
    for path in files:
        digest.update(str(path.relative_to(root)).encode() + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def keys(revision, root=ROOT):
    imported = fingerprint(
        [
            "web/uwcourses_site/importer.py",
            "web/uwcourses_site/discovery.py",
            "web/uwcourses_site/campus.py",
            "web/uwcourses_site/instructor_stats.py",
            "web/uwcourses_site/*.json",
            "uv.lock",
            "pyproject.toml",
        ],
        revision,
        root,
    )
    documents = fingerprint(
        [
            "src/lib/**/*.ts",
            "web/generate-data.ts",
            "web/data-context.ts",
            "web/data.config.ts",
            "bun.lock",
        ],
        imported,
        root,
    )
    return {
        "import": imported,
        "documents": documents,
        "social": fingerprint(
            ["web/*social*", "static/fonts/*", "static/uwcourses-logo.svg", "bun.lock"],
            documents,
            root,
        ),
        "browser": fingerprint(
            ["web/tests/browser/setup.ts", "wrangler.json", "bun.lock"], imported, root
        ),
    }


def outputs(values):
    if target := os.environ.get("GITHUB_OUTPUT"):
        with open(target, "a") as f:
            for key, value in values.items():
                f.write(
                    f"{key}={str(value).lower() if isinstance(value, bool) else value}\n"
                )
    print(json.dumps(values), flush=True)


def resolve(revision=None):
    if not revision:
        from huggingface_hub import HfApi
        from .importer import REPO

        revision = HfApi().dataset_info(REPO, revision="main").sha
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("Expected an exact HF commit")
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    changed = True
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule":
        try:
            response = requests.get(
                "https://uwcourses.com/api/status",
                headers={"Cache-Control": "no-cache"},
                timeout=30,
            )
            response.raise_for_status()
            deployed = response.json()
            if not isinstance(deployed, dict):
                raise ValueError("Invalid deployed status")
            changed = (
                deployed.get("revision") != revision
                or deployed.get("site_commit") != commit
            )
            if not changed:
                response = requests.get(
                    "https://uwcourses.com/api/suggest",
                    params={"q": "math", "revision": revision, "_probe": uuid4().hex},
                    headers={"Cache-Control": "no-cache"},
                    timeout=30,
                )
                response.raise_for_status()
                suggestions = response.json()
                changed = (
                    not isinstance(suggestions, dict)
                    or suggestions.get("revision") != revision
                    or not suggestions.get("items")
                )
        except (requests.RequestException, ValueError):
            # A missing/unhealthy deployment must not suppress a rebuild.
            changed = True
    plan = {"revision": revision, "commit": commit, "keys": keys(revision)}
    PLAN.parent.mkdir(parents=True, exist_ok=True)
    PLAN.write_text(json.dumps(plan, indent=2) + "\n")
    outputs(
        {
            "revision": revision,
            "changed": changed,
            **{f"{stage}_key": key for stage, key in plan["keys"].items()},
        }
    )


def inventory(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != ".cache-manifest.json":
            digest = hashlib.sha256()
            with path.open("rb") as f:
                for block in iter(lambda: f.read(1024 * 1024), b""):
                    digest.update(block)
            result[str(path.relative_to(root))] = digest.hexdigest()
    return result


def seal(stage):
    plan = json.loads(PLAN.read_text())
    root = STAGES[stage]
    if stage == "import":
        status = json.loads((root / "status.json").read_text())
        if (
            status.get("revision") != plan["revision"]
            or status.get("limited") is not False
        ):
            raise ValueError("Import does not match the resolved dataset")
    files = inventory(root)
    if not files:
        raise ValueError(f"Empty {stage} cache")
    manifest = {
        "version": 1,
        "key": plan["keys"][stage],
        "revision": plan["revision"],
        "files": files,
    }
    (root / ".cache-manifest.json").write_text(json.dumps(manifest) + "\n")


def valid(stage):
    try:
        plan = json.loads(PLAN.read_text())
        root = STAGES[stage]
        manifest = json.loads((root / ".cache-manifest.json").read_text())
        return (
            manifest["version"] == 1
            and manifest["key"] == plan["keys"][stage]
            and manifest["revision"] == plan["revision"]
            and bool(manifest["files"])
            and manifest["files"] == inventory(root)
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False
