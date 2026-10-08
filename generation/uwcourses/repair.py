"""Checkpointed repair jobs using native assistant/validator conversation turns."""

import json

from sqlalchemy.dialects.sqlite import insert

from .schema import jobs as job_table, results
from sqlalchemy import select


from .models import canonical, digest
from .profiles import load_profile
from .store import now
from .agents import ORCHESTRATOR, native_prompt


def create_repair(
    jobs,
    parent_id,
    profiles,
    profile_name,
    limit=20,
    course_ids=None,
    turns=3,
    task_path=None,
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
    for row in jobs.db.execute(
        select(results)
        .where(results.c.job_id == parent_id)
        .order_by(results.c.course_id)
    ):
        output = json.loads(row["output_json"])
        if any(
            section.get("status") == "invalid"
            for section in output.get("sections", {}).values()
        ):
            rows.append(dict(row))
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
        "repair_parent_results_hash": digest(
            [(r["course_id"], r["output_json"]) for r in rows]
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
