"""Resumable enrichment jobs with bounded HTTP workers and one result writer."""

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import contextmanager
import json
import os
from pathlib import Path

import jsonschema
import requests

from sqlalchemy import select, update, func
from sqlalchemy.dialects.sqlite import insert

from .database import Database
from .migrate import upgrade_database
from .schema import jobs, results, output_cache
from .models import canonical, digest
from .profiles import DEFAULT_REQUEST_TIMEOUT_SECONDS, load_profile
from .tasks import load_task
from .store import Store, now


WORKER_VERSION = 45


def generation_schema(schema):
    """Keep full post-validation while adapting unsupported grammar keywords."""
    import copy

    result = copy.deepcopy(schema)

    def visit(node):
        if not isinstance(node, dict):
            return
        node.pop("uniqueItems", None)
        for key in (
            "properties",
            "$defs",
            "definitions",
            "patternProperties",
            "dependentSchemas",
        ):
            for child in node.get(key, {}).values():
                visit(child)
        for key in (
            "items",
            "additionalProperties",
            "contains",
            "not",
            "if",
            "then",
            "else",
        ):
            visit(node.get(key))
        for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
            for child in node.get(key, []):
                visit(child)

    visit(result)
    return result


@contextmanager
def file_lock(path):
    import fcntl

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("This operation already has an active worker") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def check_server(profile):
    headers = {}
    if os.environ.get("COURSEMAP_INFERENCE_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["COURSEMAP_INFERENCE_API_KEY"]
    try:
        response = requests.get(
            profile["base_url"].rstrip("/") + "/models",
            headers=headers,
            timeout=(10, 30),
        )
        response.raise_for_status()
        identity = f"{profile['model']}@{profile['revision']}"
        if identity not in {row["id"] for row in response.json()["data"]}:
            raise ValueError("Inference server is not serving the pinned model")
    except requests.RequestException as exc:
        raise RuntimeError(
            "Inference server unavailable; start the pinned model and resume this job"
        ) from exc


def generate(profile, task, payload):
    from .agents import generate_generic

    if task.get("workflow") == "student_summary_v1":
        from .student_summary import generate_student

        return generate_student(profile, task, payload)
    return generate_generic(profile, task, payload)


class Jobs:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = Database(self.root / "processing.sqlite", timeout=30, wal=True)
        try:
            upgrade_database(self.db, "processing")
        except Exception:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def status(self, job):
        row = self.db.execute(select(jobs).where(jobs.c.job_id == job)).fetchone()
        if row is None:
            raise ValueError("Unknown enrichment job")
        return {
            **dict(row),
            "counts": dict(
                self.db.execute(
                    select(results.c.status, func.count())
                    .where(results.c.job_id == job)
                    .group_by(results.c.status),
                )
            ),
        }

    def create(
        self,
        source_run,
        profiles,
        profile_name,
        task_path,
        limit=100,
        course_ids=None,
        reuse_job_ids=None,
        allow_partial_reuse=False,
    ):
        if limit < 0:
            raise ValueError("limit must be nonnegative")
        profile = load_profile(profiles, profile_name)
        if profile.runner != "generate":
            raise ValueError("Enrichment requires a generation profile")
        task = load_task(task_path)
        if (
            not task.get("name")
            or not task.get("prompt")
            or not task.get("version")
            or "schema" not in task
        ):
            raise ValueError("Task must have a name, version, prompt, and JSON schema")
        jsonschema.Draft202012Validator.check_schema(task["schema"])
        if task.get("validator") not in {
            None,
            "requirements_graph_v1",
            "student_claims_v1",
        }:
            raise ValueError("Unknown task validator")
        if task.get("workflow") not in {None, "unified_v1", "student_summary_v1"}:
            raise ValueError("Unknown enrichment workflow")
        if reuse_job_ids and task.get("workflow") not in {
            "unified_v1",
            "student_summary_v1",
        }:
            raise ValueError("Reuse requires unified enrichment or student summaries")
        fields = task.get(
            "input_fields",
            ["course_reference", "course_title", "description", "prerequisites"],
        )
        source = Store(self.root, readonly=True)
        try:
            from .lifecycle import require_snapshot

            require_snapshot(source, source_run)
            courses = source.records(source_run, "courses")
            from .course_context import CourseContext

            context = (
                CourseContext(source, source_run)
                if task.get("workflow") in {"unified_v1", "student_summary_v1"}
                or course_ids
                else None
            )
            if not courses:
                raise ValueError("Snapshot has no courses")
            # Stable hash sampling avoids an alphabetically biased pilot.
            selected = sorted(courses, key=lambda key: digest(key))
            if limit:
                selected = selected[:limit]
            if course_ids:
                selected = sorted(
                    {context.resolve(key) for key in course_ids},
                    key=lambda key: key or "",
                )
                if None in selected:
                    raise ValueError(
                        "Selected course is missing or ambiguous in the snapshot"
                    )
            from .agents import ORCHESTRATOR
            from .reuse import ReuseIndex

            student = task.get("workflow") == "student_summary_v1"
            if allow_partial_reuse and not student:
                raise ValueError("Partial reuse requires the student summary workflow")
            if student:
                from .student_context import StudentContext
                from .student_summary import summary_seeds

                student_context = StudentContext(source, source_run, context)
                seeds = summary_seeds(
                    self,
                    reuse_job_ids or [],
                    source_run,
                    allow_partial=allow_partial_reuse,
                )
                if any(key not in seeds for key in selected):
                    raise ValueError(
                        "Student summaries require --reuse-job coverage for every selected course"
                    )
            reuse = (
                ReuseIndex(self, reuse_job_ids, context, task, profile)
                if reuse_job_ids and not student
                else None
            )

            spec = {
                "task": task,
                "reuse_job_ids": sorted(set(reuse_job_ids or [])),
                "profile": profile.model_dump(),
                "source_hash": source.input_hash(source_run),
                "total_courses": len(courses),
                "selected_courses": len(selected),
                "worker_version": WORKER_VERSION,
                "orchestrator": ORCHESTRATOR,
            }
            if allow_partial_reuse:
                # Freeze exactly the completed results observed at creation time.
                # Later parent progress must produce a distinct child job.
                spec["reuse_snapshot_hash"] = digest(
                    {key: seeds[key] for key in selected}
                )
            job = (
                "enrich-"
                + digest(
                    {"source_run": source_run, "spec": spec, "selection": selected}
                )[:24]
            )
            with self.db:
                self.db.execute(
                    insert(jobs)
                    .values(
                        job_id=job,
                        source_run=source_run,
                        spec_json=canonical(spec),
                        status="pending",
                        created_at=now(),
                    )
                    .on_conflict_do_nothing(index_elements=[jobs.c.job_id]),
                )
                for key in selected:
                    if student:
                        payload = {
                            "source_run": source_run,
                            "student_context": student_context.get(key),
                            "summary_seed": seeds[key],
                        }
                    elif task.get("workflow") == "unified_v1":
                        payload = context.get(key)
                    elif isinstance(fields, dict):
                        payload = {}
                        for field, path in fields.items():
                            value = courses[key]
                            for part in path.split("."):
                                value = (
                                    value.get(part) if isinstance(value, dict) else None
                                )
                            payload[field] = value
                    else:
                        payload = {field: courses[key].get(field) for field in fields}
                    if reuse is not None:
                        seed = reuse.seed(key)
                        if seed:
                            payload["reuse_seed"] = seed
                    cache_profile = profile.model_dump(
                        exclude={"base_url", "concurrency"}
                    )
                    cache_key = digest(
                        {
                            "input": payload,
                            "task": task,
                            "profile": cache_profile,
                            "worker_version": WORKER_VERSION,
                            "orchestrator": ORCHESTRATOR,
                        }
                    )
                    self.db.execute(
                        insert(results)
                        .values(
                            job_id=job,
                            course_id=key,
                            cache_key=cache_key,
                            input_json=canonical(payload),
                            status="pending",
                        )
                        .on_conflict_do_nothing(
                            index_elements=[results.c.job_id, results.c.course_id]
                        ),
                    )
            return job
        finally:
            source.close()

    def run(self, job, worker=generate, concurrency=None, request_timeout=None):
        with file_lock(self.root / "jobs" / f"{job}.lock"):
            status = self.status(job)
            if status["status"] == "complete":
                return status
            spec = json.loads(status["spec_json"])
            concurrency = (
                concurrency
                if concurrency is not None
                else spec["profile"]["concurrency"]
            )
            if not 1 <= concurrency <= 512:
                raise ValueError("Concurrency must be between 1 and 512")
            profile = dict(spec["profile"])
            if request_timeout is not None:
                if not 1 <= request_timeout <= 1800:
                    raise ValueError(
                        "Request timeout must be between 1 and 1800 seconds"
                    )
                profile["request_timeout_seconds"] = request_timeout
            if spec["worker_version"] != WORKER_VERSION:
                raise ValueError(
                    "Enrichment worker changed; create a new job with current provenance"
                )
            if worker is generate:
                check_server(spec["profile"])
            source = Store(self.root, readonly=True)
            context = None
            try:
                if source.input_hash(status["source_run"]) != spec["source_hash"]:
                    raise ValueError("Source snapshot changed")
                if spec["task"].get("workflow") == "unified_v1":
                    from .course_context import CourseContext

                    context = CourseContext(source, status["source_run"])
            finally:
                source.close()
            with self.db:
                self.db.execute(
                    update(jobs).where(jobs.c.job_id == job).values(status="running")
                )
            rows = iter(
                self.db.execute(
                    select(results)
                    .where(results.c.job_id == job, results.c.status != "complete")
                    .order_by(results.c.course_id),
                ).fetchall()
            )
            pending = {}

            def submit_next(pool):
                for row in rows:
                    cached = self.db.execute(
                        select(
                            output_cache.c.output_json, output_cache.c.usage_json
                        ).where(output_cache.c.cache_key == row["cache_key"]),
                    ).fetchone()
                    if cached and context is not None:
                        dependencies = (
                            json.loads(cached[0])
                            .get("provenance", {})
                            .get("dependencies", {})
                        )
                        if any(
                            context.fingerprint(key) != stamp
                            for key, stamp in dependencies.items()
                        ):
                            cached = None
                    if cached:
                        with self.db:
                            self.db.execute(
                                update(results)
                                .where(
                                    results.c.job_id == job,
                                    results.c.course_id == row["course_id"],
                                )
                                .values(
                                    status="complete",
                                    output_json=cached["output_json"],
                                    usage_json=cached["usage_json"],
                                    error=None,
                                ),
                            )
                        continue
                    args = [
                        profile,
                        spec["task"],
                        json.loads(row["input_json"]),
                    ]
                    selected_worker = worker
                    if context is not None and worker is generate:
                        from .agents import generate_unified

                        selected_worker = generate_unified
                        if spec["task"].get("repair_mode") == "conversation_v1":
                            from .agents import generate_repair

                            selected_worker = generate_repair
                        args.append(context)
                    pending[pool.submit(selected_worker, *args)] = row
                    return

            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                for _ in range(concurrency):
                    submit_next(pool)
                while pending:
                    done, _ = wait(pending, return_when=FIRST_COMPLETED)
                    for future in done:
                        row = pending.pop(future)
                        try:
                            value, usage = future.result()
                            if context is not None:
                                value.setdefault("provenance", {})[
                                    "generated_from_snapshot"
                                ] = status["source_run"]
                            value.setdefault("provenance", {})["client_concurrency"] = (
                                concurrency
                            )
                            value["provenance"]["request_timeout_seconds"] = (
                                profile.get(
                                    "request_timeout_seconds",
                                    DEFAULT_REQUEST_TIMEOUT_SECONDS,
                                )
                            )
                            encoded, tokens = canonical(value), canonical(usage)
                            with self.db:
                                self.db.execute(
                                    insert(output_cache)
                                    .values(
                                        cache_key=row["cache_key"],
                                        output_json=encoded,
                                        usage_json=tokens,
                                    )
                                    .on_conflict_do_update(
                                        index_elements=[output_cache.c.cache_key],
                                        set_={
                                            "output_json": encoded,
                                            "usage_json": tokens,
                                        },
                                    ),
                                )
                                self.db.execute(
                                    update(results)
                                    .where(
                                        results.c.job_id == job,
                                        results.c.course_id == row["course_id"],
                                    )
                                    .values(
                                        status="complete",
                                        output_json=encoded,
                                        usage_json=tokens,
                                        error=None,
                                        attempts=results.c.attempts + 1,
                                    ),
                                )
                        except Exception as exc:
                            error = type(exc).__name__
                            if isinstance(
                                exc, (ValueError, jsonschema.ValidationError)
                            ):
                                reason = (
                                    exc.message
                                    if isinstance(exc, jsonschema.ValidationError)
                                    else str(exc)
                                )
                                error += ": " + reason[:600]
                            with self.db:
                                self.db.execute(
                                    update(results)
                                    .where(
                                        results.c.job_id == job,
                                        results.c.course_id == row["course_id"],
                                    )
                                    .values(
                                        status="failed",
                                        error=error,
                                        attempts=results.c.attempts + 1,
                                    ),
                                )
                        submit_next(pool)
            remaining = self.db.execute(
                select(func.count())
                .select_from(results)
                .where(results.c.job_id == job, results.c.status != "complete"),
            ).fetchone()[0]
            with self.db:
                self.db.execute(
                    update(jobs)
                    .where(jobs.c.job_id == job)
                    .values(status="failed" if remaining else "complete"),
                )
            if remaining:
                raise RuntimeError(
                    f"{remaining} enrichments failed; resume {job} to retry only failed rows"
                )
            return self.status(job)

    @staticmethod
    def append_release(root, path, source_run, ids, history=None):
        from .history import export_enrichments

        export_enrichments(root, path, source_run, ids, history)
