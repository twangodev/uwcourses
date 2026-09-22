"""Typed public Parquet datasets with immutable provenance."""

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

import pyarrow as pa
import pyarrow.parquet as pq

from .review_data import (
    SCHEMA as REVIEW_SCHEMA,
    DESCRIPTION as REVIEW_DESCRIPTION,
    review_rows,
)

from .models import canonical, digest
from .identities import catalog_identities
from .dataset_shape import (
    SCHEMAS as SHAPE_SCHEMAS,
    DESCRIPTIONS as SHAPE_DESCRIPTIONS,
    write_shape,
)

PUBLIC_VERSION = 6
GRADE_FIELDS = (
    "a ab b bc c d f satisfactory unsatisfactory credit no_credit passed "
    "incomplete no_work not_reported other total"
).split()
TEXT = pa.string()
STRINGS = pa.list_(TEXT)
TIME = pa.timestamp("us", tz="UTC")
CATALOG_FIELDS = [
    ("course_id", TEXT),
    ("course_uid", TEXT),
    ("catalog_version_id", TEXT),
    ("course_number", pa.int64()),
    ("subjects", STRINGS),
    ("title", TEXT),
    ("description", TEXT),
    ("requirements_text", TEXT),
]
OBSERVATION_FIELDS = [("run_id", TEXT), ("semester", TEXT), ("observed_at", TIME)]
SCHEMAS = {
    "llm_traces": pa.schema(
        [
            ("job_id", TEXT),
            ("run_id", TEXT),
            ("course_id", TEXT),
            ("course_uid", TEXT),
            ("output_id", TEXT),
            ("model", TEXT),
            ("model_revision", TEXT),
            ("created_at", TIME),
            ("selected_for_release", pa.bool_()),
            ("has_conversation", pa.bool_()),
            ("job_spec_json", TEXT),
            ("output_json", TEXT),
            ("usage_json", TEXT),
        ]
    ),
    "catalog_versions": pa.schema(CATALOG_FIELDS),
    "courses_history": pa.schema(
        OBSERVATION_FIELDS + [("record_version_id", TEXT)] + CATALOG_FIELDS
    ),
    "courses_current": pa.schema(
        OBSERVATION_FIELDS
        + [("record_version_id", TEXT)]
        + CATALOG_FIELDS
        + [
            ("credits_min", pa.float64()),
            ("credits_max", pa.float64()),
            ("credit_offering_ids", STRINGS),
            ("llm_job_id", TEXT),
            ("llm_output_id", TEXT),
            ("llm_model", TEXT),
            ("llm_model_revision", TEXT),
            ("llm_task_version", TEXT),
            ("llm_search_status", TEXT),
            ("llm_summary", TEXT),
            ("llm_topics", STRINGS),
            ("llm_skills", STRINGS),
            ("llm_assumed_background", STRINGS),
            ("llm_search_phrases", STRINGS),
            ("llm_requirements_status", TEXT),
            ("llm_requirements_ast_json", TEXT),
            ("llm_student_summary_status", TEXT),
            ("llm_student_summary_json", TEXT),
            ("llm_experience_status", TEXT),
            ("llm_experience_json", TEXT),
            ("designations", STRINGS),
        ]
    ),
    "grades_latest": pa.schema(
        OBSERVATION_FIELDS
        + [
            ("course_id", TEXT),
            ("course_uid", TEXT),
            ("term_id", TEXT),
            ("term_name", TEXT),
            ("instructors", STRINGS),
        ]
        + [(name, pa.int64()) for name in GRADE_FIELDS]
    ),
    "offerings_current": pa.schema(
        OBSERVATION_FIELDS
        + [
            ("offering_id", TEXT),
            ("course_id", TEXT),
            ("course_uid", TEXT),
            ("term_id", TEXT),
            ("source_course_id", TEXT),
            ("source_subject_id", TEXT),
            ("title", TEXT),
            ("credits_min", pa.float64()),
            ("credits_max", pa.float64()),
            ("typically_offered", TEXT),
        ]
    ),
}
DESCRIPTIONS = {
    "llm_traces": "One row per archived job/course output, including unselected experiments. output_json preserves recorded model thinking, native conversations, tools, validator feedback, truncation recovery traces, rejected candidates and final sections. job_spec_json records task and inference settings. Older jobs may lack a conversation; missing traces are not reconstructed. Join courses through run_id/course_id and current outputs through llm_output_id. These are model-generated traces, not authoritative course facts.",
    "courses_current": "One row per course in the selected source snapshot. Credits come from matched current enrollment offerings; null means unavailable. LLM fields use the newest explicitly selected output per course (created_at, job_id); invalid sections never become search text or usable ASTs.",
    "courses_history": "One row per observed course per source run, with directly readable catalog fields. This is observation history, not inferred validity intervals or one row per semester. record_version_id links to the complete archival record.",
    "catalog_versions": "Distinct catalog projections: course identity, subjects, number, title, description, and source requirement text. Parsed trees, grades, similar courses and term activity do not change this ID. Original full records remain in the archive.",
    "grades_latest": "One row per course and grading term, choosing the latest observed distribution across included snapshots (observed_at, run_id). semester is the observation semester; term_id is the grading semester. Counts are not duplicated for repeated scrapes. Cross-listed course aliases may still overlap; do not interpret a sum across courses as distinct students. Missing counts remain null.",
    "offerings_current": "One row per enrollment offering in the selected source snapshot. Unmatched course_id stays null. This is a schedule snapshot, not live enrollment availability.",
}


SCHEMAS["rmp_reviews"] = REVIEW_SCHEMA
DESCRIPTIONS["rmp_reviews"] = REVIEW_DESCRIPTION
SCHEMAS.update(SHAPE_SCHEMAS)
DESCRIPTIONS.update(SHAPE_DESCRIPTIONS)


def timestamp(value):
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def json_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=json_value,
        )
    )


def catalog_record(course_id, record):
    prerequisites = record.get("prerequisites") or {}
    text = (
        prerequisites.get("prerequisites_text")
        if isinstance(prerequisites, dict)
        else None
    )
    fields = {
        "course_id": course_id,
        "course_number": record["course_reference"]["course_number"],
        "subjects": sorted(record["course_reference"]["subjects"]),
        "title": record["course_title"],
        "description": record["description"],
        "requirements_text": text,
    }
    return {**fields, "catalog_version_id": digest(fields)}


def write_rows(path, schema, rows, max_text_bytes=None):
    count, batch, text_bytes = 0, [], 0
    with pq.ParquetWriter(
        path, schema, compression="zstd", write_page_index=True
    ) as writer:
        for row in rows:
            row_bytes = (
                sum(
                    len(value.encode("utf-8"))
                    for value in row.values()
                    if isinstance(value, str)
                )
                if max_text_bytes is not None
                else 0
            )
            if (
                batch
                and max_text_bytes is not None
                and text_bytes + row_bytes > max_text_bytes
            ):
                writer.write_table(pa.Table.from_pylist(batch, schema=schema))
                count += len(batch)
                batch, text_bytes = [], 0
            batch.append(row)
            text_bytes += row_bytes
            if len(batch) == 4096:
                writer.write_table(pa.Table.from_pylist(batch, schema=schema))
                count += len(batch)
                batch, text_bytes = [], 0
        if batch:
            writer.write_table(pa.Table.from_pylist(batch, schema=schema))
            count += len(batch)
    if pq.read_metadata(path).num_rows != count:
        raise ValueError(f"Public row count mismatch: {path.name}")
    return count


def selected_enrichments(db):
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='current_course_enrichments'"
    ).fetchone():
        return {}
    # Deliberate selection wins; within it, the newest job wins as a whole.
    return {
        row["course_id"]: enrich_fields(row)
        for row in db.execute("""SELECT e.*,j.created_at,o.output_id,o.model,o.model_revision
            FROM current_course_enrichments e JOIN enrichment_jobs j USING(job_id)
            JOIN course_enrichment_runs b USING(job_id,run_id,course_id)
            JOIN enrichment_outputs o USING(output_id) ORDER BY j.created_at,j.job_id""")
    }


def enrich_fields(row):
    result = {
        "llm_search_status": "not_generated",
        "llm_requirements_status": "not_generated",
        "llm_experience_status": "not_generated",
        "llm_student_summary_status": "not_generated",
        **{
            key: []
            for key in (
                "llm_topics",
                "llm_skills",
                "llm_assumed_background",
                "llm_search_phrases",
            )
        },
    }
    if row is None:
        return result
    output = json.loads(row["output_json"])
    result.update(
        llm_job_id=row["job_id"],
        llm_output_id=row["output_id"],
        llm_model=row["model"],
        llm_model_revision=row["model_revision"],
        llm_task_version=str(output["task_version"])
        if output.get("task_version") is not None
        else None,
    )
    sections = output.get("sections", {})
    student = sections.get("student_summary", {})
    result["llm_student_summary_status"] = student.get("status", "not_generated")
    if student.get("status") == "valid" and student.get("value"):
        result["llm_student_summary_json"] = canonical(student["value"])
    for name, field in [
        ("search_profile", "search"),
        ("requirements", "requirements"),
        ("student_experience", "experience"),
    ]:
        section = sections.get(name, {})
        result[f"llm_{field}_status"] = section.get("status", "not_generated")
        value = section.get("value")
        if name == "requirements":
            if section.get("status") in {"valid", "needs_review"} and value:
                result["llm_requirements_ast_json"] = canonical(value)
            continue
        if section.get("status") != "valid" or value is None:
            continue
        if name == "search_profile":
            summary = value.get("summary")
            result["llm_summary"] = (
                summary.get("text") if isinstance(summary, dict) else summary
            )
            for source, target in [
                ("topics", "topics"),
                ("skills_taught", "skills"),
                ("assumed_background", "assumed_background"),
            ]:
                result["llm_" + target] = [
                    item["text"] if isinstance(item, dict) else item
                    for item in value.get(source, [])
                ]
            result["llm_search_phrases"] = value.get("search_phrases", [])
        else:
            result["llm_experience_json"] = canonical(value)
    return result


def display_requirements_ast(course):
    """Always provide a renderable root, retaining uncertainty in status and notes."""
    raw = course.get("llm_requirements_ast_json")
    value = json.loads(raw) if raw else None
    if (
        value
        and value.get("nodes")
        and value.get("root") in {node.get("id") for node in value["nodes"]}
    ):
        return canonical(value)
    text = course.get("requirements_text") or ""
    return canonical(
        {
            "status": "needs_review" if text.strip() else "none",
            "root": "source_requirements",
            "nodes": [
                {
                    "id": "source_requirements",
                    "kind": "condition",
                    "condition": text if text.strip() else "No prerequisites listed",
                    "evidence": text,
                    "course": None,
                    "children": [],
                }
            ],
            "notes": [
                "Display fallback using original requirements text; not an LLM-parsed rule."
                if text.strip()
                else "Display placeholder; the source lists no requirements."
            ],
        }
    )


def write_public(database, destination, release_id, source_run, registry_path=None):
    """Read an immutable archive; write only the public/ and serving/ subtrees."""
    destination = Path(destination)
    directory = destination / "public"
    directory.mkdir(parents=True)
    db = sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        runs = {row["run_id"]: dict(row) for row in db.execute("SELECT * FROM runs")}
        if source_run not in runs:
            raise ValueError("Selected source snapshot is missing")

        def observation(run):
            return {
                "run_id": run,
                "semester": runs[run]["semester"],
                "observed_at": timestamp(runs[run]["observed_at"]),
            }

        identities = catalog_identities(db, registry_path)
        write_json(
            directory / "course_identity_registry.json",
            {"version": 1, "assignments": identities},
        )
        counts, versions, current = {}, {}, {}

        def history():
            for row in db.execute("""SELECT s.*,v.record_json FROM course_snapshots s
                    JOIN course_versions v USING(version_id) ORDER BY s.course_id,s.run_id"""):
                record = json.loads(row["record_json"])
                catalog = catalog_record(row["course_id"], record)
                catalog["course_uid"] = identities[row["course_id"]]
                versions.setdefault(catalog["catalog_version_id"], catalog)
                value = {
                    **observation(row["run_id"]),
                    "record_version_id": row["version_id"],
                    **catalog,
                }
                if row["run_id"] == source_run:
                    current[row["course_id"]] = {
                        **value,
                        "designations": list(record.get("designations") or []),
                    }
                yield value

        counts["courses_history"] = write_rows(
            directory / "courses_history.parquet", SCHEMAS["courses_history"], history()
        )
        counts["catalog_versions"] = write_rows(
            directory / "catalog_versions.parquet",
            SCHEMAS["catalog_versions"],
            (versions[k] for k in sorted(versions)),
        )
        offers = []
        by_course = defaultdict(list)
        for row in db.execute(
            "SELECT * FROM offerings WHERE run_id=? ORDER BY offering_id", (source_run,)
        ):
            detail = json.loads(row["details_json"])
            value = {
                **observation(source_run),
                **{
                    k: row[k]
                    for k in (
                        "offering_id",
                        "course_id",
                        "term_id",
                        "source_course_id",
                        "source_subject_id",
                    )
                },
                "course_uid": identities.get(row["course_id"]),
                "title": detail.get("title"),
                "credits_min": detail.get("minimumCredits"),
                "credits_max": detail.get("maximumCredits"),
                "typically_offered": detail.get("typicallyOffered"),
            }
            offers.append(value)
            if row["course_id"] is not None:
                by_course[row["course_id"]].append(value)
        counts["offerings_current"] = write_rows(
            directory / "offerings_current.parquet",
            SCHEMAS["offerings_current"],
            offers,
        )
        enrichment = selected_enrichments(db)
        for key, course in current.items():
            related = by_course[key]
            minima = [o["credits_min"] for o in related if o["credits_min"] is not None]
            maxima = [o["credits_max"] for o in related if o["credits_max"] is not None]
            course.update(
                credits_min=min(minima) if minima else None,
                credits_max=max(maxima) if maxima else None,
                credit_offering_ids=[
                    o["offering_id"]
                    for o in related
                    if o["credits_min"] is not None or o["credits_max"] is not None
                ],
                **enrichment.get(key, enrich_fields(None)),
            )
        for course in current.values():
            course["llm_requirements_ast_json"] = display_requirements_ast(course)
            for field in SCHEMAS["courses_current"].names:
                course.setdefault(field, None)
        counts["courses_current"] = write_rows(
            directory / "courses_current.parquet",
            SCHEMAS["courses_current"],
            (current[k] for k in sorted(current)),
        )

        def grades():
            seen = set()
            for run in sorted(
                runs, key=lambda r: (timestamp(runs[r]["observed_at"]), r), reverse=True
            ):
                term_names = dict(
                    db.execute("SELECT term_id,name FROM terms WHERE run_id=?", (run,))
                )
                for row in db.execute(
                    "SELECT * FROM grades WHERE run_id=? ORDER BY course_id,term_id",
                    (run,),
                ):
                    key = (row["course_id"], row["term_id"])
                    if key in seen:
                        continue
                    seen.add(key)
                    distribution = json.loads(row["distribution_json"])
                    value = {
                        **observation(run),
                        "course_id": key[0],
                        "course_uid": identities.get(key[0]),
                        "term_id": key[1],
                        "term_name": term_names.get(key[1]),
                        "instructors": distribution.get("instructors", []),
                        **{field: distribution.get(field) for field in GRADE_FIELDS},
                    }
                    yield value

        counts["grades_latest"] = write_rows(
            directory / "grades_latest.parquet", SCHEMAS["grades_latest"], grades()
        )

        def traces():
            for row in db.execute("""
                SELECT b.job_id,b.run_id,b.course_id,b.output_id,o.model,o.model_revision,
                       j.created_at,j.spec_json,o.output_json,o.usage_json,r.is_selected AS selected
                FROM course_enrichment_runs b
                JOIN enrichment_outputs o USING(output_id)
                JOIN enrichment_jobs j USING(job_id)
                JOIN release_enrichments r USING(job_id)
                ORDER BY b.job_id,b.course_id
            """):
                value = dict(row)
                provenance = json.loads(value["output_json"]).get("provenance", {})
                value.update(
                    course_uid=identities.get(row["course_id"]),
                    created_at=timestamp(value["created_at"]),
                    selected_for_release=bool(value.pop("selected")),
                    has_conversation=bool(provenance.get("conversation")),
                    job_spec_json=value.pop("spec_json"),
                )
                yield value

        counts["llm_traces"] = write_rows(
            directory / "llm_traces.parquet",
            SCHEMAS["llm_traces"],
            traces(),
            max_text_bytes=16 * 1024 * 1024,
        )
        counts.update(write_shape(db, directory, runs, source_run, identities))
        counts["rmp_reviews"] = write_rows(
            directory / "rmp_reviews.parquet",
            REVIEW_SCHEMA,
            review_rows(db, identities),
        )
        write_json(
            directory / "schema.json",
            {
                "version": PUBLIC_VERSION,
                "tables": {
                    name: {
                        "rows": counts[name],
                        "description": DESCRIPTIONS[name],
                        "columns": {f.name: str(f.type) for f in schema},
                    }
                    for name, schema in SCHEMAS.items()
                },
            },
        )
        return counts
    finally:
        db.close()


def dataset_card(
    source_run, public_counts, archive_counts=None, repo_id="twangodev/uwcourses"
):
    import yaml
    from urllib.parse import urlencode

    configs = []
    for prefix, counts in [("public", public_counts), ("tables", archive_counts or {})]:
        for name in counts:
            config = {
                "config_name": name if prefix == "public" else "archive_" + name,
                "data_files": [{"split": "train", "path": f"{prefix}/{name}.parquet"}],
            }
            if name == "courses_current" and prefix == "public":
                config["default"] = True
            configs.append(config)
    metadata = {
        "pretty_name": "uwcourses",
        "language": ["en"],
        "multilinguality": ["monolingual"],
        "annotations_creators": ["machine-generated"],
        "task_categories": ["text-retrieval"],
        "tags": [
            "education",
            "university-of-wisconsin-madison",
            "courses",
            "grades",
            "prerequisites",
            "tabular",
            "parquet",
            "llm-generated",
        ],
        "configs": configs,
    }

    def badge(label, query):
        url = "https://img.shields.io/badge/dynamic/json?" + urlencode(
            {
                "url": f"https://huggingface.co/datasets/{repo_id}/raw/main/sync.json",
                "query": query,
                "label": label,
                "color": "red",
                "cacheSeconds": 3600,
            }
        )
        return f"![{label}]({url})"

    return (
        "---\n"
        + yaml.safe_dump(metadata, sort_keys=False)
        + "---\n\n"
        + "\n".join(
            [
                "# uwcourses",
                "",
                badge("last scan", "$.last_scan_utc"),
                badge("courses", "$.courses"),
                "",
                "UW–Madison courses, grades, instructors, student reviews, offerings, history, and LLM metadata in Parquet.",
                "",
                "Sources: [UW Guide](https://guide.wisc.edu/), [enrollment](https://public.enroll.wisc.edu/), [Madgrades](https://madgrades.com/), [Rate My Professors](https://www.ratemyprofessors.com/).",
                "",
                "```python",
                "from datasets import load_dataset",
                "",
                f'courses = load_dataset("{repo_id}", "courses_current", split="train")',
                "```",
                "",
                "See [schema](public/schema.json) for tables and columns; [manifest](manifest.json) for provenance and checksums. `llm_traces` retains recorded outputs and model revisions.",
                "",
                "This dataset is not affiliated with or endorsed by the University of Wisconsin–Madison.",
                "",
            ]
        )
    )


def export_public(root, archive_id):
    """Build a slim release from a verified archive without copying its large files."""
    from .cli import code_hash
    from .jobs import file_lock
    from .release import checksum, verify_release
    import shutil

    root = Path(root)
    if Path(archive_id).name != archive_id:
        raise ValueError("Expected a release ID, not a path")
    archive = root / "releases" / archive_id
    manifest = verify_release(archive)
    if not (archive / "coursemap.sqlite").is_file():
        raise ValueError("Public export requires a complete SQLite archive")
    source_run = manifest.get("source_run", manifest["run_id"])
    with file_lock(root / "releases.lock"):
        with sqlite3.connect(archive / "coursemap.sqlite") as identity_db:
            identity_db.row_factory = sqlite3.Row
            identities = catalog_identities(
                identity_db, root / "course-identities.json"
            )
        selection = {
            "course_identities_sha256": digest(identities),
            "source_run": source_run,
            "input_hash": manifest["input_hash"],
            "archive_release": archive_id,
            "archive_manifest_sha256": checksum(archive / "manifest.json"),
            "public_schema_version": PUBLIC_VERSION,
            "exporter_hash": code_hash(),
        }
        release_id = "public-" + digest(selection)[:24]
        target = root / "releases" / release_id
        if target.exists():
            verify_release(target)
            return target
        staging = target.with_name(target.name + ".partial")
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir()
        counts = write_public(
            archive / "coursemap.sqlite",
            staging,
            release_id,
            source_run,
            root / "course-identities.json",
        )
        (staging / "README.md").write_text(dataset_card(source_run, counts))
        write_json(
            staging / "manifest.json",
            {
                **selection,
                "run_id": release_id,
                "schema_version": manifest["schema_version"],
                "public_tables": counts,
                "files": {
                    p.relative_to(staging).as_posix(): {
                        "sha256": checksum(p),
                        "bytes": p.stat().st_size,
                    }
                    for p in sorted(staging.rglob("*"))
                    if p.is_file()
                },
            },
        )
        verify_release(staging)
        staging.replace(target)
        return target
