import importlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import select

from uwcourses.database import Database
from uwcourses.jobs import Jobs, file_lock
from uwcourses.migrate import upgrade_database
from uwcourses.models import canonical
from uwcourses.schema import observations, results
from uwcourses.storage import compact, fingerprint, report
from uwcourses.storage_codec import MAGIC, pack, unpack
from uwcourses.store import Store

BASELINE = importlib.import_module("uwcourses.migrations.versions.0001_baseline")


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.payload = canonical(
            {"text": "Course evidence and citations. 水\n" * 10000}
        )

    def test_codec_preserves_exact_text_and_skips_small_values(self):
        packed = pack(self.payload)
        self.assertIsInstance(packed, bytes)
        self.assertLess(len(packed), len(self.payload.encode()) // 10)
        self.assertEqual(unpack(packed), self.payload)
        self.assertEqual(pack(packed), packed)
        for value in (None, "{}", "plain legacy text", b"ordinary binary"):
            self.assertEqual(unpack(value), value)
            self.assertEqual(pack(value), value)
        with self.assertRaises(Exception):
            unpack(packed[:-8])

    def test_compressed_observations_support_core_raw_queries_and_json_views(self):
        store = Store(self.root)
        self.addCleanup(store.close)
        run = store.new_run("1272", {})
        course = {
            "course_reference": {"subjects": ["COMPSCI"], "course_number": 300},
            "course_title": "Programming II",
            "description": "Source evidence. " * 10000,
        }
        store.put(
            run,
            "catalog",
            {
                "kind": "courses",
                "key": "COMPSCI 300",
                "source_url": "url",
                "payload": course,
            },
        )
        store.finish(run)
        self.assertEqual(store.records(run, "courses")["COMPSCI 300"], course)
        self.assertEqual(
            store.db.execute("SELECT title FROM current_courses").fetchone()[0],
            "Programming II",
        )
        self.assertEqual(
            store.db.execute("SELECT subject_id FROM course_subjects").fetchone()[0],
            "COMPSCI",
        )
        typed = store.db.execute(select(observations.c.payload_json)).fetchone()
        raw = store.db.execute("SELECT payload_json FROM observations").fetchone()
        self.assertEqual(typed[0], canonical(course))
        self.assertEqual(raw[0], typed[0])
        self.assertEqual(dict(raw)["payload_json"], typed[0])
        self.assertEqual(tuple(raw), tuple(typed))
        with sqlite3.connect(self.root / "pipeline.sqlite") as db:
            value = db.execute("SELECT payload_json FROM observations").fetchone()[0]
            self.assertTrue(value.startswith(MAGIC))
        with self.assertRaises(sqlite3.IntegrityError):
            with store.db:
                store.db.execute(
                    "UPDATE observations SET payload_json=?", ("invalid json",)
                )

    def legacy_processing(self):
        path = self.root / "processing.sqlite"
        with sqlite3.connect(path) as db:
            db.executescript(BASELINE.PROCESSING)
            db.execute("INSERT INTO jobs VALUES('job','run','{}','complete','then')")
            db.execute(
                "INSERT INTO results VALUES('job','course','cache',?,'complete',?,'{}',NULL,1)",
                (self.payload, self.payload),
            )
            db.execute(
                "INSERT INTO output_cache VALUES('cache',?,'{}')", (self.payload,)
            )
        return path

    def test_compaction_preserves_results_and_release_bytes(self):
        path = self.legacy_processing()
        release = self.root / "releases/release-original/coursemap.sqlite"
        release.parent.mkdir(parents=True)
        release.write_bytes(b"untouched release")
        before = path.stat().st_size
        db = Database(path, readonly=True)
        original = fingerprint(db)
        db.close()
        summary = compact(self.root)
        self.assertLess(summary["databases"][0]["after_bytes"], before // 4)
        self.assertEqual(release.read_bytes(), b"untouched release")
        jobs = Jobs(self.root)
        try:
            self.assertEqual(fingerprint(jobs.db), original)
            value = jobs.db.execute(select(results.c.output_json)).fetchone()[0]
            self.assertEqual(value, self.payload)
            with jobs.db:
                jobs.db.execute(
                    "UPDATE results SET status='failed', attempts=attempts+1 WHERE job_id='job'"
                )
            self.assertEqual(
                jobs.db.execute("SELECT output_json FROM output_cache").fetchone()[0],
                self.payload,
            )
        finally:
            jobs.close()

    def test_pipeline_migration_preserves_hashes_artifacts_and_json_views(self):
        import test_database

        path = test_database.DatabaseTests.legacy_pipeline(self)
        course = {
            "course_reference": {"subjects": ["COMPSCI"], "course_number": 300},
            "course_title": "Programming II",
            "description": "Archived source text. " * 10000,
        }
        with sqlite3.connect(path) as db:
            db.execute("UPDATE observations SET payload_json=?", (canonical(course),))
            db.execute(
                "INSERT INTO artifacts VALUES('course-run','source_state','hash','{}',?)",
                (self.payload,),
            )
        db = Database(path, readonly=True)
        original = fingerprint(db)
        db.close()
        before = path.stat().st_size
        compact(self.root)
        self.assertLess(path.stat().st_size, before // 3)
        store = Store(self.root, readonly=True)
        try:
            self.assertEqual(fingerprint(store.db), original)
            self.assertEqual(
                store.get_artifact("course-run", "source_state"),
                json.loads(self.payload),
            )
            self.assertEqual(
                store.records("course-run", "courses")["COMPSCI 300"], course
            )
            self.assertEqual(
                store.db.execute("SELECT description FROM current_courses").fetchone()[
                    0
                ],
                course["description"],
            )
        finally:
            store.close()

    def test_failed_verification_rolls_back_migration_and_payloads(self):
        path = self.legacy_processing()
        db = Database(path)
        self.addCleanup(db.close)
        stamps = iter(("before", "changed"))
        with self.assertRaisesRegex(ValueError, "contents changed"):
            upgrade_database(db, "processing", fingerprint=lambda _: next(stamps))
        self.assertFalse(
            db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='alembic_version'"
            ).fetchone()
        )
        self.assertEqual(
            db.execute("SELECT output_json FROM results").fetchone()[0], self.payload
        )
        with sqlite3.connect(path) as raw:
            self.assertIsInstance(
                raw.execute("SELECT output_json FROM results").fetchone()[0], str
            )

    def test_report_does_not_count_external_links_or_change_databases(self):
        path = self.legacy_processing()
        original = path.read_bytes()
        (self.root / "external-model").symlink_to(path)
        entries = {entry["path"]: entry for entry in report(self.root)["entries"]}
        self.assertEqual(entries["external-model"]["bytes"], 0)
        self.assertFalse(entries["processing.sqlite"]["rebuildable"])
        self.assertEqual(path.read_bytes(), original)

    def test_compaction_rejects_active_job_locks(self):
        self.legacy_processing()
        with file_lock(self.root / "jobs/job.lock"):
            with self.assertRaisesRegex(RuntimeError, "active worker"):
                compact(self.root)

    def test_wal_compaction_reports_reclaimed_bytes_after_checkpoint(self):
        path = self.legacy_processing()
        with sqlite3.connect(path) as db:
            db.execute("PRAGMA journal_mode=WAL")
        value = compact(self.root)["databases"][0]
        self.assertEqual(value["after_bytes"], path.stat().st_size)
        self.assertLess(value["after_bytes"], value["before_bytes"] // 4)
        self.assertFalse(Path(str(path) + "-wal").exists())

    def test_compaction_rejects_databases_shared_through_hard_links(self):
        path = self.legacy_processing()
        (self.root / "retained-copy.sqlite").hardlink_to(path)
        original = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "linked database"):
            compact(self.root)
        self.assertEqual(path.read_bytes(), original)

    def test_storage_cli_report_is_readonly(self):
        from uwcourses.cli import main

        path = self.legacy_processing()
        original = path.read_bytes()
        with patch("builtins.print") as output:
            main(["--workspace", str(self.root), "storage"])
        self.assertEqual(
            json.loads(output.call_args.args[0])["workspace"], str(self.root)
        )
        self.assertEqual(path.read_bytes(), original)
