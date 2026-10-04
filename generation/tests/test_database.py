"""Database adoption, snapshot isolation, and source-conflict regressions."""

import importlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

from sqlalchemy import event, insert, select

from uwcourses.database import Database
from uwcourses.jobs import Jobs
from uwcourses.migrate import upgrade_database
from uwcourses.models import canonical
from uwcourses.schema import observations, runs
from uwcourses.store import Store

BASELINE = importlib.import_module("uwcourses.migrations.versions.0001_baseline")


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def legacy_pipeline(self, version=2):
        path = self.root / "pipeline.sqlite"
        with sqlite3.connect(path) as db:
            db.executescript(BASELINE.PIPELINE)
            db.execute("PRAGMA user_version=1")
            db.execute(
                "INSERT INTO runs VALUES(?,?,?,?,?,?,?)",
                (
                    "course-run",
                    "1272",
                    "2026-09-01T00:00:00+00:00",
                    "2026-09-01T01:00:00+00:00",
                    "complete",
                    canonical({"sources": ["catalog"]}),
                    None,
                ),
            )
            course = {
                "course_reference": {"subjects": ["COMPSCI"], "course_number": 300},
                "course_title": "Programming II",
                "description": "Classes and objects.",
            }
            db.execute(
                "INSERT INTO observations VALUES(?,?,?,?,?,?,?,?)",
                (
                    "course-run",
                    "catalog",
                    "courses",
                    "COMPSCI 300",
                    "https://guide.wisc.edu/",
                    "2026-09-01T00:00:00+00:00",
                    "hash",
                    canonical(course),
                ),
            )
            if version == 2:
                db.execute("ALTER TABLE runs ADD COLUMN observed_at TEXT")
                db.execute(
                    "ALTER TABLE runs ADD COLUMN origin TEXT NOT NULL DEFAULT 'scrape'"
                )
                db.execute("ALTER TABLE runs ADD COLUMN source_revision TEXT")
                db.execute("UPDATE runs SET observed_at=started_at")
                db.execute("PRAGMA user_version=2")
            db.execute(
                "CREATE VIEW courses AS SELECT 'stale' AS title FROM observations"
            )
        return path

    def test_v2_baseline_preserves_records_and_replaces_stale_views(self):
        path = self.legacy_pipeline()
        with sqlite3.connect(path) as db:
            before = db.execute("SELECT * FROM observations").fetchall()
        store = Store(self.root)
        stamp = store.input_hash("course-run")
        self.assertEqual(
            store.db.execute("SELECT title FROM current_courses").fetchone()[0],
            "Programming II",
        )
        self.assertEqual(
            store.db.execute("SELECT version_num FROM alembic_version").fetchone()[0],
            "0003_snapshot_views",
        )
        self.assertEqual(store.db.execute("PRAGMA user_version").fetchone()[0], 2)
        store.close()
        with sqlite3.connect(path) as db:
            self.assertEqual(
                db.execute("SELECT * FROM observations").fetchall(), before
            )
        store = Store(self.root)
        self.addCleanup(store.close)
        self.assertEqual(store.input_hash("course-run"), stamp)

    def test_readonly_does_not_stamp_or_modify_old_database(self):
        path = self.legacy_pipeline()
        original = path.read_bytes()
        store = Store(self.root, readonly=True)
        try:
            self.assertEqual(
                store.records("course-run", "courses")["COMPSCI 300"]["course_title"],
                "Programming II",
            )
            with self.assertRaises(sqlite3.OperationalError):
                store.db.execute(
                    insert(runs).values(
                        run_id="write",
                        semester="1272",
                        started_at="now",
                        status="pending",
                        config_json="{}",
                    )
                )
        finally:
            store.close()
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse((self.root / "pipeline.sqlite-wal").exists())

    def test_failed_view_migration_rolls_back_stamp_and_schema(self):
        path = self.legacy_pipeline()
        db = Database(path, wal=True)
        self.addCleanup(db.close)

        def fail_view(connection, cursor, statement, parameters, context, executemany):
            if statement.startswith("CREATE VIEW subjects"):
                raise RuntimeError("interrupted migration")

        event.listen(db.engine, "before_cursor_execute", fail_view)
        with self.assertRaisesRegex(RuntimeError, "interrupted migration"):
            upgrade_database(db, "pipeline")
        event.remove(db.engine, "before_cursor_execute", fail_view)
        self.assertEqual(db.execute("SELECT title FROM courses").fetchone()[0], "stale")
        self.assertFalse(
            db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='alembic_version'"
            ).fetchone()
        )
        self.assertEqual(
            db.execute("SELECT count(*) FROM observations").fetchone()[0], 1
        )
        db.rollback()
        upgrade_database(db, "pipeline")
        self.assertEqual(
            db.execute("SELECT title FROM courses").fetchone()[0], "Programming II"
        )

    def test_processing_baseline_preserves_completed_results_and_cache(self):
        path = self.root / "processing.sqlite"
        with sqlite3.connect(path) as db:
            db.executescript(BASELINE.PROCESSING)
            db.execute(
                "INSERT INTO jobs VALUES('job','course-run','{}','complete','then')"
            )
            db.execute(
                "INSERT INTO results VALUES('job','COMPSCI 300','cache','{}','complete','{}','{}',NULL,2)"
            )
            db.execute("INSERT INTO output_cache VALUES('cache','{}','{}')")
            before = {
                name: db.execute(f"SELECT * FROM {name}").fetchall()
                for name in ("jobs", "results", "output_cache")
            }
        jobs = Jobs(self.root)
        jobs.close()
        with sqlite3.connect(path) as db:
            for name, rows in before.items():
                self.assertEqual(db.execute(f"SELECT * FROM {name}").fetchall(), rows)

    def test_core_and_driver_queries_share_rollback_and_read_snapshot(self):
        store = Store(self.root)
        self.addCleanup(store.close)
        run = store.new_run("1272", {})
        try:
            with store.db:
                store.db.execute(
                    insert(observations).values(
                        run_id=run,
                        source="catalog",
                        kind="subjects",
                        entity_id="CS",
                        source_url="url",
                        observed_at="then",
                        content_hash="hash",
                        payload_json='{"name":"CS"}',
                    )
                )
                self.assertEqual(
                    store.db.execute("SELECT count(*) FROM observations").fetchone()[0],
                    1,
                )
                raise RuntimeError("rollback")
        except RuntimeError:
            pass
        self.assertEqual(store.db.execute(select(observations)).fetchall(), [])
        store.db.rollback()
        store.db.execute("BEGIN")
        self.assertEqual(store.db.execute(select(observations)).fetchall(), [])
        writer = Store(self.root)
        try:
            writer.put(
                run,
                "catalog",
                {
                    "kind": "subjects",
                    "key": "CS",
                    "source_url": "url",
                    "payload": {"name": "CS"},
                },
            )
        finally:
            writer.close()
        self.assertEqual(store.db.execute(select(observations)).fetchall(), [])
        store.db.rollback()
        self.assertEqual(len(store.db.execute(select(observations)).fetchall()), 1)

    def test_auxiliary_run_does_not_replace_current_course_snapshot(self):
        self.legacy_pipeline()
        store = Store(self.root)
        self.addCleanup(store.close)
        run = store.new_run("1272", {"sources": ["buildings"]})
        store.finish(run)
        self.assertEqual(
            store.db.execute("SELECT run_id FROM current_courses").fetchone()[0],
            "course-run",
        )
        from uwcourses.lifecycle import require_snapshot

        with self.assertRaisesRegex(ValueError, "auxiliary"):
            require_snapshot(store, run)

    def test_auxiliary_history_exports_without_course_state(self):
        import test_pipeline
        from uwcourses.reconcile import reconcile, encode_state
        from uwcourses.release import write_database

        fixture = test_pipeline.PipelineTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.seed()
        store, run = fixture.store, fixture.run
        store.artifact(
            run,
            "source_state",
            encode_state(*reconcile(store, run)),
            store.input_hash(run),
            {},
        )
        store.finish(run)
        auxiliary = store.new_run("1272", {"sources": ["buildings"]})
        key, building = next(iter(store.records(run, "buildings").items()))
        store.put(
            auxiliary,
            "buildings",
            {
                "kind": "buildings",
                "key": key,
                "source_url": "https://map.wisc.edu/",
                "payload": building,
            },
        )
        store.finish(auxiliary)
        output = self.root / "archive.sqlite"
        write_database(store, run, output)
        with sqlite3.connect(output) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM runs").fetchone()[0], 2)
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM observations WHERE run_id=?", (auxiliary,)
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM course_snapshots WHERE run_id=?", (auxiliary,)
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                db.execute("SELECT run_id FROM current_courses").fetchone()[0], run
            )
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_source_conflicts_fail_and_term_precedence_is_explicit(self):
        store = Store(self.root)
        self.addCleanup(store.close)
        run = store.new_run("1272", {})
        for source, name in [("enrollment", "Fall"), ("madgrades", "Fall 2026")]:
            store.put(
                run,
                source,
                {
                    "kind": "terms",
                    "key": "1272",
                    "source_url": "url",
                    "payload": {"name": name},
                },
            )
        self.assertEqual(store.records(run, "terms")["1272"]["name"], "Fall 2026")
        self.assertEqual(
            store.records(run, "terms", "enrollment")["1272"]["name"], "Fall"
        )
        for source, name in [("catalog", "Computer Science"), ("other", "Other")]:
            store.put(
                run,
                source,
                {
                    "kind": "subjects",
                    "key": "CS",
                    "source_url": "url",
                    "payload": {"name": name},
                },
            )
        with self.assertRaisesRegex(ValueError, "Conflicting subjects"):
            store.records(run, "subjects")
        self.assertEqual(
            store.records(run, "subjects", "catalog")["CS"]["name"], "Computer Science"
        )

    def test_newer_or_unknown_schema_is_not_baselined(self):
        path = self.legacy_pipeline()
        with sqlite3.connect(path) as db:
            db.execute("PRAGMA user_version=99")
        with self.assertRaisesRegex(ValueError, "newer"):
            Store(self.root)
        with sqlite3.connect(path) as db:
            self.assertFalse(
                db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='alembic_version'"
                ).fetchone()
            )


if __name__ == "__main__":
    unittest.main()
