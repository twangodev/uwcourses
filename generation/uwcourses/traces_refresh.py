"""Offline, append-only HF conversation projection for an existing publication."""

from collections import Counter
import json
from pathlib import Path
import re
import shutil

from datasets import Dataset, Features
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from .models import canonical, digest
from .publication import publish_candidate, safe_relative, verify_file
from .release import checksum
from . import trace_format

TRACE_FILE = "public/llm_traces.parquet"
CONVERSATION_FILE = "public/llm_conversations.parquet"
CHANGED_PARENT_FILES = {TRACE_FILE, "public/schema.json", "README.md"}


def update_card(text):
    """Keep existing card metadata/configuration and add only trace documentation."""
    if not text.startswith("---\n") or "\n---" not in text[4:]:
        raise ValueError("Existing dataset card has no YAML metadata")
    metadata, body = text[4:].split("\n---", 1)
    metadata = yaml.safe_load(metadata)
    if not isinstance(metadata, dict) or not isinstance(metadata.get("configs"), list):
        raise ValueError("Existing dataset card has no explicit configurations")
    config = {
        "config_name": "llm_conversations",
        "data_files": [{"split": "train", "path": CONVERSATION_FILE}],
    }
    existing = [
        entry
        for entry in metadata["configs"]
        if entry.get("config_name") == "llm_conversations"
    ]
    if existing and existing != [config]:
        raise ValueError(
            "Existing llm_conversations configuration conflicts with the projection"
        )
    if not existing:
        metadata["configs"].append(config)
    section = """

## Recorded conversation format

`llm_traces.messages` contains only the recorded root conversation, as messages
with `role` and `content`. `llm_conversations` retains each recorded root,
subtask, grounding, repair and recovery conversation separately. Join it through
`trace_id`; `source_path` is a JSON pointer into the unchanged `output_json`.
Missing conversations stay explicitly missing; these columns never reconstruct
prompts or model responses from final outputs. Unsupported recorded parts are
reported in `conversation_issues`, and their original values remain available.

Messages also retain recorded thinking, tool calls, tool results, validator
feedback and source-part provenance. `tools` is populated only when an actual
recorded declaration exists. Tools are not inferred from observed calls. The
original `output_json`, `job_spec_json` and `usage_json` remain unchanged, as do
all course, outcome, grade, schedule and other source data.

Use `datasets>=4.7` to decode `Json` features in tool arguments, tools, source
parts and issues as native values. Parquet contains the corresponding HF feature
metadata; readers that do not support JSON extension types can inspect their
string storage. These traces are recorded machine output, not authoritative
course facts or a reviewed training dataset.
"""
    return (
        "---\n"
        + yaml.safe_dump(metadata, sort_keys=False).rstrip()
        + "\n---"
        + body
        + section
    )


def _project_traces(source, output):
    parquet = pq.ParquetFile(source)
    parent_schema = parquet.schema_arrow
    additions = set(trace_format.TRACE_ADDED_FEATURES)
    if additions & set(parent_schema.names):
        raise ValueError("Trace file already has conversation projection columns")
    added_features = Features(trace_format.TRACE_ADDED_FEATURES)
    full_features = trace_format.trace_features(parent_schema)
    schema = pa.schema(
        list(parent_schema) + list(added_features.arrow_schema),
        metadata={
            **(parent_schema.metadata or {}),
            **(full_features.arrow_schema.metadata or {}),
        },
    )
    child_features = trace_format.CONVERSATION_FEATURES
    counts, issues = Counter(), Counter()
    seen_traces, seen_conversations = set(), set()
    with (
        pq.ParquetWriter(output / TRACE_FILE, schema, compression="zstd") as writer,
        pq.ParquetWriter(
            output / CONVERSATION_FILE, child_features.arrow_schema, compression="zstd"
        ) as child_writer,
    ):
        for batch in parquet.iter_batches(batch_size=256):
            original = pa.Table.from_batches([batch])
            added_rows, child_rows = [], []
            for row in original.to_pylist():
                augmented, children = trace_format.normalize_trace(row)
                if augmented["trace_id"] in seen_traces:
                    raise ValueError("Duplicate trace identity in parent publication")
                seen_traces.add(augmented["trace_id"])
                added_rows.append(
                    {key: augmented[key] for key in trace_format.TRACE_ADDED_FEATURES}
                )
                counts["traces"] += 1
                counts["traces_with_root_messages"] += bool(augmented["messages"])
                counts["traces_with_any_conversation"] += augmented[
                    "has_any_conversation"
                ]
                counts["root_status:" + augmented["conversation_status"]] += 1
                for issue in augmented["conversation_issues"]:
                    issues[issue["code"]] += 1
                for child in children:
                    if child["conversation_id"] in seen_conversations:
                        raise ValueError(
                            "Duplicate conversation identity in projection"
                        )
                    seen_conversations.add(child["conversation_id"])
                    child_rows.append(child)
                    counts["conversations"] += 1
                    counts["conversation_status:" + child["conversation_status"]] += 1
            added = Dataset.from_dict(
                {key: [row[key] for row in added_rows] for key in added_features},
                features=added_features,
            ).data.table
            projected = original
            for field in added.schema:
                projected = projected.append_column(field, added[field.name])
            if not projected.select(parent_schema.names).equals(original):
                raise ValueError("Trace projection altered an original column")
            writer.write_table(projected.replace_schema_metadata(schema.metadata))
            if child_rows:
                child_writer.write_table(
                    Dataset.from_dict(
                        {
                            key: [row[key] for row in child_rows]
                            for key in child_features
                        },
                        features=child_features,
                    ).data.table
                )
    if counts["traces"] != parquet.metadata.num_rows:
        raise ValueError("Trace projection changed parent row count")
    # A second read checks the actual serialized legacy columns, not only the inputs.
    for old, new in zip(
        parquet.iter_batches(batch_size=256),
        pq.ParquetFile(output / TRACE_FILE).iter_batches(
            batch_size=256, columns=parent_schema.names
        ),
        strict=True,
    ):
        if not pa.Table.from_batches([old]).equals(pa.Table.from_batches([new])):
            raise ValueError("Serialized trace projection altered an original column")
    return schema, child_features.arrow_schema, dict(counts), dict(issues)


def refresh_traces(publication, parent_revision, output):
    """Prepare a complete candidate without scraping, inference or publication."""
    if not re.fullmatch(r"[0-9a-f]{40}", parent_revision):
        raise ValueError("A pinned parent dataset revision is required")
    publication, output = Path(publication).resolve(), Path(output).resolve()
    if output.exists() or output == publication or publication in output.parents:
        raise ValueError(
            "Trace candidate must be a new directory separate from its parent"
        )
    parent = json.loads((publication / "manifest.json").read_text())
    for name in (TRACE_FILE, "public/schema.json", "README.md"):
        if name not in parent["files"]:
            raise ValueError(
                f"Parent publication omits required trace migration input: {name}"
            )
    if CONVERSATION_FILE in parent["files"]:
        raise ValueError(
            "Parent publication already declares a conversation projection"
        )
    for name, expected in parent["files"].items():
        verify_file(publication / safe_relative(name), expected)
    sync = json.loads((publication / "sync.json").read_text())
    if sync.get("manifest_sha256") != checksum(publication / "manifest.json"):
        raise ValueError("Parent sync metadata does not match its manifest")
    release_id = (
        "traces-"
        + digest(
            {
                "parent_revision": parent_revision,
                "parent_manifest_sha256": checksum(publication / "manifest.json"),
                "trace_sha256": parent["files"][TRACE_FILE]["sha256"],
                "format": trace_format.FORMAT,
                "converter_sha256": checksum(Path(trace_format.__file__)),
            }
        )[:24]
    )
    output.mkdir(parents=True)
    for name in parent["files"]:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        # Modified files are written separately below; all other files get independent copies.
        if name not in CHANGED_PARENT_FILES:
            shutil.copy2(publication / name, target)
    schema, conversation_schema, counts, issues = _project_traces(
        publication / TRACE_FILE, output
    )
    public_schema = json.loads((publication / "public/schema.json").read_text())
    public_schema["tables"]["llm_traces"]["columns"] = {
        field.name: str(field.type) for field in schema
    }
    public_schema["tables"]["llm_traces"]["description"] += (
        " Additive role/content messages project the recorded root only; raw columns are unchanged."
    )
    public_schema["tables"]["llm_conversations"] = {
        "rows": counts.get("conversations", 0),
        "columns": {field.name: str(field.type) for field in conversation_schema},
        "description": "One row per recorded root or nested conversation branch; source_path points into its trace's unchanged output_json. Missing histories are never reconstructed.",
    }
    (output / "public/schema.json").write_text(canonical(public_schema))
    (output / "README.md").write_text(
        update_card((publication / "README.md").read_text())
    )
    provenance = {
        "format": trace_format.FORMAT,
        "converter_sha256": checksum(Path(trace_format.__file__)),
        "parent_dataset_revision": parent_revision,
        "parent_manifest_sha256": checksum(publication / "manifest.json"),
        "raw_trace_sha256": parent["files"][TRACE_FILE]["sha256"],
        "counts": counts,
        "root_issues": issues,
        "legacy_trace_columns_preserved": True,
        "source_run_unchanged": parent["source_run"],
        "source_rescraped": False,
        "inference_run": False,
    }
    manifest = {
        **parent,
        "run_id": release_id,
        "parent_dataset_revision": parent_revision,
        "public_tables": {
            **parent["public_tables"],
            "llm_conversations": counts.get("conversations", 0),
        },
        "supplemental_sources": {
            **parent.get("supplemental_sources", {}),
            "conversation_traces": provenance,
        },
    }
    unchanged = []
    for name, expected in parent["files"].items():
        if name not in CHANGED_PARENT_FILES:
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
    sync.update(
        data_release=release_id, manifest_sha256=checksum(output / "manifest.json")
    )
    sync.pop("data_revision", None)
    (output / "sync.json").write_text(canonical(sync))
    report = {
        "candidate": str(output),
        "release_id": release_id,
        "parent_revision": parent_revision,
        "counts": counts,
        "root_issues": issues,
        "original_trace_columns": pq.ParquetFile(
            publication / TRACE_FILE
        ).schema_arrow.names,
        "unchanged_parent_files": unchanged,
        "changed_parent_files": sorted(CHANGED_PARENT_FILES),
        "source_data_preserved": True,
        "published": False,
    }
    (output.parent / f"{release_id}-report.json").write_text(canonical(report))
    return report


def publish_traces(candidate, repo_id, parent_revision, api=None, download=None):
    candidate = Path(candidate)
    manifest = json.loads((candidate / "manifest.json").read_text())
    if not manifest.get("supplemental_sources", {}).get(
        "conversation_traces"
    ) or CONVERSATION_FILE not in manifest.get("files", {}):
        raise ValueError("Candidate is not a documented conversation trace supplement")
    return publish_candidate(
        candidate,
        repo_id,
        parent_revision,
        commit_message="feat(data): expose recorded HF conversation messages",
        api=api,
        download=download,
    )
