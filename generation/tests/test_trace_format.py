"""HF conversations retain tools and branches without fabricating history."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from datasets import load_dataset
import pyarrow.parquet as pq

from uwcourses.trace_format import normalize_trace, normalize_conversation
from uwcourses.public_data import TRACE_FEATURES, write_rows


def request(*parts):
    return {"kind": "request", "parts": list(parts)}


def response(*parts):
    return {"kind": "response", "parts": list(parts)}


class TraceFormatTests(unittest.TestCase):
    def test_orphan_feedback_retains_recorded_role_and_id_and_is_partial(self):
        feedback = {
            "part_kind": "retry-prompt",
            "content": "Fix the argument",
            "tool_name": "f",
            "tool_call_id": "orphan",
        }
        projected = normalize_conversation([request(feedback)])
        self.assertEqual(projected["conversation_status"], "partial")
        self.assertEqual(
            projected["conversation_issues"][0]["code"], "unmatched_tool_feedback"
        )
        self.assertEqual(len(projected["messages"]), 1)
        self.assertEqual(projected["messages"][0]["role"], "tool")
        self.assertEqual(projected["messages"][0]["tool_call_id"], "orphan")
        matched = normalize_conversation(
            [
                response(
                    {
                        "part_kind": "tool-call",
                        "tool_name": "f",
                        "tool_call_id": "orphan",
                        "args": {},
                    }
                ),
                request(feedback),
            ]
        )
        self.assertEqual(matched["conversation_status"], "converted")
        self.assertEqual(matched["conversation_issues"], [])
        orphan_result = normalize_conversation(
            [request({**feedback, "part_kind": "tool-return"})]
        )
        self.assertEqual(orphan_result["conversation_status"], "partial")
        self.assertEqual(
            orphan_result["conversation_issues"][0]["code"], "unmatched_tool_result"
        )

    def row(self, output):
        return {
            "job_id": "job",
            "run_id": "run",
            "course_id": "COMPSCI 300",
            "output_id": "output",
            "output_json": json.dumps(output, indent=2),
            "job_spec_json": ' {"untouched": true} ',
            "usage_json": '{ "tokens": 123 }',
        }

    def conversation(self, args=None):
        return [
            request({"part_kind": "user-prompt", "content": "Look up the course"}),
            response(
                {"part_kind": "thinking", "content": "Check its source."},
                {
                    "part_kind": "tool-call",
                    "tool_name": "get_course",
                    "tool_call_id": "call1",
                    "args": json.dumps(args or {"course_id": "COMPSCI 200"}),
                },
            ),
            request(
                {
                    "part_kind": "tool-return",
                    "tool_name": "get_course",
                    "tool_call_id": "call1",
                    "content": {"course_id": "COMPSCI 200", "credits": 3},
                }
            ),
            response({"part_kind": "text", "content": "Done"}),
        ]

    def test_native_projection_preserves_raw_bytes_thinking_and_argument_objects(self):
        row = self.row({"provenance": {"conversation": self.conversation()}})
        original = copy.deepcopy(row)
        parent, children = normalize_trace(row)
        for key, value in original.items():
            self.assertEqual(parent[key], value)
        self.assertEqual(row, original)
        self.assertEqual(parent["conversation_count"], 1)
        self.assertEqual(parent["tools_status"], "not_recorded")
        self.assertIsNone(parent["tools"])
        messages = parent["messages"]
        self.assertEqual(messages[1]["thinking"], "Check its source.")
        self.assertEqual(
            messages[1]["tool_calls"][0]["function"]["arguments"],
            {"course_id": "COMPSCI 200"},
        )
        self.assertEqual(json.loads(messages[2]["content"])["credits"], 3)
        self.assertEqual(messages[2]["source_parts"][0]["content"]["credits"], 3)
        self.assertEqual(children[0]["source_path"], "/provenance/conversation")
        self.assertEqual(normalize_trace(row)[0]["trace_id"], parent["trace_id"])

    def test_empty_missing_nested_checker_recovery_and_role_repair_remain_separate(
        self,
    ):
        output = {
            "provenance": {
                "conversation": [],
                "subtasks": [
                    {
                        "output": {
                            "provenance": {
                                "conversation": self.conversation(),
                                "grounding_checks": [
                                    {
                                        "output": {
                                            "provenance": {
                                                "conversation": self.conversation()
                                            }
                                        }
                                    }
                                ],
                            }
                        }
                    }
                ],
                "recovery_events": [{"conversation": self.conversation()}],
                "repair_conversation": [
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {"name": "f", "arguments": '{"a":1}'},
                            }
                        ],
                    }
                ],
            }
        }
        parent, children = normalize_trace(self.row(output))
        self.assertEqual(parent["conversation_status"], "empty")
        self.assertEqual(parent["messages"], [])
        self.assertTrue(parent["has_any_conversation"])
        self.assertEqual(parent["conversation_count"], 4)
        repair = next(
            row
            for row in children
            if row["source_path"].endswith("repair_conversation")
        )
        self.assertEqual(
            repair["messages"][0]["tool_calls"][0]["function"]["arguments"], {"a": 1}
        )
        missing, children = normalize_trace(
            self.row({"sections": {"search_profile": {"value": "Not a message"}}})
        )
        self.assertEqual(missing["conversation_status"], "missing")
        self.assertEqual(missing["messages"], [])
        self.assertEqual(children, [])

    def test_retry_feedback_and_malformed_arguments_are_explicit(self):
        raw = [
            request(
                {
                    "part_kind": "retry-prompt",
                    "content": [{"msg": "Field required"}],
                    "tool_name": "f",
                    "tool_call_id": "call1",
                },
                {"part_kind": "retry-prompt", "content": "Please use a tool"},
            ),
            response(
                {"part_kind": "tool-call", "tool_name": "f", "args": "broken JSON"}
            ),
        ]
        projected = normalize_conversation(raw)
        self.assertEqual(projected["conversation_status"], "partial")
        self.assertEqual(
            [msg["role"] for msg in projected["messages"][:2]], ["tool", "user"]
        )
        self.assertTrue(projected["messages"][0]["feedback"])
        self.assertEqual(
            json.loads(projected["messages"][0]["content"]), [{"msg": "Field required"}]
        )
        self.assertEqual(projected["messages"][-1]["tool_calls"], [])
        self.assertEqual(projected["messages"][-1]["source_parts"], raw[-1]["parts"])
        self.assertFalse(any(msg["role"] == "system" for msg in projected["messages"]))

    def test_parquet_load_dataset_decodes_heterogeneous_arguments_without_custom_adapter(
        self,
    ):
        rows = []
        for args in (
            {"course_id": "COMPSCI 200"},
            {"limit": 3, "nested": {"values": [1, "two", None], "enabled": True}},
        ):
            parent, _ = normalize_trace(
                self.row({"provenance": {"conversation": self.conversation(args)}})
            )
            rows.append(parent)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "traces.parquet"
            write_rows(path, TRACE_FEATURES.arrow_schema, rows, features=TRACE_FEATURES)
            self.assertIn(b"huggingface", pq.read_schema(path).metadata)
            self.assertIsInstance(
                pq.read_table(path)["messages"][0].as_py()[1]["tool_calls"][0], str
            )
            loaded = load_dataset(
                "parquet",
                data_files=str(path),
                split="train",
                cache_dir=str(Path(temp) / "cache"),
            )
            self.assertEqual(
                loaded[0]["messages"][1]["tool_calls"][0]["function"]["arguments"],
                {"course_id": "COMPSCI 200"},
            )
            self.assertEqual(
                loaded[1]["messages"][1]["tool_calls"][0]["function"]["arguments"][
                    "nested"
                ]["values"],
                [1, "two", None],
            )
            self.assertEqual(loaded[0]["output_json"], rows[0]["output_json"])
            self.assertEqual(
                loaded[0]["messages"][2]["source_parts"][0]["content"]["credits"], 3
            )
