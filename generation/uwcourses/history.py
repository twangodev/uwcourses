"""Content-addressed course versions and complete released enrichment history."""

import hashlib
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from .database import Database
from .schema import archive as archive_schema, jobs, results
from .models import canonical, digest


def write_course(db, run, key, value):
    fields = (
        value["course_reference"]["course_number"],
        value["course_title"],
        value["description"],
        canonical(value["prerequisites"]),
        canonical(value),
    )
    version = digest(value)
    db.execute(
        insert(archive_schema.tables["course_versions"])
        .on_conflict_do_nothing()
        .values(
            {
                "version_id": version,
                "course_number": fields[0],
                "title": fields[1],
                "description": fields[2],
                "prerequisites_json": fields[3],
                "record_json": fields[4],
            }
        )
    )
    db.execute(
        insert(archive_schema.tables["course_snapshots"]).values(
            {"run_id": run, "course_id": key, "version_id": version}
        )
    )


def job_stamp(db, row):
    spec = json.loads(row["spec_json"])
    hasher = hashlib.sha256()
    count = 0
    for result in db.execute(
        select(
            results.c.course_id,
            results.c.status,
            results.c.output_json,
            results.c.usage_json,
        )
        .where(results.c.job_id == row["job_id"])
        .order_by(results.c.course_id),
    ):
        if result["status"] != "complete" or result["output_json"] is None:
            raise ValueError("Enrichment coverage does not match its completed job")
        hasher.update(canonical(list(result)).encode())
        hasher.update(b"\n")
        count += 1
    if count != spec["selected_courses"]:
        raise ValueError("Enrichment coverage does not match its completed job")
    return {
        "job_id": row["job_id"],
        "source_run": row["source_run"],
        "spec_hash": digest(spec),
        "results_hash": hasher.hexdigest(),
    }


def select_enrichments(root, runs, selected, current_run, include_all=True):
    """Freeze completed jobs, including a content fingerprint for release identity."""
    selected, runs = set(selected), set(runs)
    path = Path(root) / "processing.sqlite"
    if not path.exists():
        if selected:
            raise ValueError("Release requires completed enrichment jobs")
        return []
    db = Database(path, readonly=True)
    try:
        db.execute("BEGIN")
        rows = list(db.execute(select(jobs).order_by(jobs.c.job_id)))
        by_id = {row["job_id"]: row for row in rows}
        for key in selected:
            row = by_id.get(key)
            if not row or row["status"] != "complete" or row["source_run"] not in runs:
                raise ValueError(
                    "Release requires completed enrichment jobs from included snapshots"
                )
        return [
            {**job_stamp(db, row), "selected": row["job_id"] in selected}
            for row in rows
            if row["status"] == "complete"
            and row["source_run"] in runs
            and (include_all or row["job_id"] in selected)
        ]
    finally:
        db.close()


ENRICHMENT_VIEWS = [
    "CREATE VIEW course_enrichments AS SELECT b.job_id,b.run_id,b.course_id,o.output_json,o.usage_json FROM course_enrichment_runs b JOIN enrichment_outputs o USING(output_id)",
    "CREATE VIEW enrichment_sections AS SELECT b.job_id,b.course_id,s.section,s.status,o.model,o.model_revision,s.value_json,s.candidate_json,s.error FROM course_enrichment_runs b JOIN enrichment_outputs o USING(output_id) JOIN enrichment_output_sections s USING(output_id)",
    "CREATE VIEW course_enrichment_history AS SELECT b.*,r.semester,r.observed_at,c.version_id,j.task,j.created_at,o.model,o.model_revision FROM course_enrichment_runs b JOIN runs r USING(run_id) JOIN course_snapshots c USING(run_id,course_id) JOIN enrichment_jobs j USING(job_id) JOIN enrichment_outputs o USING(output_id)",
    "CREATE VIEW current_course_enrichments AS SELECT e.* FROM course_enrichments e JOIN current_courses c USING(run_id,course_id) JOIN release_enrichments s USING(job_id) WHERE s.is_selected=1",
    "CREATE VIEW current_enrichment_sections AS SELECT s.* FROM enrichment_sections s JOIN current_course_enrichments c USING(job_id,course_id)",
]


def export_enrichments(root, path, source_run, ids, history=None):
    output = Database(path)
    try:
        with output:
            return _export_enrichments(root, output, source_run, ids, history)
    finally:
        output.close()


def _export_enrichments(root, output, source_run, ids, history):
    archive_schema.create_all(
        output.connection,
        tables=[
            table
            for table in archive_schema.sorted_tables
            if table.name.startswith("enrichment_")
            or table.name in {"release_enrichments", "course_enrichment_runs"}
        ],
    )
    for statement in ENRICHMENT_VIEWS:
        output.execute(statement)
    if history is None:
        history = select_enrichments(
            root,
            [
                r[0]
                for r in output.execute(select(archive_schema.tables["runs"].c.run_id))
            ],
            ids,
            source_run,
            include_all=False,
        )
    if not history:
        return
    db = Database(Path(root) / "processing.sqlite", readonly=True)
    try:
        db.execute("BEGIN")
        for stamp in history:
            job = stamp["job_id"]
            row = db.execute(select(jobs).where(jobs.c.job_id == job)).fetchone()
            if (
                not row
                or row["status"] != "complete"
                or job_stamp(db, row)
                != {k: v for k, v in stamp.items() if k != "selected"}
            ):
                raise ValueError(
                    "Enrichment changed after release history was selected"
                )
            spec = json.loads(row["spec_json"])
            spec["profile"].pop("base_url", None)
            output.execute(
                insert(archive_schema.tables["enrichment_jobs"]).values(
                    {
                        "job_id": job,
                        "run_id": row["source_run"],
                        "task": spec["task"]["name"],
                        "spec_json": canonical(spec),
                        "selected_courses": spec["selected_courses"],
                        "total_courses": spec["total_courses"],
                        "created_at": row["created_at"],
                    }
                )
            )
            output.execute(
                insert(archive_schema.tables["release_enrichments"]).values(
                    {"job_id": job, "is_selected": int(stamp["selected"])}
                )
            )
            for result in db.execute(
                select(results)
                .where(results.c.job_id == job)
                .order_by(results.c.course_id)
            ):
                fields = (
                    spec["profile"]["model"],
                    spec["profile"]["revision"],
                    result["output_json"],
                    result["usage_json"],
                )
                identifier = digest(fields)
                output.execute(
                    insert(archive_schema.tables["enrichment_outputs"])
                    .on_conflict_do_nothing()
                    .values(
                        {
                            "output_id": identifier,
                            "model": fields[0],
                            "model_revision": fields[1],
                            "output_json": fields[2],
                            "usage_json": fields[3],
                        }
                    )
                )
                output.execute(
                    insert(archive_schema.tables["course_enrichment_runs"]).values(
                        {
                            "job_id": job,
                            "run_id": row["source_run"],
                            "course_id": result["course_id"],
                            "output_id": identifier,
                        }
                    )
                )
                for name, section in (
                    json.loads(result["output_json"]).get("sections", {}).items()
                ):
                    output.execute(
                        insert(archive_schema.tables["enrichment_output_sections"])
                        .on_conflict_do_nothing()
                        .values(
                            {
                                "output_id": identifier,
                                "section": name,
                                "status": section["status"],
                                "value_json": canonical(section["value"])
                                if section.get("value") is not None
                                else None,
                                "candidate_json": canonical(section["candidate"])
                                if section.get("candidate") is not None
                                else None,
                                "error": section.get("error"),
                            }
                        )
                    )
    finally:
        db.close()
    if output.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("Enrichment references missing course snapshots")
