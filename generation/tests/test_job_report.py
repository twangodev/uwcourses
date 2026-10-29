import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from uwcourses.job_report import report
from uwcourses.storage_codec import pack


class ReportTests(unittest.TestCase):
    def test_partial_job_distinguishes_completion_quality_and_preservation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "processing.sqlite"
            with sqlite3.connect(path) as db:
                db.executescript("""
                    CREATE TABLE jobs(job_id, status, source_run, spec_json);
                    CREATE TABLE results(job_id, course_id, status, input_json, output_json, usage_json);
                """)
                db.execute(
                    "INSERT INTO jobs VALUES(?,?,?,?)",
                    (
                        "job",
                        "running",
                        "source",
                        json.dumps(
                            {
                                "worker_version": 17,
                                "profile": {"base_url": "private-url"},
                            }
                        ),
                    ),
                )
                parent = {"status": "valid", "value": {"text": "accepted"}}
                source = {
                    "repair_seed": {"output": {"sections": {"search_profile": parent}}}
                }
                output = {
                    "sections": {
                        "search_profile": parent,
                        "requirements": {"status": "invalid"},
                    },
                    "provenance": {
                        "request_error": "Model token limit (16) exceeded",
                        "recovery_events": [{}],
                    },
                }
                db.execute(
                    "INSERT INTO results VALUES(?,?,?,?,?,?)",
                    (
                        "job",
                        "CS 100",
                        "complete",
                        json.dumps(source),
                        json.dumps(output),
                        '{"completion_tokens":10}',
                    ),
                )
                db.execute(
                    "INSERT INTO results VALUES(?,?,?,?,?,?)",
                    ("job", "CS 200", "pending", "{}", None, None),
                )
                db.execute(
                    "INSERT INTO results VALUES(?,?,?,?,?,?)",
                    ("job", "CS 300", "failed", "{}", None, None),
                )
            value = report(directory, "job")
            self.assertEqual(
                value["counts"], {"complete": 1, "pending": 1, "failed": 1}
            )
            self.assertEqual(value["sections"]["requirements"], {"invalid": 1})
            self.assertEqual(
                value["failure_categories"], {"token_limit": 1, "worker_error": 1}
            )
            self.assertEqual(value["recovery_courses"], 1)
            self.assertEqual(value["retained_sections_checked"], 1)
            self.assertEqual(value["changed_retained_sections"], 0)
            self.assertNotIn("private-url", json.dumps(value))
            with sqlite3.connect(path) as db:
                for column in ("input_json", "output_json", "usage_json"):
                    for rowid, text in db.execute(
                        f"SELECT rowid,{column} FROM results"
                    ).fetchall():
                        if text:
                            expanded = json.loads(text)
                            expanded["storage_test"] = "repeated evidence " * 1000
                            db.execute(
                                f"UPDATE results SET {column}=? WHERE rowid=?",
                                (pack(json.dumps(expanded)), rowid),
                            )
            self.assertEqual(report(directory, "job"), value)
            output["sections"]["search_profile"] = {
                "status": "valid",
                "value": {"text": "changed"},
            }
            with sqlite3.connect(path) as db:
                db.execute(
                    "UPDATE results SET output_json=? WHERE course_id='CS 100'",
                    (json.dumps(output),),
                )
            self.assertEqual(report(directory, "job")["changed_retained_sections"], 1)
            output["provenance"]["request_error"] = (
                "This model's maximum context length is 32768 tokens"
            )
            with sqlite3.connect(path) as db:
                db.execute(
                    "UPDATE results SET output_json=? WHERE course_id='CS 100'",
                    (json.dumps(output),),
                )
            self.assertEqual(
                report(directory, "job")["failure_categories"],
                {"context_window": 1, "worker_error": 1},
            )
            with self.assertRaisesRegex(ValueError, "Unknown enrichment"):
                report(directory, "absent")

    def test_missing_workspace_is_not_created(self):
        with tempfile.TemporaryDirectory() as directory:
            absent = Path(directory) / "absent"
            with self.assertRaises(sqlite3.OperationalError):
                report(absent, "job")
            self.assertFalse(absent.exists())
