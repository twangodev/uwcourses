import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uwcourses_site import importer
from uwcourses_site.importer import chunks, grade_stats, MAX_CHUNK
from uwcourses_site.cli import check_assets
from uwcourses_site.search_projection import TABLES as SEARCH_TABLES


class PublicationTests(unittest.TestCase):
    def test_invalid_source_preserves_existing_generated_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / ".site"
            static = root / "static/data"
            output.mkdir()
            static.mkdir(parents=True)
            for path in [output, static]:
                (path / "keep").write_text("existing release")
            with (
                patch.object(importer, "ROOT", root),
                patch.object(
                    importer, "verify", side_effect=ValueError("invalid source")
                ),
                patch(
                    "sys.argv",
                    [
                        "import",
                        "--source",
                        str(root),
                        "--revision",
                        "revision123",
                        "--output",
                        str(output),
                    ],
                ),
            ):
                with self.assertRaisesRegex(ValueError, "invalid source"):
                    importer.main()
            self.assertTrue((output / "keep").exists())
            self.assertTrue((static / "keep").exists())

    def test_trace_fragments_preserve_full_unicode_record(self):
        record = {"output": "α🐾" * MAX_CHUNK}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            urls = chunks(root, "revision", "traces", "course", [record])
            parts = [json.loads((root / u.lstrip("/")).read_text())[0] for u in urls]
            restored = json.loads("".join(p["record_fragment"] for p in parts))
            self.assertEqual(restored, record)
            self.assertTrue(
                all((root / u.lstrip("/")).stat().st_size < MAX_CHUNK for u in urls)
            )

    def test_gpa_excludes_nonletter_outcomes(self):
        self.assertEqual(grade_stats([{"a": 1, "f": 1, "satisfactory": 100}])["gpa"], 2)
        self.assertIsNone(grade_stats([{"satisfactory": 100}])["gpa"])

    def test_asset_budget_rejects_oversized_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "large.json"
            with p.open("wb") as f:
                f.truncate(21 * 1024 * 1024)
            with self.assertRaisesRegex(ValueError, "20 MiB"):
                check_assets(Path(tmp))

    def test_built_dataset_integrity(self):
        db = sqlite3.connect(".site/import/site.sqlite")
        for (raw,) in db.execute("SELECT payload FROM courses"):
            c = json.loads(raw)
            self.assertTrue(c["requirements"]["nodes"])
            terms = [r["term_id"] for r in c["grades"]]
            self.assertEqual(len(terms), len(set(terms)))
            self.assertEqual(c["statistics"], grade_stats(c["grades"]))
            for urls in c["evidence"].values():
                self.assertTrue(
                    all(
                        (Path(".site/import/assets") / url.lstrip("/")).exists()
                        for url in urls
                    )
                )
        status = json.loads(
            db.execute("SELECT value FROM metadata WHERE key='status'").fetchone()[0]
        )
        self.assertEqual(
            status["current_instructors"],
            db.execute("SELECT count(*) FROM instructors WHERE current=1").fetchone()[
                0
            ],
        )
        db.close()

    def test_sql_roundtrip_and_d1_statement_limits(self):
        restored = sqlite3.connect(":memory:")
        restored.execute("BEGIN")
        statement = ""
        for part in sorted(Path(".site/import/sql").glob("*.sql")):
            self.assertLessEqual(part.stat().st_size, 16 * 1024 * 1024)
            with part.open() as file:
                for line in file:
                    statement += line
                    if sqlite3.complete_statement(statement):
                        self.assertLess(len(statement.encode()), 100000)
                        restored.execute(statement)
                        statement = ""
        self.assertFalse(statement.strip())
        source = sqlite3.connect(".site/import/site.sqlite")
        for table in [
            "courses",
            "instructors",
            "grades",
            "search",
            "course_numbers",
            "offerings",
            "grade_summaries",
            "reviews",
            *[
                table
                for table in SEARCH_TABLES
                if source.execute(
                    "SELECT 1 FROM sqlite_master WHERE name=?", (table,)
                ).fetchone()
            ],
        ]:
            self.assertEqual(
                restored.execute(f"SELECT count(*) FROM {table}").fetchone(),
                source.execute(f"SELECT count(*) FROM {table}").fetchone(),
            )
        self.assertEqual(
            restored.execute(
                "SELECT payload FROM courses ORDER BY length(payload) DESC LIMIT 1"
            ).fetchone(),
            source.execute(
                "SELECT payload FROM courses ORDER BY length(payload) DESC LIMIT 1"
            ).fetchone(),
        )
        self.assertEqual(
            restored.execute("SELECT value FROM metadata WHERE key='ready'").fetchone(),
            ("true",),
        )
        restored.close()
        source.close()


if __name__ == "__main__":
    unittest.main()
