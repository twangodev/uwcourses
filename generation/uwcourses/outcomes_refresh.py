"""Add independently archived official outcomes to a pinned public release.

This deliberately preserves the existing catalog version identities and all
other data. Outcomes are supplemental source evidence, not a catalog refresh or
an inference run. Publication is a separate, explicit operation.
"""

import gzip
import hashlib
import json
import logging
from pathlib import Path
import re
import shutil
from datetime import datetime

import pyarrow as pa
import pyarrow.parquet as pq

from .models import canonical, digest
from .release import checksum
from .course import Course
from .course_context import text_view

OUTCOME_COLUMN = "official_learning_outcomes_json"
CATALOG_FIELDS = (
    "course_id",
    "course_number",
    "subjects",
    "title",
    "description",
    "requirements_text",
)
SUPPLEMENT_SCHEMA = pa.schema(
    [
        ("course_id", pa.string()),
        ("course_uid", pa.string()),
        ("source_run", pa.string()),
        ("supplement_id", pa.string()),
        ("outcome_index", pa.int64()),
        ("text", pa.string()),
        ("source", pa.string()),
        ("source_url", pa.string()),
        ("observed_at", pa.string()),
        ("term", pa.string()),
        ("catalog_year", pa.string()),
        ("source_sha256", pa.string()),
    ]
)


def safe_relative(name):
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Publication manifest contains an unsafe path")
    return path


def verify_file(path, expected):
    if path.stat().st_size != expected["bytes"] or checksum(path) != expected["sha256"]:
        raise ValueError(f"Source publication checksum mismatch: {path.name}")


def read_evidence(path):
    records = {}
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        key = record["course_id"]
        if key in records:
            raise ValueError(f"Duplicate outcome evidence for {key}")
        records[key] = record
    return records


def refresh_outcomes(
    publication,
    evidence_jsonl,
    evidence_manifest,
    parent_revision,
    output,
    fallback=None,
):
    """Build a new, verified candidate; never write to input files or publish."""
    if not re.fullmatch(r"[0-9a-f]{40}", parent_revision):
        raise ValueError("A pinned parent dataset revision is required")
    publication, output = Path(publication).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("Outcome candidate output must be a new directory")
    if output == publication or publication in output.parents:
        raise ValueError("Candidate must be separate from its source publication")
    parent = json.loads((publication / "manifest.json").read_text())
    evidence = read_evidence(evidence_jsonl)
    source_manifest = json.loads(Path(evidence_manifest).read_text())
    if source_manifest.get(
        "parent_dataset_revision"
    ) != parent_revision or source_manifest.get("base_manifest_sha256") != checksum(
        publication / "manifest.json"
    ):
        raise ValueError("Evidence does not identify this pinned parent publication")
    if source_manifest.get("evidence_sha256") != checksum(Path(evidence_jsonl)):
        raise ValueError("Evidence JSONL checksum mismatch")
    current = pq.read_table(publication / "public/courses_current.parquet")
    current_rows = current.to_pylist()
    by_id = {row["course_id"]: row for row in current_rows}
    if len(by_id) != len(current_rows):
        raise ValueError("Current release has duplicate course IDs")
    if set(evidence) - by_id.keys():
        raise ValueError("Evidence references courses outside the pinned release")
    supplement_id = (
        "outcomes-"
        + digest(
            {
                "parent_revision": parent_revision,
                "evidence": evidence,
                "source_manifest": source_manifest,
            }
        )[:24]
    )
    source_pages, parsed_pages, typed_rows, counts = (
        {},
        {},
        [],
        {"matched_courses": 0, "courses_with_outcomes": 0, "outcomes": 0},
    )
    for key, record in evidence.items():
        row = by_id[key]
        proof = record["matched_catalog_fields"]
        if any(proof.get(field) != row[field] for field in CATALOG_FIELDS):
            raise ValueError(f"Evidence does not match pinned catalog fields: {key}")
        sources = {}
        for source in record["matched_sources"]:
            url, sha = source["source_url"], source["sha256"]
            if not re.fullmatch(r"https://guide\.wisc\.edu/courses/[a-z_]+/", url):
                raise ValueError(
                    "Outcome evidence must identify an official Guide subject URL"
                )
            if not re.fullmatch(r"[0-9a-f]{64}", sha):
                raise ValueError("Invalid archived source hash")
            raw = Path(source["raw_path"])
            source_key = (url, source.get("fetched_at"), source.get("catalog_year"))
            if source_key not in parsed_pages:
                body = gzip.decompress(raw.read_bytes())
                if hashlib.sha256(body).hexdigest() != sha:
                    raise ValueError(f"Archived source checksum mismatch: {url}")
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(body, "html.parser")
                tagline = soup.select_one(".site-tagline")
                year = tagline.get_text(strip=True) if tagline else None
                year = year if year and re.fullmatch(r"\d{4}-\d{4}", year) else None
                if year != source.get("catalog_year"):
                    raise ValueError("Catalog year differs from the archived page")
                parsed = {}
                for block in soup.select("div.courseblock"):
                    code = block.select_one(".courseblockcode")
                    if code:
                        identity = Course.Reference.from_string(
                            code.get_text()
                        ).get_identifier()
                        parsed_course = Course.from_block(
                            block,
                            logging.getLogger(__name__),
                            source_url=url,
                            observed_at=source.get("fetched_at"),
                            catalog_year=source.get("catalog_year"),
                        )
                        if parsed_course is None:
                            raise ValueError(
                                "Archived Guide course block could not be parsed"
                            )
                        parsed[identity] = parsed_course
                parsed_pages[source_key] = parsed
            identity = f"{'/'.join(sorted(row['subjects']))} {row['course_number']}"
            if identity not in parsed_pages[source_key]:
                raise ValueError(
                    f"Archived source does not contain the matched course: {key}"
                )
            parsed_course = parsed_pages[source_key][identity]
            if any(
                text_view(actual) != text_view(expected)
                for actual, expected in (
                    (parsed_course.course_title, row["title"]),
                    (parsed_course.description, row["description"]),
                    (
                        parsed_course.prerequisites.prerequisites_text,
                        row["requirements_text"],
                    ),
                )
            ):
                raise ValueError(
                    f"Archived catalog context differs from pinned course: {key}"
                )
            if (
                not source.get("fetched_at")
                or datetime.fromisoformat(source["fetched_at"]) > row["observed_at"]
            ):
                raise ValueError(
                    "Supplement source postdates the original catalog observation"
                )
            public_source = {
                name: source.get(name)
                for name in (
                    "source_url",
                    "sha256",
                    "fetched_at",
                    "catalog_year",
                    "response_run_id",
                )
            }
            if (
                source_key in source_pages
                and source_pages[source_key][0] != public_source
            ):
                raise ValueError("Conflicting archived source identity")
            source_pages[source_key] = (public_source, raw)
            sources[url] = public_source
        outcomes = record["official_learning_outcomes"]
        if not isinstance(outcomes, list):
            raise ValueError("Outcome evidence must be a list")
        for index, outcome in enumerate(outcomes):
            source = sources.get(outcome.get("source_url"))
            if not source or outcome.get("source") != "catalog":
                raise ValueError(f"Outcome has no matched official source: {key}")
            if not isinstance(outcome.get("text"), str) or not outcome["text"].strip():
                raise ValueError("Outcome statement is empty")
            if (
                outcome.get("observed_at") != source["fetched_at"]
                or outcome.get("catalog_year") != source["catalog_year"]
                or outcome.get("term") is not None
            ):
                raise ValueError(
                    "Outcome provenance differs from its archived response"
                )
            if (
                outcome
                not in parsed_pages[
                    (source["source_url"], source["fetched_at"], source["catalog_year"])
                ][identity].official_learning_outcomes
            ):
                raise ValueError(
                    f"Outcome is not an exact structured statement for its archived course: {key}"
                )
            typed_rows.append(
                {
                    "course_id": key,
                    "course_uid": row["course_uid"],
                    "source_run": parent["source_run"],
                    "supplement_id": supplement_id,
                    "outcome_index": index,
                    **outcome,
                    "source_sha256": source["sha256"],
                }
            )
        counts["matched_courses"] += 1
        counts["courses_with_outcomes"] += bool(outcomes)
        counts["outcomes"] += len(outcomes)
    # Verify every parent file before producing a concrete publication candidate.
    source_paths = {}
    for name, expected in parent["files"].items():
        relative = safe_relative(name)
        source = publication / relative
        if not source.exists() and fallback:
            source = Path(fallback) / relative
        verify_file(source, expected)
        source_paths[name] = source
    output.mkdir(parents=True)
    for name, source in source_paths.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    values = [
        canonical(evidence[row["course_id"]]["official_learning_outcomes"])
        if row["course_id"] in evidence
        else "[]"
        for row in current_rows
    ]
    if OUTCOME_COLUMN in current.column_names:
        updated = current.set_column(
            current.column_names.index(OUTCOME_COLUMN),
            OUTCOME_COLUMN,
            pa.array(values, type=pa.string()),
        )
    else:
        updated = current.append_column(
            OUTCOME_COLUMN, pa.array(values, type=pa.string())
        )
    pq.write_table(
        updated, output / "public/courses_current.parquet", compression="zstd"
    )
    preserved_columns = [
        name for name in current.column_names if name != OUTCOME_COLUMN
    ]
    if (
        not pq.read_table(output / "public/courses_current.parquet")
        .select(preserved_columns)
        .equals(current.select(preserved_columns))
    ):
        raise ValueError("Outcome supplementation changed an existing course column")
    pq.write_table(
        pa.Table.from_pylist(typed_rows, schema=SUPPLEMENT_SCHEMA),
        output / "tables/official_learning_outcomes.parquet",
        compression="zstd",
    )
    pages = []
    for source, raw in sorted(
        source_pages.values(),
        key=lambda value: (value[0]["source_url"], value[0]["fetched_at"] or ""),
    ):
        relative = f"public/official-outcomes-sources/{source['sha256']}.html.gz"
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(raw, target)
        pages.append(
            {
                **source,
                "archived_body": relative,
                "stored_sha256": checksum(target),
                "raw_encoding": "gzip",
            }
        )
    provenance = {
        "supplement_id": supplement_id,
        "parent_dataset_revision": parent_revision,
        "source_run": parent["source_run"],
        "pages": pages,
        "source_coverage": {
            key: source_manifest.get(key)
            for key in (
                "version",
                "evidence_sha256",
                "base_manifest_sha256",
                "source_run",
                "archive_run",
                "matching_policy",
                "metrics",
            )
        },
        **counts,
        "scope": "Official outcomes supplement only; original catalog identities and history are unchanged.",
    }
    (output / "public/official_learning_outcomes_sources.json").write_text(
        canonical(provenance)
    )
    schema_path = output / "public/schema.json"
    schema = json.loads(schema_path.read_text())
    schema["tables"]["courses_current"]["columns"][OUTCOME_COLUMN] = "string"
    schema_path.write_text(canonical(schema))
    manifest = {
        **parent,
        "run_id": supplement_id,
        "parent_dataset_revision": parent_revision,
        "supplemental_sources": {
            **parent.get("supplemental_sources", {}),
            "official_learning_outcomes": provenance,
        },
        "tables": {
            **parent.get("tables", {}),
            "official_learning_outcomes": len(typed_rows),
        },
    }
    changed = {"public/courses_current.parquet", "public/schema.json"}
    unchanged = []
    for name, expected in parent["files"].items():
        if name not in changed:
            verify_file(output / name, expected)
            unchanged.append(name)
    manifest["files"] = {
        p.relative_to(output).as_posix(): {
            "bytes": p.stat().st_size,
            "sha256": checksum(p),
        }
        for p in sorted(output.rglob("*"))
        if p.is_file()
    }
    (output / "manifest.json").write_text(canonical(manifest))
    if (publication / "sync.json").exists():
        sync = json.loads((publication / "sync.json").read_text())
        sync.update(
            data_release=supplement_id,
            manifest_sha256=checksum(output / "manifest.json"),
        )
        sync.pop("data_revision", None)
        (output / "sync.json").write_text(canonical(sync))
    report = {
        "candidate": str(output),
        "release_id": supplement_id,
        "parent_revision": parent_revision,
        "courses": len(current_rows),
        **counts,
        "matched_pages": len(pages),
        "unmatched_courses": sorted(by_id.keys() - evidence.keys()),
        "unchanged_parent_files": unchanged,
        "changed_parent_files": sorted(changed),
        "existing_current_columns_preserved": True,
        "pilot_outputs_attached": False,
        "experimental_classification_enabled": False,
        "published": False,
    }
    return report


def publish_outcomes(candidate, repo_id, parent_revision, api=None, download=None):
    """Publish a reviewed supplement atomically with a pinned parent guard."""
    from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download

    candidate = Path(candidate)
    manifest = json.loads((candidate / "manifest.json").read_text())
    if manifest.get("parent_dataset_revision") != parent_revision or not manifest.get(
        "supplemental_sources", {}
    ).get("official_learning_outcomes"):
        raise ValueError(
            "Candidate is not an outcomes supplement for the pinned parent"
        )
    expected = dict(manifest["files"])
    for name in ("manifest.json", "sync.json"):
        expected[name] = {
            "bytes": (candidate / name).stat().st_size,
            "sha256": checksum(candidate / name),
        }
    for name, metadata in expected.items():
        verify_file(candidate / safe_relative(name), metadata)
    api, download = api or HfApi(), download or hf_hub_download
    if api.repo_info(repo_id=repo_id, repo_type="dataset").sha != parent_revision:
        raise ValueError("Dataset main changed since the candidate was prepared")
    existing = set(
        api.list_repo_files(repo_id, repo_type="dataset", revision=parent_revision)
    ) - {".gitattributes"}
    if not existing <= expected.keys():
        raise ValueError("Candidate omits files from the current dataset")
    checkpoint = candidate.parent / f"{manifest['run_id']}-publication.json"
    checkpoint.write_text(
        canonical(
            {
                "status": "uploading",
                "repo_id": repo_id,
                "parent_revision": parent_revision,
                "release_id": manifest["run_id"],
            }
        )
    )
    result = api.create_commit(
        repo_id=repo_id,
        repo_type="dataset",
        parent_commit=parent_revision,
        commit_message="feat(data): add archived official course outcomes",
        operations=[
            CommitOperationAdd(path_in_repo=name, path_or_fileobj=str(candidate / name))
            for name in sorted(expected)
        ],
        num_threads=8,
    )
    revision = result.oid
    checkpoint.write_text(
        canonical(
            {
                "status": "verifying",
                "repo_id": repo_id,
                "parent_revision": parent_revision,
                "revision": revision,
                "release_id": manifest["run_id"],
            }
        )
    )
    actual = set(
        api.list_repo_files(repo_id, repo_type="dataset", revision=revision)
    ) - {".gitattributes"}
    if actual != expected.keys():
        raise ValueError("Published outcomes file set differs from the candidate")
    checked = set()
    for info in api.get_paths_info(
        repo_id=repo_id, paths=list(expected), repo_type="dataset", revision=revision
    ):
        checked.add(info.path)
        sha = (
            info.lfs.sha256
            if info.lfs
            else checksum(
                Path(
                    download(
                        repo_id=repo_id,
                        filename=info.path,
                        repo_type="dataset",
                        revision=revision,
                    )
                )
            )
        )
        if (
            info.size != expected[info.path]["bytes"]
            or sha != expected[info.path]["sha256"]
        ):
            raise ValueError(f"Remote outcomes checksum mismatch: {info.path}")
    if (
        checked != expected.keys()
        or api.repo_info(repo_id=repo_id, repo_type="dataset").sha != revision
    ):
        raise ValueError("Dataset changed during remote outcomes verification")
    report = {
        "repo_id": repo_id,
        "revision": revision,
        "parent_revision": parent_revision,
        "release_id": manifest["run_id"],
        "verified_files": len(checked),
        "status": "complete",
    }
    checkpoint.write_text(canonical(report))
    return report
