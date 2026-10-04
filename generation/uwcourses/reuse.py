"""Explicit, evidence-checked section reuse across source snapshots."""

import copy
import json
import jsonschema

from .course_context import CourseContext, CourseLookup
from sqlalchemy import select
from .schema import results

from .models import digest
from .store import Store
from .unified import validate_section
from .requirements import ambiguous_semicolons

FACT_FIELDS = (
    "course_id",
    "course_reference",
    "title",
    "description",
    "requirements_text",
    "linked_courses",
)


def facts(value):
    return {key: value.get(key) for key in FACT_FIELDS} if value is not None else None


class ReuseIndex:
    def __init__(self, jobs, job_ids, context, task, profile):
        self.context, self.task = context, task
        self.rows, self.contexts = {}, {}
        self.jobs = {}
        source = Store(jobs.root, readonly=True)
        try:
            selected = [jobs.status(key) for key in set(job_ids)]
            for job in sorted(selected, key=lambda j: (j["created_at"], j["job_id"])):
                spec = json.loads(job["spec_json"])
                if (
                    job["status"] != "complete"
                    or spec["profile"]["model"] != profile.model
                    or spec["profile"]["revision"] != profile.revision
                ):
                    raise ValueError(
                        "Reuse requires completed jobs using the same pinned model"
                    )
                run = job["source_run"]
                if run not in self.contexts:
                    self.contexts[run] = CourseContext(source, run)
                self.jobs[job["job_id"]] = (job, spec)
                for row in jobs.db.execute(
                    select(
                        results.c.course_id, results.c.output_json, results.c.status
                    ).where(results.c.job_id == job["job_id"]),
                ):
                    if row["status"] != "complete" or not row["output_json"]:
                        raise ValueError("Reuse job has incomplete outputs")
                    self.rows[row["course_id"]] = (job["job_id"], row["output_json"])
        finally:
            source.close()

    def seed(self, key):
        if key not in self.rows:
            return None
        job_id, raw = self.rows[key]
        job, spec = self.jobs[job_id]
        previous = json.loads(raw)
        old = self.contexts[job["source_run"]]
        root = self.context.get(key)
        if facts(old.get(key)) != facts(root):
            return None
        provenance = previous.get("provenance", {})
        dependencies = set(provenance.get("dependencies", {}))
        dependencies.update(
            c["course_id"]
            for c in provenance.get("tool_calls", [])
            if c.get("tool") == "get_course"
        )
        if any(facts(old.get(k)) != facts(self.context.get(k)) for k in dependencies):
            return None
        lookup = CourseLookup(self.context, key, **self.task.get("tool_limits", {}))
        try:
            for call in provenance.get("tool_calls", []):
                if call.get("tool") == "get_course":
                    lookup.get_course(call["course_id"], call["from_course"])
            sections, origins = {}, {}
            for name in ("search_profile", "requirements"):
                section = previous.get("sections", {}).get(name, {})
                if (
                    section.get("status") not in {"valid", "needs_review"}
                    or section.get("value") is None
                ):
                    continue
                if name == "requirements" and ambiguous_semicolons(
                    root["requirements_text"]
                ):
                    # Reinterpret old fallbacks and potentially guessed AND trees.
                    continue
                try:
                    sections[name] = validate_section(
                        name, section["value"], self.task, root, lookup
                    )
                except (ValueError, KeyError, TypeError, jsonschema.ValidationError):
                    continue
                origins[name] = {
                    "job_id": job_id,
                    "source_run": job["source_run"],
                    "output_hash": digest(previous),
                    "model": previous["model"],
                    "model_revision": previous["model_revision"],
                    "task_version": spec["task"]["version"],
                    "section_hash": digest(section),
                    "validation_policy": "source-aware-v1",
                    "evidence_fingerprints": {
                        k: digest(facts(self.context.get(k)))
                        for k in sorted(dependencies | {key})
                    },
                }
        except (ValueError, KeyError):
            return None
        if not sections:
            return None
        for name in ("search_profile", "requirements", "student_experience"):
            sections.setdefault(
                name,
                {
                    "status": "invalid",
                    "value": None,
                    "candidate": None,
                    "error": "Regenerate from the current source evidence",
                },
            )
        if not root["reviews"]:
            origins["student_experience"] = {
                "kind": "deterministic_no_reviews",
                "input_hash": digest(root),
            }
            sections["student_experience"] = {
                "status": "insufficient_evidence",
                "value": {"status": "insufficient_evidence", "themes": []},
                "error": None,
            }
        return {
            "job_id": job_id,
            "section_origins": origins,
            "output": {
                "sections": copy.deepcopy(sections),
                "provenance": {
                    "dependencies": {
                        k: self.context.fingerprint(k) for k in dependencies
                    },
                    "tool_calls": lookup.trace,
                },
            },
        }
