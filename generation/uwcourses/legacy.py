"""One-time recovery of processed snapshots; no raw source or model provenance is invented."""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from .schema import runs, observations, artifacts
from .models import CourseReference, canonical, digest, validate_record
from .store import now


def git(repository, *args):
    return subprocess.check_output(["git", "-C", str(repository), *args])


def legacy_state(store, run):
    return {
        "courses": store.records(run, "courses"),
        "instructors": store.records(run, "instructors"),
        "meetings": store.get_artifact(run, "legacy_meetings"),
    }


def import_revision(store, repository, revision):
    commit = (
        git(repository, "rev-parse", "--verify", f"{revision}^{{commit}}")
        .decode()
        .strip()
    )
    run = f"legacy-{commit}"
    if store.db.execute(select(runs.c.run_id).where(runs.c.run_id == run)).fetchone():
        return {"run_id": run, "status": "already_imported"}
    entries = git(repository, "ls-tree", "-rz", commit).split(b"\0")
    selected = []
    for entry in entries:
        if not entry:
            continue
        metadata, filename = entry.split(b"\t", 1)
        path = PurePosixPath(filename.decode())
        if str(path) in {"subjects.json", "terms.json", "update.json"} or (
            path.suffix == ".json"
            and (
                (len(path.parts) == 2 and path.parts[0] in {"course", "instructors"})
                or (
                    len(path.parts) == 3
                    and path.parts[0] == "course"
                    and path.name == "meetings.json"
                )
            )
        ):
            selected.append((path, metadata.split()[2]))
    values = {}
    process = subprocess.Popen(
        ["git", "-C", str(repository), "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    try:
        for path, oid in selected:
            process.stdin.write(oid + b"\n")
            process.stdin.flush()
            header = process.stdout.readline().split()
            if len(header) != 3 or header[1] != b"blob":
                raise ValueError(f"Invalid Git blob: {path}")
            data = process.stdout.read(int(header[2]))
            process.stdout.read(1)
            values[str(path)] = json.loads(data)
    finally:
        process.stdin.close()
        process.stdout.close()
        process.wait()
    timestamp = datetime.fromisoformat(values["update.json"]["updated_on"])
    if timestamp.tzinfo is None:
        raise ValueError("Legacy update timestamp lacks timezone")
    observed = timestamp.astimezone(timezone.utc).isoformat()
    subjects, terms = values["subjects.json"], values["terms.json"]
    courses, instructors, meetings, rows = {}, {}, {}, []
    paths_to_courses = {}
    for path, value in values.items():
        parts = PurePosixPath(path).parts
        if len(parts) != 2:
            continue
        if parts[0] == "course":
            key = CourseReference.model_validate(value["course_reference"]).identifier
            if key in courses and courses[key] != value:
                raise ValueError(f"Conflicting legacy course aliases: {key}")
            courses[key] = value
            paths_to_courses[PurePosixPath(path).stem] = key
        elif parts[0] == "instructors":
            instructors[PurePosixPath(path).stem] = value
    if not courses or not instructors or not subjects or not terms:
        raise ValueError("Legacy snapshot is missing core records")
    for key, course in courses.items():
        if set(course["course_reference"]["subjects"]) - subjects.keys():
            raise ValueError(f"Missing subject for {key}")
        if set(course.get("term_data", {})) - terms.keys():
            raise ValueError(f"Missing term for {key}")
    for path, value in values.items():
        parts = PurePosixPath(path).parts
        if len(parts) == 3:
            if parts[1] not in paths_to_courses:
                raise ValueError(
                    f"Legacy meetings file has no matching course: {path} at {commit}"
                )
            key = paths_to_courses[parts[1]]
            # Identical meetings in a legacy export represent one occurrence.
            meetings[key] = list({canonical(m): m for m in value}.values())
    source_url = f"https://github.com/twangodev/uw-coursemap-data/tree/{commit}"
    for kind, records in (
        ("courses", courses),
        ("instructors", instructors),
        ("subjects", {k: {"name": v} for k, v in subjects.items()}),
        ("terms", {k: {"name": v} for k, v in terms.items()}),
    ):
        for key, payload in records.items():
            validate_record(
                {"kind": kind, "key": key, "source_url": source_url, "payload": payload}
            )
            rows.append(
                {
                    "run_id": run,
                    "source": "legacy",
                    "kind": kind,
                    "entity_id": key,
                    "source_url": source_url,
                    "observed_at": observed,
                    "content_hash": digest(payload),
                    "payload_json": canonical(payload),
                }
            )
    provenance = {
        "origin": "legacy",
        "source_revision": commit,
        "raw_responses_available": False,
        "model_provenance": "unknown",
        "semester_inferred": True,
    }
    # The original scrape target was not recorded. Prefer actual enrollment terms.
    enrollment_terms = {
        term
        for course in courses.values()
        for term, data in course.get("term_data", {}).items()
        if data.get("enrollment_data")
    }
    semester = max(enrollment_terms or terms.keys())
    with store.db:
        store.db.execute(
            insert(runs).values(
                run_id=run,
                semester=semester,
                started_at=now(),
                completed_at=now(),
                status="complete",
                config_json=canonical(provenance),
                observed_at=observed,
                origin="legacy",
                source_revision=commit,
            ),
        )
        store.db.executemany(insert(observations), rows)
        store.db.execute(
            insert(artifacts).values(
                run_id=run,
                name="legacy_meetings",
                input_hash=digest(meetings),
                config_json=canonical(provenance),
                payload_json=canonical(meetings),
            ),
        )
    return {
        "run_id": run,
        "status": "imported",
        "observed_at": observed,
        "courses": len(courses),
        "instructors": len(instructors),
        "meetings": sum(map(len, meetings.values())),
    }
