import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

from uwcourses.legacy import import_revision
from uwcourses.release import validate, write_database
from uwcourses.store import Store


class LegacyTests(unittest.TestCase):
    def test_history_import_is_atomic_idempotent_and_preserves_snapshot_grades(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "legacy"
            repository.mkdir()

            def git(*args):
                return (
                    subprocess.check_output(
                        ["git", "-C", str(repository), *args], stderr=subprocess.DEVNULL
                    )
                    .decode()
                    .strip()
                )

            git("init")
            course = {
                "course_reference": {"subjects": ["CS"], "course_number": 100},
                "course_title": "Test",
                "description": "Description",
                "prerequisites": None,
                "term_data": {"1254": {"grade_data": {"a": 10, "total": 10}}},
                "cumulative_grade_data": {"a": 10, "total": 10},
                "keywords": ["legacy"],
            }
            files = {
                "subjects.json": {"CS": "Computer Science"},
                "terms.json": {"1254": "Spring 2025"},
                "update.json": {"updated_on": "2025-01-01T00:00:00+00:00"},
                "course/CS_100.json": course,
                "instructors/Test.json": {
                    "name": "Test",
                    "email": None,
                    "official_name": None,
                    "department": None,
                    "position": None,
                },
            }

            def commit():
                for path, value in files.items():
                    target = repository / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(json.dumps(value))
                git("add", ".")
                git(
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.com",
                    "commit",
                    "-qm",
                    "snapshot",
                )
                return git("rev-parse", "HEAD")

            older = commit()
            files["update.json"]["updated_on"] = "2025-02-01T00:00:00+00:00"
            newer = commit()
            store = Store(root / "workspace")
            try:
                new = import_revision(store, repository, newer)["run_id"]
                self.assertIsNone(store.stage_status(new, "derive"))
                self.assertEqual(validate(store, new)["courses"], 1)
                import_revision(store, repository, older)
                self.assertEqual(
                    store.db.execute("SELECT run_id FROM current_courses").fetchone()[
                        0
                    ],
                    new,
                )
                self.assertEqual(
                    import_revision(store, repository, older)["status"],
                    "already_imported",
                )
                self.assertEqual(
                    store.db.execute("SELECT count(*) FROM runs").fetchone()[0], 2
                )
                public = root / "public.sqlite"
                write_database(store, new, public)
                with sqlite3.connect(public) as db:
                    self.assertEqual(
                        db.execute("SELECT count(*) FROM grades").fetchone()[0], 2
                    )
                    self.assertEqual(
                        json.loads(
                            db.execute(
                                "SELECT distribution_json FROM current_grades"
                            ).fetchone()[0]
                        )["total"],
                        10,
                    )
                    self.assertFalse(db.execute("PRAGMA foreign_key_check").fetchall())
                    self.assertEqual(
                        db.execute(
                            "SELECT source_revision FROM runs WHERE run_id=?", (new,)
                        ).fetchone()[0],
                        newer,
                    )
                live = store.new_run("1272", {})
                store.finish(live)
                self.assertEqual(
                    store.db.execute(
                        "SELECT run_id FROM runs WHERE status='complete' ORDER BY observed_at DESC LIMIT 1"
                    ).fetchone()[0],
                    live,
                )
                files["course/CS_100.json"]["course_reference"]["subjects"] = [
                    "MISSING"
                ]
                broken = commit()
                with self.assertRaisesRegex(ValueError, "Missing subject"):
                    import_revision(store, repository, broken)
                self.assertEqual(
                    store.db.execute("SELECT count(*) FROM runs").fetchone()[0], 3
                )
            finally:
                store.close()

    def test_existing_v1_database_migrates_observation_date(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            run = store.new_run("1272", {})
            store.finish(run)
            expected = store.run(run)["started_at"]
            store.close()
            with sqlite3.connect(Path(directory) / "pipeline.sqlite") as db:
                db.execute("DROP TABLE alembic_version")
                for (name,) in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='view'"
                ).fetchall():
                    db.execute(f"DROP VIEW {name}")
                for column in ["observed_at", "origin", "source_revision"]:
                    db.execute(f"ALTER TABLE runs DROP COLUMN {column}")
                db.execute("PRAGMA user_version=1")
            store = Store(directory)
            try:
                self.assertEqual(store.run(run)["observed_at"], expected)
                self.assertEqual(store.run(run)["origin"], "scrape")
                self.assertEqual(
                    store.db.execute("PRAGMA user_version").fetchone()[0], 2
                )
            finally:
                store.close()
