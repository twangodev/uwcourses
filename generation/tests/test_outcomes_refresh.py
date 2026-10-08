import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

from uwcourses.learning_outcomes import outcome
from uwcourses.models import canonical
from uwcourses.outcomes_refresh import refresh_outcomes, publish_outcomes
from uwcourses.release import checksum


class OutcomesRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.publication = self.root / "parent"
        (self.publication / "public").mkdir(parents=True)
        (self.publication / "tables").mkdir()
        self.revision = "a" * 40
        self.row = {
            "course_id": "COMPSCI 300",
            "course_uid": "course-300",
            "course_number": 300,
            "subjects": ["COMPSCI"],
            "title": "Programming II",
            "description": "Objects and classes.",
            "requirements_text": "",
            "catalog_version_id": "old-catalog-id",
            "observed_at": __import__("datetime").datetime.fromisoformat(
                "2026-09-07T00:00:00+00:00"
            ),
            "llm_search_status": "valid",
            "llm_skills": ["Existing skill"],
            "llm_requirements_ast_json": '{"existing":true}',
        }
        pq.write_table(
            pa.Table.from_pylist([self.row]),
            self.publication / "public/courses_current.parquet",
        )
        (self.publication / "public/schema.json").write_text(
            canonical(
                {
                    "version": 6,
                    "tables": {"courses_current": {"rows": 1, "columns": {}}},
                }
            )
        )
        (self.publication / "tables/grades.parquet").write_bytes(
            b"original grades remain identical"
        )
        (self.publication / "README.md").write_text("Original dataset card")
        self.parent_manifest = {
            "run_id": "old-release",
            "source_run": "original-run",
            "tables": {},
            "public_tables": {"courses_current": 1},
            "files": {
                p.relative_to(self.publication).as_posix(): {
                    "bytes": p.stat().st_size,
                    "sha256": checksum(p),
                }
                for p in self.publication.rglob("*")
                if p.is_file()
            },
        }
        (self.publication / "manifest.json").write_text(canonical(self.parent_manifest))
        (self.publication / "sync.json").write_text(
            canonical(
                {"last_scan_utc": "2026-09-07T00:00:00Z", "data_release": "old-release"}
            )
        )
        self.body = """<p class="site-tagline">2026-2027</p><div class="courseblock">
        <p class="courseblocktitle noindent"><span class="courseblockcode">COMP SCI 300</span> — Programming II</p>
        <p class="courseblockdesc noindent">Objects and classes.</p>
        <div class="cb-extras"><span class="cbextra-label">Learning Outcomes:</span><span class="cbextra-data">1. Implement objects.<br/>Audience: Undergraduate</span></div></div>""".encode()
        self.raw = self.root / "archived-response.gz"
        self.raw.write_bytes(gzip.compress(self.body, mtime=0))
        self.sha = hashlib.sha256(self.body).hexdigest()
        self.url = "https://guide.wisc.edu/courses/comp_sci/"
        self.record = {
            "course_id": self.row["course_id"],
            "matched_catalog_fields": {
                key: self.row[key]
                for key in (
                    "course_id",
                    "course_number",
                    "subjects",
                    "title",
                    "description",
                    "requirements_text",
                )
            },
            "matched_sources": [
                {
                    "source_url": self.url,
                    "sha256": self.sha,
                    "raw_path": str(self.raw),
                    "fetched_at": "2026-09-06T00:00:00+00:00",
                    "catalog_year": "2026-2027",
                    "response_run_id": "archive-run",
                }
            ],
            "official_learning_outcomes": [
                outcome(
                    "Implement objects.",
                    source="catalog",
                    source_url=self.url,
                    observed_at="2026-09-06T00:00:00+00:00",
                    catalog_year="2026-2027",
                )
            ],
        }
        self.evidence = self.root / "evidence.jsonl"
        self.evidence_manifest = self.root / "source-manifest.json"
        self.save_evidence()

    def save_evidence(self):
        self.evidence.write_text(canonical(self.record) + "\n")
        self.evidence_manifest.write_text(
            canonical(
                {
                    "parent_dataset_revision": self.revision,
                    "base_manifest_sha256": checksum(
                        self.publication / "manifest.json"
                    ),
                    "evidence_sha256": checksum(self.evidence),
                    "raw_path": str(self.raw),
                }
            )
        )

    def build(self):
        return refresh_outcomes(
            self.publication,
            self.evidence,
            self.evidence_manifest,
            self.revision,
            self.root / "candidate",
        )

    def test_outcomes_only_preserves_existing_fields_files_and_scan_time(self):
        report = self.build()
        candidate = self.root / "candidate"
        old = pq.read_table(self.publication / "public/courses_current.parquet")
        new = pq.read_table(candidate / "public/courses_current.parquet")
        self.assertTrue(new.select(old.column_names).equals(old))
        self.assertEqual(
            json.loads(new["official_learning_outcomes_json"][0].as_py()),
            self.record["official_learning_outcomes"],
        )
        self.assertEqual(
            (candidate / "tables/grades.parquet").read_bytes(),
            b"original grades remain identical",
        )
        self.assertEqual((candidate / "README.md").read_text(), "Original dataset card")
        self.assertEqual(
            json.loads((candidate / "sync.json").read_text())["last_scan_utc"],
            "2026-09-07T00:00:00Z",
        )
        self.assertNotIn(
            str(self.root),
            (candidate / "public/official_learning_outcomes_sources.json").read_text(),
        )
        self.assertEqual(report["outcomes"], 1)

    def test_rejects_wrong_course_context_and_invented_outcomes(self):
        self.record["official_learning_outcomes"][0]["text"] = "Invented statement."
        self.save_evidence()
        with self.assertRaisesRegex(ValueError, "exact structured statement"):
            self.build()
        self.record["official_learning_outcomes"][0]["text"] = "Implement objects."
        self.record["matched_catalog_fields"]["description"] = "Different context."
        self.save_evidence()
        with self.assertRaisesRegex(ValueError, "pinned catalog fields"):
            self.build()

    def test_rejects_changed_archive_and_postdated_sources(self):
        self.raw.write_bytes(gzip.compress(b"wrong source", mtime=0))
        with self.assertRaisesRegex(ValueError, "Archived source checksum"):
            self.build()
        self.raw.write_bytes(gzip.compress(self.body, mtime=0))
        self.record["matched_sources"][0]["fetched_at"] = "2026-10-01T00:00:00+00:00"
        self.save_evidence()
        with self.assertRaisesRegex(ValueError, "postdates"):
            self.build()

    def test_rejects_archived_course_context_even_with_valid_statement(self):
        body = self.body.replace(b"Objects and classes.", b"Different course context.")
        self.raw.write_bytes(gzip.compress(body, mtime=0))
        self.record["matched_sources"][0]["sha256"] = hashlib.sha256(body).hexdigest()
        self.save_evidence()
        with self.assertRaisesRegex(ValueError, "Archived catalog context"):
            self.build()

    def test_atomic_publish_guard_and_remote_verification(self):
        self.build()
        candidate = self.root / "candidate"
        with self.assertRaisesRegex(ValueError, "main changed"):
            publish_outcomes(
                candidate,
                "test/repo",
                self.revision,
                api=SimpleNamespace(
                    repo_info=lambda **kw: SimpleNamespace(sha="b" * 40)
                ),
            )
        expected = json.loads((candidate / "manifest.json").read_text())["files"]
        names = set(expected) | {"manifest.json", "sync.json"}

        class Api:
            published = False

            def repo_info(self, **kwargs):
                return SimpleNamespace(sha="c" * 40 if self.published else "a" * 40)

            def list_repo_files(self, *args, **kwargs):
                return list(names if self.published else self_parent)

            def create_commit(self, **kwargs):
                self.assert_parent = kwargs["parent_commit"]
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

        self_parent = set(self.parent_manifest["files"]) | {
            "manifest.json",
            "sync.json",
        }
        api = Api()
        report = publish_outcomes(candidate, "test/repo", self.revision, api=api)
        self.assertEqual(api.assert_parent, self.revision)
        self.assertEqual(report["status"], "complete")
