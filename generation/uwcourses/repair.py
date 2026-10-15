"""Checkpointed repair jobs using native assistant/validator conversation turns."""

import copy
import json

import jsonschema

from sqlalchemy.dialects.sqlite import insert

from .schema import jobs as job_table, results
from sqlalchemy import select


from .models import canonical, digest
from .profiles import load_profile
from .store import now
from .agents import ORCHESTRATOR, native_prompt
from .course_context import CourseContext, CourseLookup
from .store import Store
from .unified import SECTIONS, validate_section


def revalidate_output(output, names, task, root, lookup):
    """Invalidate only sections rejected by the current validation policy."""
    result = copy.deepcopy(output)
    for name in names:
        section = result.get("sections", {}).get(name, {})
        if section.get("status") != "valid" or section.get("value") is None:
            continue
        try:
            validate_section(name, section["value"], task, root, lookup)
        except (ValueError, KeyError, TypeError, jsonschema.ValidationError) as failure:
            result["sections"][name] = {
                "status": "invalid",
                "value": None,
                "candidate": section["value"],
                "error": str(failure),
            }
    return result


def create_repair(
    jobs,
    parent_id,
    profiles,
    profile_name,
    limit=20,
    course_ids=None,
    turns=3,
    task_path=None,
    revalidate_sections=(),
):
    from .jobs import WORKER_VERSION

    if limit < 0 or not 1 <= turns <= 4:
        raise ValueError("limit must be nonnegative and turns must be between 1 and 4")
    parent = jobs.status(parent_id)
    if parent["status"] != "complete":
        raise ValueError("Repair requires a completed parent job")
    original = json.loads(parent["spec_json"])
    if original["task"].get("workflow") != "unified_v1":
        raise ValueError("Repair requires unified course enrichment")
    if set(revalidate_sections) - set(SECTIONS):
        raise ValueError("Unknown section requested for revalidation")
    profile = load_profile(profiles, profile_name)
    if profile.runner != "generate" or (profile.model, profile.revision) != (
        original["profile"]["model"],
        original["profile"]["revision"],
    ):
        raise ValueError(
            "Repair must use the same pinned generation model to retain accepted sections"
        )
    profile.thinking = True
    rows = []
    source = Store(jobs.root, readonly=True) if revalidate_sections else None
    try:
        context = CourseContext(source, parent["source_run"]) if source else None
        for saved in jobs.db.execute(
            select(results)
            .where(results.c.job_id == parent_id)
            .order_by(results.c.course_id)
        ):
            if course_ids and saved["course_id"] not in course_ids:
                continue
            row = dict(saved)
            output = json.loads(row["output_json"])
            if context:
                output = revalidate_output(
                    output,
                    revalidate_sections,
                    original["task"],
                    context.get(row["course_id"]),
                    CourseLookup(
                        context,
                        row["course_id"],
                        **original["task"].get("tool_limits", {}),
                    ),
                )
                row["parent_output_json"] = row["output_json"]
                row["output_json"] = canonical(output)
            if any(
                section.get("status") == "invalid"
                for section in output.get("sections", {}).values()
            ):
                rows.append(row)
    finally:
        if source:
            source.close()
    if course_ids:
        requested = set(course_ids)
        rows = [row for row in rows if row["course_id"] in requested]
        if {row["course_id"] for row in rows} != requested:
            raise ValueError(
                "Each requested canonical course ID must have a rejected section"
            )
    rows.sort(key=lambda row: digest(row["course_id"]))
    if limit and not course_ids:
        rows = rows[:limit]
    if not rows:
        raise ValueError("No rejected course sections selected")
    source_task = original["task"]
    if task_path is not None:
        from .tasks import load_task

        source_task = load_task(task_path)
        if (
            source_task.get("workflow") != "unified_v1"
            or source_task.get("schema") != original["task"]["schema"]
        ):
            raise ValueError(
                "Repair task must retain the parent output schema and workflow"
            )
        if not source_task.get("version") or not source_task.get("prompt"):
            raise ValueError("Repair task requires a version and prompt")
    task = {**source_task, "repair_mode": "conversation_v1", "repair_turns": turns}
    task["prompt"] = native_prompt(task)
    spec = {
        **original,
        "task": task,
        "profile": profile.model_dump(),
        "worker_version": WORKER_VERSION,
        "orchestrator": ORCHESTRATOR,
        "selected_courses": len(rows),
        "repair_parent": parent_id,
        "revalidate_sections": sorted(set(revalidate_sections)),
        "repair_parent_results_hash": digest(
            [
                (r["course_id"], r.get("parent_output_json", r["output_json"]))
                for r in rows
            ]
        ),
    }
    job = "enrich-" + digest({"source_run": parent["source_run"], "spec": spec})[:24]
    with jobs.db:
        jobs.db.execute(
            insert(job_table)
            .values(
                job_id=job,
                source_run=parent["source_run"],
                spec_json=canonical(spec),
                status="pending",
                created_at=now(),
            )
            .on_conflict_do_nothing(index_elements=[job_table.c.job_id]),
        )
        for row in rows:
            payload = json.loads(row["input_json"])
            # For chained repair jobs, replace the seed rather than nesting it.
            payload["repair_seed"] = {
                "job_id": parent_id,
                "output": json.loads(row["output_json"]),
            }
            cache_key = digest(
                {
                    "input": payload,
                    "task": task,
                    "profile": profile.model_dump(exclude={"base_url", "concurrency"}),
                    "worker_version": WORKER_VERSION,
                    "orchestrator": ORCHESTRATOR,
                }
            )
            jobs.db.execute(
                insert(results)
                .values(
                    job_id=job,
                    course_id=row["course_id"],
                    cache_key=cache_key,
                    input_json=canonical(payload),
                    status="pending",
                )
                .on_conflict_do_nothing(
                    index_elements=[results.c.job_id, results.c.course_id]
                ),
            )
    return job
