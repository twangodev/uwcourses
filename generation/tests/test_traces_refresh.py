import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from datasets import load_dataset
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from uwcourses.models import canonical
from uwcourses.release import checksum
from uwcourses.traces_refresh import refresh_traces, publish_traces


LEGACY_SCHEMA = pa.schema(
    [
        ("job_id", pa.string()),
        ("run_id", pa.string()),
        ("course_id", pa.string()),
        ("course_uid", pa.string()),
        ("output_id", pa.string()),
        ("model", pa.string()),
        ("model_revision", pa.string()),
        ("created_at", pa.timestamp("us", tz="UTC")),
        ("selected_for_release", pa.bool_()),
        ("has_conversation", pa.bool_()),
        ("job_spec_json", pa.string()),
        ("output_json", pa.string()),
        ("usage_json", pa.string()),
    ]
)


class TraceRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.parent = self.root / "parent"
        self.output = self.root / "candidate"
        (self.parent / "public").mkdir(parents=True)
        (self.parent / "tables").mkdir()
        self.revision = "a" * 40
        self.native = [
            {
                "kind": "request",
                "parts": [
                    {"part_kind": "system-prompt", "content": "Recorded system."},
                    {"part_kind": "user-prompt", "content": "Recorded user."},
                ],
            },
            {
                "kind": "response",
                "parts": [
                    {"part_kind": "thinking", "content": "Recorded thinking."},
                    {
                        "part_kind": "tool-call",
                        "tool_name": "lookup",
                        "tool_call_id": "call-1",
                        "args": {"course": "CS 300", "nested": [True, {"x": 1}]},
                    },
                ],
            },
            {
                "kind": "request",
                "parts": [
                    {
                        "part_kind": "tool-return",
                        "tool_name": "lookup",
                        "tool_call_id": "call-1",
                        "content": {"found": True},
                    }
                ],
            },
            {
                "kind": "response",
                "parts": [{"part_kind": "text", "content": "Recorded answer."}],
            },
        ]
        self.rows = [
            self.row(
                "a",
                {
                    "provenance": {
                        "conversation": self.native,
                        "recovery_events": [{"conversation": self.native[-1:]}],
                    }
                },
            ),
            self.row(
                "b",
                {
                    "sections": {"final": "Not a recorded conversation"},
                    "provenance": {"subtasks": [{"conversation": self.native}]},
                },
            ),
            self.row(
                "c",
                {"sections": {"final": "Also not a conversation"}, "provenance": {}},
            ),
        ]
        pq.write_table(
            pa.Table.from_pylist(self.rows, schema=LEGACY_SCHEMA),
            self.parent / "public/llm_traces.parquet",
        )
        (self.parent / "public/schema.json").write_text(
            canonical(
                {
                    "version": 6,
                    "tables": {
                        "llm_traces": {
                            "rows": 3,
                            "columns": {f.name: str(f.type) for f in LEGACY_SCHEMA},
                            "description": "Original trace contract.",
                        }
                    },
                }
            )
        )
        self.card = {
            "pretty_name": "Existing title",
            "tags": ["existing-tag"],
            "configs": [
                {
                    "config_name": "courses_current",
                    "default": True,
                    "data_files": [
                        {"split": "train", "path": "public/courses_current.parquet"}
                    ],
                },
                {
                    "config_name": "llm_traces",
                    "data_files": [
                        {"split": "train", "path": "public/llm_traces.parquet"}
                    ],
                },
            ],
        }
        (self.parent / "README.md").write_text(
            "---\n"
            + yaml.safe_dump(self.card, sort_keys=False)
            + "---\n\nExisting card prose.\n"
        )
        for name, value in (
            ("public/courses_current.parquet", b"course and outcome data"),
            ("tables/observations.parquet", b"original source archive"),
            ("public/source.html.gz", b"original compressed source"),
        ):
            (self.parent / name).write_bytes(value)
        self.manifest = {
            "run_id": "old-release",
            "source_run": "old-source",
            "observed_at": "2026-09-07T00:00:00Z",
            "public_tables": {"llm_traces": 3, "courses_current": 1},
            "tables": {"observations": 1},
            "supplemental_sources": {"official_learning_outcomes": {"unchanged": True}},
            "files": {
                p.relative_to(self.parent).as_posix(): {
                    "bytes": p.stat().st_size,
                    "sha256": checksum(p),
                }
                for p in self.parent.rglob("*")
                if p.is_file()
            },
        }
        (self.parent / "manifest.json").write_text(canonical(self.manifest))
        self.sync = {
            "last_scan_utc": "2026-09-07T00:00:00Z",
            "data_release": "old-release",
            "manifest_sha256": checksum(self.parent / "manifest.json"),
            "courses": 1,
        }
        (self.parent / "sync.json").write_text(canonical(self.sync))

    def row(self, key, output):
        return {
            "job_id": "job-" + key,
            "run_id": "old-source",
            "course_id": "CS " + key,
            "course_uid": "course-" + key,
            "output_id": "output-" + key,
            "model": "recorded-model",
            "model_revision": "recorded-revision",
            "created_at": datetime(2026, 9, 7, tzinfo=timezone.utc),
            "selected_for_release": True,
            "has_conversation": bool(output.get("provenance", {}).get("conversation")),
            "job_spec_json": '{"original":  true}',
            "output_json": json.dumps(output),
            "usage_json": '{"tokens": 5}',
        }

    def build(self):
        return refresh_traces(self.parent, self.revision, self.output)

    def test_real_parquet_projection_preserves_raw_columns_and_decodes_json(self):
        report = self.build()
        original = pq.read_table(self.parent / "public/llm_traces.parquet")
        augmented = pq.read_table(self.output / "public/llm_traces.parquet")
        self.assertTrue(augmented.select(original.column_names).equals(original))
        traces = load_dataset(
            "parquet",
            data_files=str(self.output / "public/llm_traces.parquet"),
            split="train",
            cache_dir=str(self.root / "cache"),
        )
        first = traces[0]
        self.assertEqual(
            [message["role"] for message in first["messages"]],
            ["system", "user", "assistant", "tool", "assistant"],
        )
        call = first["messages"][2]["tool_calls"][0]
        self.assertEqual(
            call["function"]["arguments"],
            {"course": "CS 300", "nested": [True, {"x": 1}]},
        )
        self.assertEqual(
            first["messages"][2]["source_parts"][1]["args"],
            call["function"]["arguments"],
        )
        self.assertEqual(first["messages"][2]["thinking"], "Recorded thinking.")
        self.assertEqual(first["messages"][3]["tool_call_id"], "call-1")
        self.assertEqual(report["counts"]["traces"], 3)
        self.assertEqual(report["counts"]["conversations"], 3)

    def test_missing_root_never_concatenates_subtasks_or_invents_final_output(self):
        self.build()
        traces = load_dataset(
            "parquet",
            data_files=str(self.output / "public/llm_traces.parquet"),
            split="train",
            cache_dir=str(self.root / "cache"),
        )
        children = load_dataset(
            "parquet",
            data_files=str(self.output / "public/llm_conversations.parquet"),
            split="train",
            cache_dir=str(self.root / "cache"),
        )
        self.assertEqual(traces[1]["messages"], [])
        self.assertEqual(traces[1]["conversation_status"], "missing")
        self.assertTrue(traces[1]["has_any_conversation"])
        self.assertEqual(traces[2]["messages"], [])
        self.assertFalse(traces[2]["has_any_conversation"])
        self.assertEqual(
            {row["source_path"] for row in children},
            {
                "/provenance/conversation",
                "/provenance/recovery_events/0/conversation",
                "/provenance/subtasks/0/conversation",
            },
        )
        self.assertTrue(all(row["source_hash"] for row in children))

    def test_nontrace_files_card_configs_and_scan_dates_remain_preserved(self):
        report = self.build()
        for name in report["unchanged_parent_files"]:
            self.assertEqual(
                checksum(self.output / name), self.manifest["files"][name]["sha256"]
            )
        updated_card = (self.output / "README.md").read_text()
        metadata = yaml.safe_load(updated_card.split("---", 2)[1])
        self.assertEqual(metadata["configs"][:2], self.card["configs"])
        self.assertEqual(metadata["pretty_name"], self.card["pretty_name"])
        self.assertIn("Existing card prose.", updated_card)
        self.assertIn("datasets>=4.7", updated_card)
        sync = json.loads((self.output / "sync.json").read_text())
        self.assertEqual(sync["last_scan_utc"], self.sync["last_scan_utc"])
        manifest = json.loads((self.output / "manifest.json").read_text())
        self.assertEqual(manifest["source_run"], self.manifest["source_run"])
        self.assertEqual(manifest["tables"], self.manifest["tables"])
        self.assertEqual(
            manifest["supplemental_sources"]["official_learning_outcomes"],
            {"unchanged": True},
        )

    def test_corrupted_parent_rejected_before_writing_candidate(self):
        (self.parent / "public/source.html.gz").write_bytes(b"changed source")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_publish_rejects_parent_change_and_corrupt_candidate(self):
        self.build()
        api = SimpleNamespace(repo_info=lambda **kwargs: SimpleNamespace(sha="b" * 40))
        with self.assertRaisesRegex(ValueError, "main changed"):
            publish_traces(self.output, "test/repo", self.revision, api=api)
        (self.output / "public/courses_current.parquet").write_bytes(
            b"changed course data"
        )
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            publish_traces(self.output, "test/repo", self.revision, api=api)

    def test_atomic_publish_verifies_every_file_and_keeps_parent_guard(self):
        self.build()
        candidate = self.output
        files = set(json.loads((candidate / "manifest.json").read_text())["files"]) | {
            "manifest.json",
            "sync.json",
        }
        parent_files = set(self.manifest["files"]) | {"manifest.json", "sync.json"}

        class Api:
            published = False

            def repo_info(self, **kwargs):
                return SimpleNamespace(sha="c" * 40 if self.published else "a" * 40)

            def list_repo_files(self, *args, **kwargs):
                return list(files if self.published else parent_files)

            def create_commit(self, **kwargs):
                self.parent_commit = kwargs["parent_commit"]
                self.operations = kwargs["operations"]
                self.published = True
                return SimpleNamespace(oid="c" * 40)

            def get_paths_info(self, **kwargs):
                return [
                    SimpleNamespace(
                        path=name,
                        size=(candidate / name).stat().st_size,
                        lfs=SimpleNamespace(sha256=checksum(candidate / name)),
                    )
                    for name in kwargs["paths"]
                ]

        api = Api()
        report = publish_traces(candidate, "test/repo", self.revision, api=api)
        self.assertEqual(api.parent_commit, self.revision)
        self.assertEqual(
            {operation.path_in_repo for operation in api.operations}, files
        )
        self.assertEqual(report["verified_files"], len(files))
        self.assertEqual(report["status"], "complete")
