"""Relational public snapshots, Parquet exports, and verified HF publication."""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import SCHEMA_VERSION
from sqlalchemy import select, literal, func
from sqlalchemy.dialects.sqlite import insert

from .database import Database
from .schema import (
    archive as archive_schema,
    runs as source_runs,
    observations as source_observations,
    artifacts as source_artifacts,
)
from .models import canonical
from .store import SOURCES


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate(store, run):
    info = store.run(run)
    if info["origin"] == "legacy":
        from .legacy import legacy_state

        state = legacy_state(store, run)
        if not state["courses"] or not state["instructors"]:
            raise ValueError("Legacy snapshot is missing core records")
        return dict(
            store.db.execute(
                select(source_observations.c.kind, func.count())
                .where(source_observations.c.run_id == run)
                .group_by(source_observations.c.kind),
            )
        )
    errors = []
    required_sources = json.loads(info["config_json"]).get("sources", list(SOURCES))
    for source in required_sources:
        if store.stage_status(run, source) != "complete":
            errors.append(f"Source {source} is incomplete")
    counts = dict(
        store.db.execute(
            select(source_observations.c.kind, func.count())
            .where(source_observations.c.run_id == run)
            .group_by(source_observations.c.kind),
        )
    )
    required_kinds = ["courses", "subjects", "terms", "grades", "offerings"]
    if "instructors" in required_sources:
        required_kinds.extend(["faculty", "ratings"])
    if "buildings" in required_sources:
        required_kinds.append("buildings")
    if json.loads(info["config_json"]).get("ratings_contract") == 1:
        from .ratings import instructor_names

        ratings = store.records(run, "ratings", "instructors")
        missing = [
            name
            for name in instructor_names(store, run)
            if not ratings.get(name, {}).get("collection_complete")
        ]
        if missing:
            errors.append(
                f"RMP collection incomplete for {len(missing)} instructor queries"
            )
    for required in required_kinds:
        if not counts.get(required):
            errors.append(f"No {required} records")
    courses = store.records(run, "courses")
    subjects = store.records(run, "subjects")
    for key, course in courses.items():
        for subject in course["course_reference"]["subjects"]:
            if subject not in subjects:
                errors.append(f"{key} references missing subject {subject}")
    if info["semester"] not in store.records(run, "terms", "enrollment"):
        errors.append("Target semester is missing")
    previous = store.db.execute(
        select(source_runs.c.run_id)
        .where(
            source_runs.c.status == "complete",
            source_runs.c.origin == "scrape",
            source_runs.c.run_id != run,
            source_runs.c.observed_at <= info["observed_at"],
            select(source_observations.c.entity_id)
            .where(
                source_observations.c.run_id == source_runs.c.run_id,
                source_observations.c.kind == "courses",
            )
            .exists(),
        )
        .order_by(source_runs.c.observed_at.desc(), source_runs.c.run_id.desc())
        .limit(1),
    ).fetchone()
    if previous:
        old = dict(
            store.db.execute(
                select(source_observations.c.kind, func.count())
                .where(source_observations.c.run_id == previous[0])
                .group_by(source_observations.c.kind),
            )
        )
        for kind in ("courses", "subjects", "grades", "faculty", "buildings"):
            if kind in required_kinds and counts.get(kind, 0) < old.get(kind, 0) * 0.9:
                errors.append(
                    f"{kind} count fell by more than 10% ({old[kind]} -> {counts.get(kind, 0)})"
                )
    if errors:
        raise ValueError("Validation failed:\n" + "\n".join(errors[:25]))
    return counts


PUBLIC_VIEWS = [
    "CREATE VIEW courses AS SELECT s.run_id,s.course_id,v.course_number,v.title,v.description,v.prerequisites_json FROM course_snapshots s JOIN course_versions v USING(version_id)",
    "CREATE VIEW course_history AS SELECT s.run_id,s.course_id,s.version_id,r.semester,r.observed_at,r.origin,r.source_revision,v.course_number,v.title,v.description,v.prerequisites_json,v.record_json FROM course_snapshots s JOIN course_versions v USING(version_id) JOIN runs r USING(run_id)",
]


def snapshot_state(store, run):
    if store.run(run)["origin"] == "legacy":
        from .legacy import legacy_state

        return legacy_state(store, run)
    # Older completed snapshots stored reconciled records in a graph artifact.
    # Read those archives without requiring the retired website generator.
    for name in ("source_state", "graph"):
        row = store.db.execute(
            select(source_artifacts.c.payload_json).where(
                source_artifacts.c.run_id == run, source_artifacts.c.name == name
            )
        ).fetchone()
        if row:
            return json.loads(row[0])
    raise ValueError("Snapshot has no reconciled source state")


def write_database(store, run, path):
    public = Database(path)
    try:
        _write_database(store, run, public)
    finally:
        public.close()


def _write_database(store, run, public):
    archive_schema.create_all(
        public.connection,
        tables=[
            table
            for table in archive_schema.sorted_tables
            if not table.name.startswith("enrichment_")
            and table.name not in {"release_enrichments", "course_enrichment_runs"}
        ],
    )
    for statement in PUBLIC_VIEWS:
        public.execute(statement)
    history = [
        row[0]
        for row in store.db.execute(
            select(source_runs.c.run_id)
            .where((source_runs.c.status == "complete") | (source_runs.c.run_id == run))
            .order_by(source_runs.c.observed_at, source_runs.c.run_id),
        )
    ]
    with public:
        for identifier in history:
            info = store.run(identifier)
            public.execute(
                insert(archive_schema.tables["runs"]).values(
                    {
                        "run_id": identifier,
                        "semester": info["semester"],
                        "observed_at": info["observed_at"],
                        "origin": info["origin"],
                        "source_revision": info["source_revision"],
                    }
                )
            )
            public.executemany(
                insert(archive_schema.tables["observations"]),
                [
                    {
                        "run_id": row["run_id"],
                        "source": row["source"],
                        "kind": row["kind"],
                        "entity_id": row["entity_id"],
                        "source_url": row["source_url"],
                        "observed_at": row["observed_at"],
                        "content_hash": row["content_hash"],
                        "payload_json": row["payload_json"],
                    }
                    for row in store.db.execute(
                        select(source_observations)
                        .where(source_observations.c.run_id == identifier)
                        .order_by(
                            source_observations.c.source,
                            source_observations.c.kind,
                            source_observations.c.entity_id,
                        ),
                    )
                ],
            )
            subjects = store.records(identifier, "subjects")
            public.executemany(
                insert(archive_schema.tables["subjects"]),
                [
                    {"run_id": identifier, "subject_id": k, "name": v["name"]}
                    for (k, v) in subjects.items()
                ],
            )
            for key, value in store.records(identifier, "courses").items():
                from .history import write_course

                write_course(public, identifier, key, value)
                public.executemany(
                    insert(archive_schema.tables["course_subjects"]),
                    [
                        {"run_id": identifier, "course_id": key, "subject_id": s}
                        for s in value["course_reference"]["subjects"]
                    ],
                )
            public.executemany(
                insert(archive_schema.tables["terms"]),
                [
                    {"run_id": identifier, "term_id": k, "name": v["name"]}
                    for (k, v) in store.records(identifier, "terms").items()
                ],
            )
            if not store.records(identifier, "courses"):
                continue  # Auxiliary history retains observations without course projections.
            state = snapshot_state(store, identifier)
            for key, value in state["instructors"].items():
                public.execute(
                    insert(archive_schema.tables["instructors"]).values(
                        {
                            "run_id": identifier,
                            "instructor_id": key,
                            "name": value["name"],
                            "email": value["email"],
                            "official_name": value["official_name"],
                            "department": value["department"],
                            "position": value["position"],
                            "details_json": canonical(value),
                        }
                    )
                )
            for key, value in state["courses"].items():
                for term, term_data in value["term_data"].items():
                    if term_data["grade_data"]:
                        public.execute(
                            insert(archive_schema.tables["grades"]).values(
                                {
                                    "run_id": identifier,
                                    "course_id": key,
                                    "term_id": term,
                                    "distribution_json": canonical(
                                        term_data["grade_data"]
                                    ),
                                }
                            )
                        )
            aliases = {
                (subject, value["course_reference"]["course_number"]): key
                for key, value in state["courses"].items()
                for subject in value["course_reference"]["subjects"]
            }
            for key, value in store.records(identifier, "offerings").items():
                hit = value["hit"]
                public.execute(
                    insert(archive_schema.tables["offerings"]).values(
                        {
                            "run_id": identifier,
                            "offering_id": key,
                            "term_id": value["term"],
                            "course_id": next(
                                (
                                    aliases[
                                        subject,
                                        value["course_reference"]["course_number"],
                                    ]
                                    for subject in value["course_reference"]["subjects"]
                                    if (
                                        subject,
                                        value["course_reference"]["course_number"],
                                    )
                                    in aliases
                                ),
                                None,
                            ),
                            "source_course_id": str(hit["courseId"]),
                            "source_subject_id": str(hit["subject"]["subjectCode"]),
                            "course_reference_json": canonical(
                                value["course_reference"]
                            ),
                            "details_json": canonical(hit),
                        }
                    )
                )
                for package in value["sections"]:
                    for section in package["sections"]:
                        sid = f"{section['type']}:{section['sectionNumber']}"
                        public.execute(
                            insert(archive_schema.tables["sections"])
                            .on_conflict_do_nothing()
                            .values(
                                {
                                    "run_id": identifier,
                                    "offering_id": key,
                                    "section_id": sid,
                                    "section_type": section["type"],
                                    "section_number": str(section["sectionNumber"]),
                                    "details_json": canonical(section),
                                }
                            )
                        )
                        from uwcourses.sanitization import sanitize_instructor_id

                        for instructor in section.get("instructors", []):
                            name = f"{instructor['name']['first']} {instructor['name']['last']}"
                            instructor_id = sanitize_instructor_id(name)
                            if instructor_id not in state["instructors"]:
                                instructor_id = None
                            public.execute(
                                insert(archive_schema.tables["section_instructors"])
                                .on_conflict_do_nothing()
                                .values(
                                    {
                                        "run_id": identifier,
                                        "offering_id": key,
                                        "section_id": sid,
                                        "instructor_name": name,
                                        "instructor_id": instructor_id,
                                    }
                                )
                            )
            for key, meetings in state["meetings"].items():
                for meeting in meetings:
                    encoded = canonical(meeting)
                    public.execute(
                        insert(archive_schema.tables["meetings"]).values(
                            {
                                "run_id": identifier,
                                "course_id": key,
                                "meeting_id": hashlib.sha256(
                                    encoded.encode()
                                ).hexdigest(),
                                "start_time": meeting["start_time"],
                                "end_time": meeting["end_time"],
                                "details_json": encoded,
                            }
                        )
                    )
            public.executemany(
                insert(archive_schema.tables["derived_artifacts"]),
                [
                    {
                        "run_id": row["run_id"],
                        "name": row["name"],
                        "input_hash": row["input_hash"],
                        "config_json": row["config_json"],
                        "payload_json": row["payload_json"],
                    }
                    for row in store.db.execute(
                        select(source_artifacts)
                        .where(source_artifacts.c.run_id == identifier)
                        .order_by(source_artifacts.c.name),
                    )
                ],
            )
        # No private run config, filesystem paths, request credentials or logs are exported.
        for table in (
            "courses",
            "subjects",
            "course_subjects",
            "terms",
            "instructors",
            "grades",
            "offerings",
            "sections",
            "section_instructors",
            "meetings",
            "observations",
            "derived_artifacts",
        ):
            public.execute(
                f"CREATE VIEW current_{table} AS SELECT * FROM {table} WHERE run_id="
                + str(
                    literal(run).compile(
                        dialect=public.connection.dialect,
                        compile_kwargs={"literal_binds": True},
                    )
                )
            )
    if public.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("Public snapshot contains broken references")
    if public.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValueError("Public snapshot failed integrity check")
    public.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    public.commit()


def write_parquet(database, directory):
    import pyarrow as pa
    from .public_data import write_rows

    directory.mkdir()
    db = sqlite3.connect(database)
    tables = [
        r[0]
        for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
    ]
    counts = {}
    for name in tables:
        columns = db.execute(f"PRAGMA table_info({name})").fetchall()
        schema = pa.schema(
            [
                (column[1], pa.int64() if column[2] == "INTEGER" else pa.string())
                for column in columns
            ]
        )
        cursor = db.execute(f"SELECT * FROM {name} ORDER BY rowid")
        # Historical graph artifacts and model traces can each be very large.
        # Bound text bytes as well as rows; retain oversized single rows intact.
        counts[name] = write_rows(
            directory / f"{name}.parquet",
            schema,
            (dict(zip(schema.names, row)) for row in cursor),
            max_text_bytes=16 * 1024 * 1024,
        )
    db.close()
    return counts


def verify_release(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    actual = {
        p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()
    }
    if actual != set(manifest["files"]) | {"manifest.json"}:
        raise ValueError("Release contains missing or unexpected files")
    for name, metadata in manifest["files"].items():
        path = directory / name
        if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError("Invalid release path")
        if (
            path.stat().st_size != metadata["bytes"]
            or checksum(path) != metadata["sha256"]
        ):
            raise ValueError(f"Release checksum mismatch: {name}")
    return manifest


def sync_metadata(manifest, source, revision, course_count):
    """Badge metadata for the source snapshot activated by a publication."""
    completed = source["completed_at"]
    return {
        "schema_version": 1,
        "source_run": source["run_id"],
        "data_revision": revision,
        "scan_started_at": source["started_at"],
        "scan_completed_at": completed,
        "last_scan_utc": datetime.fromisoformat(completed)
        .astimezone(timezone.utc)
        .strftime("%Y-%m-%d %H:%M UTC"),
        "courses": manifest.get("public_tables", {}).get(
            "courses_current", course_count
        ),
        "history_snapshots": len(manifest.get("history", [source["run_id"]])),
    }


def publish(store, run, repo_id, api=None, download=None):
    from huggingface_hub import (
        HfApi,
        CommitOperationAdd,
        CommitOperationDelete,
        hf_hub_download,
    )

    directory = store.root / "releases" / run
    manifest = verify_release(directory)
    source_run = manifest.get("source_run", run)
    if store.run(source_run)["status"] != "complete" or manifest[
        "input_hash"
    ] != store.input_hash(source_run):
        raise ValueError("Only a completed, unchanged run can be published")
    api = api or HfApi()
    download = download or hf_hub_download
    api.create_repo(repo_id=repo_id, repo_type="dataset", private=False, exist_ok=True)
    branch = f"runs/{run}"
    tag = f"release-{run}"
    expected = sorted(set(manifest["files"]) | {"manifest.json"})
    checkpoint_path = (
        store.root
        / "runs"
        / run
        / ("upload-" + hashlib.sha256(repo_id.encode()).hexdigest() + ".json")
    )
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_hash = checksum(directory / "manifest.json")
    base = api.repo_info(repo_id=repo_id, repo_type="dataset", revision="main").sha
    api.create_branch(
        repo_id=repo_id, repo_type="dataset", branch=branch, exist_ok=True
    )
    head = api.repo_info(repo_id=repo_id, repo_type="dataset", revision=branch).sha
    checkpoint = {
        "index": 0,
        "revision": head,
        "base": base,
        "manifest_hash": manifest_hash,
    }
    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text())
        if checkpoint["manifest_hash"] != manifest_hash:
            raise ValueError("Release changed after publication started")
        if checkpoint.get("complete"):
            return {"repo_id": repo_id, "revision": checkpoint["revision"], "tag": tag}
        if checkpoint["revision"] != head:
            # Commit succeeded but the process died before its checkpoint: replay
            # the idempotent uploads against the current branch head.
            checkpoint.update(index=0, revision=head)

    def save_checkpoint():
        temporary = checkpoint_path.with_suffix(".tmp")
        temporary.write_text(canonical(checkpoint))
        temporary.replace(checkpoint_path)

    remote = set(
        api.list_repo_files(repo_id=repo_id, repo_type="dataset", revision=head)
    )
    deletes = sorted(remote - set(expected) - {".gitattributes"})
    for offset in range(0, len(deletes), 100):
        commit = api.create_commit(
            repo_id=repo_id,
            repo_type="dataset",
            revision=branch,
            parent_commit=checkpoint["revision"],
            operations=[
                CommitOperationDelete(name) for name in deletes[offset : offset + 100]
            ],
            commit_message="Remove files outside this snapshot",
        )
        checkpoint["revision"] = commit.oid
        save_checkpoint()
    for offset in range(checkpoint["index"], len(expected), 100):
        commit = api.create_commit(
            repo_id=repo_id,
            repo_type="dataset",
            revision=branch,
            parent_commit=checkpoint["revision"],
            operations=[
                CommitOperationAdd(name, str(directory / name))
                for name in expected[offset : offset + 100]
            ],
            commit_message=f"Upload {run}: files {offset + 1}-{min(offset + 100, len(expected))}",
        )
        checkpoint.update(index=min(offset + 100, len(expected)), revision=commit.oid)
        save_checkpoint()
    revision = checkpoint["revision"]
    remote = set(
        api.list_repo_files(repo_id=repo_id, repo_type="dataset", revision=revision)
    )
    if remote - {".gitattributes"} != set(expected):
        raise ValueError("Remote release file list differs")
    downloaded = download(
        repo_id, "manifest.json", repo_type="dataset", revision=revision
    )
    if Path(downloaded).read_bytes() != (directory / "manifest.json").read_bytes():
        raise ValueError("Remote release manifest differs")
    api.create_tag(
        repo_id=repo_id, repo_type="dataset", tag=tag, revision=revision, exist_ok=True
    )
    if (
        api.repo_info(repo_id=repo_id, repo_type="dataset", revision=tag).sha
        != revision
    ):
        raise ValueError("Release tag already points to a different revision")
    # A single pointer commit activates only a complete immutable snapshot. An
    # intervening publication causes a conflict instead of silently replacing it.
    pointer = canonical(
        {
            "run_id": run,
            "revision": revision,
            "tag": tag,
            "manifest_sha256": manifest_hash,
        }
    ).encode()
    latest = api.repo_info(repo_id=repo_id, repo_type="dataset", revision="main").sha
    if latest != checkpoint["base"]:
        try:
            current = Path(
                download(repo_id, "latest.json", repo_type="dataset", revision=latest)
            ).read_bytes()
        except Exception as exc:
            raise ValueError(
                "HF main changed during upload; latest was not replaced"
            ) from exc
        if current != pointer:
            raise ValueError(
                "Another release advanced HF main; latest was not replaced"
            )
    else:
        operations = [
            CommitOperationAdd("latest.json", pointer),
            CommitOperationAdd(
                "sync.json",
                canonical(
                    sync_metadata(
                        manifest,
                        store.run(source_run),
                        revision,
                        store.db.execute(
                            "SELECT count(*) FROM observations WHERE run_id=? AND kind='courses'",
                            (source_run,),
                        ).fetchone()[0],
                    )
                ).encode(),
            ),
        ]
        # Put the friendly tables on main as well, so the default HF viewer works.
        # The serving pointer still pins the complete immutable release revision.
        if "public_tables" in manifest:
            from .public_data import dataset_card

            operations.append(
                CommitOperationAdd(
                    "README.md",
                    dataset_card(
                        source_run, manifest["public_tables"], repo_id=repo_id
                    ).encode(),
                )
            )
            operations.extend(
                CommitOperationAdd(name, str(directory / name))
                for name in expected
                if name.startswith("public/")
            )
        main_files = set(
            api.list_repo_files(repo_id=repo_id, repo_type="dataset", revision=latest)
        )
        public_files = (
            {name for name in expected if name.startswith("public/")}
            if "public_tables" in manifest
            else set()
        )
        operations.extend(
            CommitOperationDelete(name)
            for name in sorted(main_files)
            if name.startswith("public/") and name not in public_files
        )
        if (
            "public_tables" not in manifest
            and "public/courses_current.parquet" in main_files
            and "README.md" in main_files
        ):
            operations.append(CommitOperationDelete("README.md"))
        api.create_commit(
            repo_id=repo_id,
            repo_type="dataset",
            revision="main",
            parent_commit=checkpoint["base"],
            operations=operations,
            commit_message=f"Activate validated release {run}",
        )
    if "source_run" not in manifest:
        with store.db:
            store.db.execute(
                "UPDATE runs SET revision=? WHERE run_id=?", (revision, source_run)
            )
    checkpoint["complete"] = True
    save_checkpoint()
    return {"repo_id": repo_id, "revision": revision, "tag": tag}
