"""Read-only, bounded-memory progress and quality reports for enrichment jobs."""

from collections import Counter, defaultdict
from contextlib import closing
import json
from pathlib import Path

from .database import Database


def report(root, job_id):
    with closing(
        Database(Path(root) / "processing.sqlite", readonly=True, timeout=30)
    ) as db:
        # One consistent WAL snapshot while the worker continues checkpointing.
        db.execute("BEGIN")
        job = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if job is None:
            raise ValueError("Unknown enrichment job")
        spec = json.loads(job["spec_json"])
        counts, failures, tokens = Counter(), Counter(), Counter()
        sections = defaultdict(Counter)
        recovery_courses = retained = changed = 0
        examples = []
        for row in db.execute("SELECT * FROM results WHERE job_id=?", (job_id,)):
            counts[row["status"]] += 1
            if not row["output_json"]:
                if row["status"] == "failed":
                    failures["worker_error"] += 1
                continue
            output = json.loads(row["output_json"])
            provenance = output.get("provenance", {})
            recovery_courses += bool(provenance.get("recovery_events"))
            error = provenance.get("request_error")
            if error:
                kind = (
                    "context_window"
                    if "maximum context length" in error
                    else "token_limit"
                    if "Model token limit" in error
                    else "validation_retry_limit"
                    if "output retries" in error
                    else "request_or_tool_budget"
                    if "limit" in error.lower()
                    else "inference_error"
                )
                failures[kind] += 1
            for key, value in json.loads(row["usage_json"] or "{}").items():
                if isinstance(value, (int, float)):
                    tokens[key] += value
            parent = (
                json.loads(row["input_json"]).get("repair_seed", {}).get("output", {})
            )
            for name, section in output.get("sections", {}).items():
                sections[name][section["status"]] += 1
                previous = parent.get("sections", {}).get(name)
                if previous and previous["status"] != "invalid":
                    retained += 1
                    changed += section != previous
                if section["status"] == "invalid" and len(examples) < 10:
                    examples.append({"course_id": row["course_id"], "section": name})
        return {
            "job_id": job_id,
            "status": job["status"],
            "source_run": job["source_run"],
            "worker_version": spec.get("worker_version"),
            "counts": dict(counts),
            "sections": {name: dict(values) for name, values in sections.items()},
            "failure_categories": dict(failures),
            "recovery_courses": recovery_courses,
            "retained_sections_checked": retained,
            "changed_retained_sections": changed,
            "recorded_usage": dict(tokens),
            "invalid_examples": examples,
        }
