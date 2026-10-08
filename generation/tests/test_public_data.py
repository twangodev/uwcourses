"""Public contracts: temporal identity, typed data and preserved evidence."""

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

from uwcourses.database import Database
from uwcourses.schema import archive
from uwcourses.history import ENRICHMENT_VIEWS, write_course
from uwcourses.models import canonical, digest
from uwcourses.public_data import (
    SCHEMAS,
    catalog_record,
    dataset_card,
    export_public,
    write_public,
    write_rows,
    selected_enrichments,
    grounded_learning_claims,
    enrich_fields,
)
from uwcourses.release import PUBLIC_VIEWS, write_parquet


class LegacySkillsTests(unittest.TestCase):
    def test_legacy_projection_does_not_claim_new_cited_skill_contract(self):
        from uwcourses_site.importer import course_learning_fields

        for skills in (
            ["Programming"],
            [
                {
                    "text": "Programming",
                    "evidence": [
                        {
                            "course_id": "COMPSCI 300",
                            "field": "description",
                            "quote": "Write programs.",
                        }
                    ],
                }
            ],
        ):
            with self.subTest(skills=skills):
                row = {
                    "job_id": "old",
                    "output_id": "old",
                    "model": "old",
                    "model_revision": "a" * 40,
                    "output_json": canonical(
                        {
                            "task_version": 16,
                            "sections": {
                                "search_profile": {
                                    "status": "valid",
                                    "value": {
                                        "summary": "Existing summary",
                                        "skills_taught": skills,
                                    },
                                }
                            },
                        }
                    ),
                }
                projected = enrich_fields(row)
                self.assertNotIn("llm_skills_evidence_json", projected)
                course = course_learning_fields(
                    {**projected, "course_id": "COMPSCI 300"}
                )
                self.assertEqual(course["llm_skills"], ["Programming"])
                self.assertEqual(course["llm_search_status"], "valid")
                self.assertEqual(course["llm_summary"], "Existing summary")


class PublicDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "archive.sqlite"
        self.db = Database(self.database)
        archive.create_all(self.db.connection)
        for statement in PUBLIC_VIEWS + ENRICHMENT_VIEWS:
            self.db.execute(statement)
        self.record = {
            "course_reference": {"subjects": ["COMPSCI"], "course_number": 300},
            "course_title": "Programming II",
            "description": "Classes and objects.",
            "prerequisites": {
                "prerequisites_text": "COMP SCI 200",
                "abstract_syntax_tree": "old parser",
            },
            "term_data": {"1262": {"grade_data": {"a": 1}}},
        }
        for run, when in [
            ("old", "2025-09-01T00:00:00+00:00"),
            ("new", "2026-09-01T00:00:00+00:00"),
        ]:
            self.db.execute(
                "INSERT INTO runs VALUES(?,?,?,?,?)",
                (run, "1272", when, "scrape", None),
            )
            record = json.loads(canonical(self.record))
            if run == "new":
                record["term_data"] = {}
                record["prerequisites"]["abstract_syntax_tree"] = "new parser"
            write_course(self.db, run, "COMPSCI 300", record)
            self.db.execute(
                "INSERT INTO terms VALUES(?,?,?)", (run, "1262", "Fall 2025")
            )
            self.db.execute(
                "INSERT INTO grades VALUES(?,?,?,?)",
                (
                    run,
                    "COMPSCI 300",
                    "1262",
                    canonical(
                        {
                            "a": 1 if run == "old" else 2,
                            "total": 2,
                            "instructors": ["Jane Example"],
                        }
                    ),
                ),
            )
        self.db.execute(
            'CREATE VIEW current_courses AS SELECT * FROM courses WHERE run_id="new"'
        )
        self.db.execute(
            "INSERT INTO offerings VALUES(?,?,?,?,?,?,?,?)",
            (
                "new",
                "offering-1",
                "1262",
                "COMPSCI 300",
                "123",
                "266",
                "{}",
                canonical(
                    {
                        "minimumCredits": 3,
                        "maximumCredits": 4,
                        "title": "Programming II",
                    }
                ),
            ),
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def add_job(
        self, job, selected, status="valid", title="Object oriented programming"
    ):
        graph = {
            "status": "parsed",
            "root": "exclude",
            "nodes": [
                {"id": "exclude", "kind": "not", "children": ["course"]},
                {
                    "id": "course",
                    "kind": "course",
                    "course": {"subjects": ["COMPSCI"], "course_number": 367},
                },
            ],
        }
        output = {
            "task_version": 4,
            "sections": {
                "search_profile": {
                    "status": status,
                    "value": {
                        "summary": {"text": title},
                        "topics": [{"text": "Objects"}],
                        "skills_taught": [],
                        "search_phrases": ["java programming"],
                    },
                },
                "requirements": {"status": status, "value": graph},
                "student_experience": {
                    "status": "insufficient_evidence",
                    "value": {"themes": []},
                },
            },
        }
        self.db.execute(
            "INSERT INTO enrichment_jobs VALUES(?,?,?,?,?,?,?)",
            (job, "new", "unified", "{}", 1, 1, "2026-09-01T00:00:00+00:00"),
        )
        self.db.execute("INSERT INTO release_enrichments VALUES(?,?)", (job, selected))
        self.db.execute(
            "INSERT INTO enrichment_outputs VALUES(?,?,?,?,?)",
            (job, "qwen/model", "a" * 40, canonical(output), "{}"),
        )
        self.db.execute(
            "INSERT INTO course_enrichment_runs VALUES(?,?,?,?)",
            (job, "new", "COMPSCI 300", job),
        )
        self.db.commit()

    def export(self):
        output = self.root / "export"
        counts = write_public(self.database, output, "release-test", "new")
        return output, counts

    def test_catalog_history_ignores_term_activity_and_parser_versions(self):
        output, counts = self.export()
        self.assertEqual(counts["catalog_versions"], 1)
        history = pq.read_table(output / "public/courses_history.parquet").to_pylist()
        self.assertEqual(len(history), 2)
        self.assertNotEqual(
            history[0]["record_version_id"], history[1]["record_version_id"]
        )
        self.assertEqual(
            history[0]["catalog_version_id"], history[1]["catalog_version_id"]
        )
        modified = json.loads(canonical(self.record))
        modified["description"] = "Now teaches Java."
        self.assertNotEqual(
            catalog_record("COMPSCI 300", modified)["catalog_version_id"],
            history[0]["catalog_version_id"],
        )
        modified = json.loads(canonical(self.record))
        modified["prerequisites"]["prerequisites_text"] = "COMP SCI 200 or 220"
        self.assertNotEqual(
            catalog_record("COMPSCI 300", modified)["catalog_version_id"],
            history[0]["catalog_version_id"],
        )

    def test_official_outcomes_and_cited_skills_survive_public_export(self):
        outcome = {
            "text": "Implement object-oriented programs.",
            "source": "enrollment",
            "source_url": "https://public.enroll.wisc.edu/api/search/v1/example",
            "observed_at": "2026-09-01T00:00:00+00:00",
            "term": "1272",
            "catalog_year": None,
        }
        record = {**self.record, "official_learning_outcomes": [outcome]}
        version_id = digest(record)
        self.db.execute(
            "INSERT INTO course_versions VALUES(?,?,?,?,?,?)",
            (
                version_id,
                300,
                record["course_title"],
                record["description"],
                canonical(record["prerequisites"]),
                canonical(record),
            ),
        )
        self.db.execute(
            "UPDATE course_snapshots SET version_id=? WHERE run_id=? AND course_id=?",
            (version_id, "new", "COMPSCI 300"),
        )
        self.add_job("selected", 1)
        row = self.db.execute(
            "SELECT output_json FROM enrichment_outputs WHERE output_id=?",
            ("selected",),
        ).fetchone()
        output = json.loads(row[0])
        claim = {
            "text": "Implement object-oriented programs",
            "evidence": [
                {
                    "field": "official_learning_outcomes",
                    "course_id": "COMPSCI 300",
                    "outcome_index": 0,
                    "quote": outcome["text"],
                    "source_url": outcome["source_url"],
                    **{
                        key: outcome.get(key)
                        for key in ("source", "observed_at", "term", "catalog_year")
                    },
                }
            ],
        }
        profile = output["sections"]["search_profile"]["value"]
        profile["skills_taught"] = [claim]
        profile["activity_tags"] = [
            {"label": "programming", "evidence": claim["evidence"]}
        ]
        self.db.execute(
            "UPDATE enrichment_outputs SET output_json=? WHERE output_id=?",
            (canonical(output), "selected"),
        )
        self.db.commit()
        destination, _ = self.export()
        course = pq.read_table(
            destination / "public/courses_current.parquet"
        ).to_pylist()[0]
        self.assertEqual(
            json.loads(course["official_learning_outcomes_json"]), [outcome]
        )
        observations = pq.read_table(
            destination / "public/course_observations.parquet"
        ).to_pylist()
        current_observation = next(
            item for item in observations if item["run_id"] == "new"
        )
        self.assertEqual(
            current_observation["catalog_version_id"], course["catalog_version_id"]
        )

        history = pq.read_table(
            destination / "public/courses_history.parquet"
        ).to_pylist()
        self.assertEqual(
            json.loads(
                next(item for item in history if item["run_id"] == "new")[
                    "official_learning_outcomes_json"
                ]
            ),
            [outcome],
        )
        versions = pq.read_table(
            destination / "public/catalog_versions.parquet"
        ).to_pylist()
        self.assertTrue(
            any(
                json.loads(item["official_learning_outcomes_json"]) == [outcome]
                for item in versions
            )
        )
        self.assertEqual(json.loads(course["llm_skills_evidence_json"]), [claim])
        self.assertEqual(course["llm_activity_tags"], ["programming"])
        self.assertEqual(
            json.loads(course["llm_activity_tags_json"]),
            [
                {
                    "label": "programming",
                    "text": "programming",
                    "evidence": claim["evidence"],
                }
            ],
        )

    def test_grounding_drops_stale_and_fabricated_claims(self):
        import copy

        url = "https://guide.wisc.edu/courses/comp_sci/"
        course = {
            "course_id": "COMPSCI 300",
            "source_url": url,
            "description": "Write programs using objects.",
            "official_learning_outcomes": [
                {"text": "Implement programs", "source_url": url, "source": "catalog"},
                {"text": "Analyze programs", "source_url": url, "source": "catalog"},
            ],
        }
        citation = {
            "course_id": "COMPSCI 300",
            "field": "official_learning_outcomes",
            "outcome_index": 0,
            "quote": "Implement programs",
            "source_url": url,
        }
        valid = {"label": "programming", "evidence": [citation]}
        self.assertEqual(
            grounded_learning_claims([valid], course, activities=True)[0]["text"],
            "programming",
        )
        cases = [
            {"outcome_index": 1},
            {"outcome_index": -1},
            {"outcome_index": True},
            {"source_url": "https://example.com/"},
            {"quote": "Fabricated"},
            {"course_id": "MATH 300"},
        ]
        for change in cases:
            with self.subTest(change=change):
                self.assertEqual(
                    grounded_learning_claims(
                        [{**valid, "evidence": [{**citation, **change}]}],
                        course,
                        activities=True,
                    ),
                    [],
                )
        reordered = copy.deepcopy(course)
        reordered["official_learning_outcomes"].reverse()
        self.assertEqual(
            grounded_learning_claims([valid], reordered, activities=True), []
        )
        self.assertEqual(
            grounded_learning_claims(
                [{**valid, "label": "easy"}], course, activities=True
            ),
            [],
        )
        description = {
            "text": "Program with objects",
            "evidence": [
                {
                    "course_id": "COMPSCI 300",
                    "field": "description",
                    "quote": "Write programs",
                    "source_url": url,
                }
            ],
        }
        self.assertEqual(len(grounded_learning_claims([description], course)), 1)
        self.assertEqual(
            grounded_learning_claims(
                [description], {**course, "description": "Different text"}
            ),
            [],
        )
        self.assertEqual(
            grounded_learning_claims(
                [description], {**course, "source_url": "https://example.com"}
            ),
            [],
        )

    def test_cross_run_changed_catalog_clears_entire_search_profile(self):
        self.add_job("selected", 1, title="OBSOLETELEARNING")
        self.db.execute(
            "UPDATE course_enrichment_runs SET run_id='old' WHERE job_id='selected'"
        )
        self.db.execute("DROP VIEW current_courses")
        self.db.execute("CREATE VIEW current_courses AS SELECT * FROM courses")
        output = json.loads(
            self.db.execute(
                "SELECT output_json FROM enrichment_outputs WHERE output_id='selected'"
            ).fetchone()[0]
        )
        output["sections"]["search_profile"]["value"]["topics"] = [
            {"text": "OBSOLETELEARNING"}
        ]
        output["sections"]["search_profile"]["value"]["search_phrases"] = [
            "OBSOLETELEARNING"
        ]
        self.db.execute(
            "UPDATE enrichment_outputs SET output_json=? WHERE output_id='selected'",
            (canonical(output),),
        )
        record = {
            **self.record,
            "official_learning_outcomes": [
                {
                    "text": "Analyze current data",
                    "source": "catalog",
                    "source_url": "https://guide.wisc.edu/courses/comp_sci/",
                }
            ],
        }
        version = digest(record)
        self.db.execute(
            "INSERT INTO course_versions VALUES(?,?,?,?,?,?)",
            (
                version,
                300,
                record["course_title"],
                record["description"],
                canonical(record["prerequisites"]),
                canonical(record),
            ),
        )
        self.db.execute(
            "UPDATE course_snapshots SET version_id=? WHERE run_id='new'", (version,)
        )
        self.db.commit()
        destination, _ = self.export()
        row = pq.read_table(destination / "public/courses_current.parquet").to_pylist()[
            0
        ]
        self.assertEqual(row["llm_search_status"], "stale_evidence")
        self.assertIsNone(row["llm_summary"])
        self.assertEqual(row["llm_topics"], [])
        self.assertEqual(row["llm_search_phrases"], [])
        self.assertNotIn("OBSOLETELEARNING", json.dumps(row, default=str))

    def test_cross_run_unchanged_catalog_retains_legacy_profile(self):
        self.add_job("selected", 1)
        self.db.execute(
            "UPDATE course_enrichment_runs SET run_id='old' WHERE job_id='selected'"
        )
        self.db.execute("DROP VIEW current_courses")
        self.db.execute("CREATE VIEW current_courses AS SELECT * FROM courses")
        self.db.commit()
        destination, _ = self.export()
        row = pq.read_table(destination / "public/courses_current.parquet").to_pylist()[
            0
        ]
        self.assertEqual(row["llm_search_status"], "valid")
        self.assertEqual(row["llm_summary"], "Object oriented programming")
        self.assertEqual(row["llm_topics"], ["Objects"])
        self.assertEqual(row["llm_search_phrases"], ["java programming"])

    def test_legacy_plain_skills_survive_reexport_and_serving_import(self):
        from uwcourses_site.importer import course_learning_fields

        self.add_job("selected", 1)
        output = json.loads(
            self.db.execute(
                "SELECT output_json FROM enrichment_outputs WHERE output_id='selected'"
            ).fetchone()[0]
        )
        output["sections"]["search_profile"]["value"]["skills_taught"] = ["Programming"]
        self.db.execute(
            "UPDATE enrichment_outputs SET output_json=? WHERE output_id='selected'",
            (canonical(output),),
        )
        self.db.commit()
        destination, _ = self.export()
        row = pq.read_table(destination / "public/courses_current.parquet").to_pylist()[
            0
        ]
        self.assertIsNone(row["llm_skills_evidence_json"])
        course = course_learning_fields(row)
        self.assertEqual(course["llm_skills"], ["Programming"])
        self.assertEqual(course["llm_search_status"], "valid")
        self.assertEqual(course["llm_search_phrases"], ["java programming"])

    def test_typed_grades_deduplicate_snapshots_and_keep_missing_counts_null(self):
        output, counts = self.export()
        self.assertEqual(counts["grades_latest"], 1)
        grades = pq.read_table(output / "public/grades_latest.parquet")
        self.assertTrue(pa.types.is_integer(grades.schema.field("a").type))
        self.assertTrue(pa.types.is_list(grades.schema.field("instructors").type))
        self.assertTrue(pa.types.is_timestamp(grades.schema.field("observed_at").type))
        row = grades.to_pylist()[0]
        self.assertEqual(
            (row["run_id"], row["a"], row["total"], row["b"]), ("new", 2, 2, None)
        )
        course = pq.read_table(output / "public/courses_current.parquet").to_pylist()[0]
        self.assertEqual((course["credits_min"], course["credits_max"]), (3, 4))
        self.assertEqual(course["credit_offering_ids"], ["offering-1"])
        self.assertEqual(course["llm_search_status"], "not_generated")
        self.assertEqual(course["llm_student_summary_status"], "not_generated")

    def test_only_selected_valid_sections_enter_search_and_requirement_graph(self):
        self.add_job("1-selected", 1)
        self.add_job("2-unselected", 0, title="Ignore this experiment")
        output, _ = self.export()
        course = pq.read_table(output / "public/courses_current.parquet").to_pylist()[0]
        self.assertEqual(course["llm_model_revision"], "a" * 40)
        self.assertEqual(course["llm_summary"], "Object oriented programming")
        self.assertIsNone(course["llm_experience_json"])
        ast = json.loads(course["llm_requirements_ast_json"])
        self.assertEqual(ast["nodes"][0]["kind"], "not")
        self.assertNotIn("Ignore this experiment", json.dumps(course, default=str))
        self.assertFalse((output / "serving").exists())

    def test_newer_selected_invalid_output_does_not_fall_back_to_stale_valid_output(
        self,
    ):
        self.add_job("1-selected", 1)
        self.add_job("2-selected", 1, status="invalid", title="Rejected unicorn")
        output, _ = self.export()
        row = pq.read_table(output / "public/courses_current.parquet").to_pylist()[0]
        self.assertEqual(row["llm_search_status"], "invalid")
        self.assertIsNone(row["llm_summary"])
        ast = json.loads(row["llm_requirements_ast_json"])
        self.assertEqual(len(ast["nodes"]), 1)
        self.assertEqual(ast["nodes"][0]["condition"], row["requirements_text"])
        self.assertEqual(ast["root"], ast["nodes"][0]["id"])

    def test_uncertain_requirement_tree_is_available_for_display(self):
        self.add_job("selected", 1, status="needs_review")
        output, _ = self.export()
        row = pq.read_table(output / "public/courses_current.parquet").to_pylist()[0]
        ast = json.loads(row["llm_requirements_ast_json"])
        self.assertEqual(row["llm_requirements_status"], "needs_review")
        self.assertEqual(ast["root"], "exclude")
        self.assertEqual(len(ast["nodes"]), 2)
        self.assertIsNone(row["llm_summary"])

    def test_empty_and_missing_trees_always_have_a_display_node(self):
        from uwcourses.public_data import display_requirements_ast

        for raw in (None, canonical({"status": "none", "nodes": [], "root": None})):
            for text in ("", "Instructor consent"):
                with self.subTest(raw=raw, text=text):
                    ast = json.loads(
                        display_requirements_ast(
                            {
                                "requirements_text": text,
                                "llm_requirements_ast_json": raw,
                            }
                        )
                    )
                    self.assertEqual(len(ast["nodes"]), 1)
                    self.assertEqual(ast["root"], ast["nodes"][0]["id"])
                    self.assertEqual(ast["nodes"][0]["evidence"], text)
                    self.assertTrue(ast["nodes"][0]["condition"])

    def test_slim_release_is_verified_repeatable_and_references_archive(self):
        from uwcourses.release import checksum, verify_release
        import shutil

        archive = self.root / "releases" / "archive-test"
        archive.mkdir(parents=True)
        self.db.commit()
        shutil.copyfile(self.database, archive / "coursemap.sqlite")
        (archive / "manifest.json").write_text(
            canonical(
                {
                    "run_id": "archive-test",
                    "source_run": "new",
                    "input_hash": "source-hash",
                    "schema_version": 4,
                    "files": {
                        "coursemap.sqlite": {
                            "sha256": checksum(archive / "coursemap.sqlite"),
                            "bytes": (archive / "coursemap.sqlite").stat().st_size,
                        }
                    },
                }
            )
        )
        target = export_public(self.root, "archive-test")
        manifest = verify_release(target)
        self.assertEqual(manifest["archive_release"], "archive-test")
        self.assertEqual(
            manifest["archive_manifest_sha256"], checksum(archive / "manifest.json")
        )
        self.assertEqual(manifest["public_tables"]["courses_current"], 1)
        self.assertFalse((target / "coursemap.sqlite").exists())
        self.assertEqual(export_public(self.root, "archive-test"), target)
        with self.assertRaises(ValueError):
            export_public(self.root, "../archive-test")
        (target / "public/schema.json").write_text("corrupted")
        with self.assertRaisesRegex(ValueError, "checksum"):
            export_public(self.root, "archive-test")

    def test_trace_export_preserves_thinking_tools_retries_and_unselected_outputs(self):
        self.add_job("1-selected", 1)
        self.add_job("2-experiment", 0, status="invalid")
        value = json.loads(
            self.db.execute(
                "SELECT output_json FROM enrichment_outputs WHERE output_id='2-experiment'"
            ).fetchone()[0]
        )
        value["provenance"] = {
            "conversation": [
                {
                    "kind": "response",
                    "parts": [
                        {"part_kind": "thinking", "content": "Recorded Qwen reasoning"},
                        {
                            "part_kind": "tool-call",
                            "tool_name": "get_course",
                            "args": {"course_id": "COMPSCI 200"},
                        },
                    ],
                }
            ],
            "recovery_events": [
                {
                    "conversation": [
                        {
                            "kind": "request",
                            "parts": [
                                {
                                    "part_kind": "retry-prompt",
                                    "content": "Missing exclusion",
                                }
                            ],
                        }
                    ]
                }
            ],
            "worker_version": 17,
        }
        self.db.execute(
            "UPDATE enrichment_outputs SET output_json=?,usage_json=? WHERE output_id='2-experiment'",
            (canonical(value), '{"completion_tokens":123}'),
        )
        self.db.commit()
        output, counts = self.export()
        rows = pq.read_table(output / "public/llm_traces.parquet").to_pylist()
        self.assertEqual(counts["llm_traces"], 2)
        self.assertFalse(rows[0]["has_conversation"])
        self.assertFalse(rows[1]["selected_for_release"])
        self.assertTrue(rows[1]["has_conversation"])
        self.assertEqual(json.loads(rows[1]["output_json"]), value)
        self.assertEqual(rows[1]["model_revision"], "a" * 40)
        self.assertEqual(json.loads(rows[1]["usage_json"])["completion_tokens"], 123)
        self.assertNotIn(
            "Recorded Qwen reasoning",
            json.dumps(
                pq.read_table(output / "public/courses_current.parquet").to_pylist(),
                default=str,
            ),
        )

    def test_large_trace_rows_are_byte_batched_without_losing_content(self):
        path = self.root / "bounded.parquet"
        schema = pa.schema([("output_json", pa.string())])
        rows = [{"output_json": "é" * n} for n in [20, 20, 60, 10]]
        self.assertEqual(write_rows(path, schema, iter(rows), max_text_bytes=100), 4)
        self.assertEqual(pq.read_metadata(path).num_row_groups, 3)
        self.assertEqual(pq.read_table(path).to_pylist(), rows)

    def test_selected_projection_does_not_retain_raw_traces(self):
        self.add_job("selected", 1)
        selected = selected_enrichments(self.db)
        self.assertTrue(selected)
        for value in selected.values():
            self.assertNotIn("output_json", value)
            self.assertIn("llm_search_status", value)
            self.assertEqual(value["llm_job_id"], "selected")

    def test_archive_export_byte_batches_large_artifacts_losslessly(self):
        database = self.root / "large-archive.sqlite"
        payloads = ["é" * (5 * 1024 * 1024)] * 2 + ["x" * (18 * 1024 * 1024), None]
        with sqlite3.connect(database) as db:
            db.execute("CREATE TABLE artifacts(id INTEGER, payload TEXT)")
            db.executemany("INSERT INTO artifacts VALUES(?,?)", enumerate(payloads))
        directory = self.root / "large-archive-tables"
        self.assertEqual(write_parquet(database, directory), {"artifacts": 4})
        path = directory / "artifacts.parquet"
        self.assertEqual(pq.read_metadata(path).num_row_groups, 4)
        self.assertEqual(
            pq.read_table(path).to_pylist(),
            [{"id": i, "payload": value} for i, value in enumerate(payloads)],
        )

    def test_empty_tables_keep_schema_and_card_has_one_default(self):
        self.db.execute("DELETE FROM grades")
        self.db.execute("DELETE FROM offerings")
        self.db.commit()
        output, counts = self.export()
        self.assertEqual(
            pq.read_table(output / "public/grades_latest.parquet").schema,
            SCHEMAS["grades_latest"],
        )
        current = pq.read_table(output / "public/courses_current.parquet").to_pylist()[
            0
        ]
        self.assertIsNone(current["credits_min"])
        card = dataset_card("new", counts, {"grades": 2})
        self.assertEqual(card.count("default: true"), 1)
        self.assertIn("config_name: archive_grades", card)
        self.assertIn("not affiliated with or endorsed", card)
        self.assertNotIn("license:", card)
        for name in counts:
            self.assertIn(f"path: public/{name}.parquet", card)

    def test_buildings_export_selected_snapshot_with_source_provenance(self):
        from uwcourses.models import digest

        data = json.loads(
            (Path(__file__).parent / "fixtures/campus-building.json").read_text()
        )
        for run in ("old", "new"):
            payload = {**data, "building_number": "0451B", "name": run + " name"}
            self.db.execute(
                "INSERT INTO observations VALUES(?,?,?,?,?,?,?,?)",
                (
                    run,
                    "buildings",
                    "buildings",
                    "366",
                    "https://map.wisc.edu/?initObj=0451B",
                    "2026-09-02T00:00:00+00:00",
                    digest(payload),
                    canonical(payload),
                ),
            )
        self.db.commit()
        output, counts = self.export()
        (row,) = pq.read_table(output / "public/buildings_current.parquet").to_pylist()
        self.assertEqual(counts["buildings_current"], 1)
        self.assertEqual(row["building_uid"], "uw-map:366")
        self.assertEqual(row["building_number"], "0451B")
        self.assertEqual(row["name"], "new name")
        self.assertEqual(json.loads(row["geometry_json"]), data["geojson"])
        self.assertEqual(json.loads(row["meta_json"]), data["meta"])
        self.assertEqual(row["longitude"], data["lnglat"][0])
        self.assertEqual(row["source_observed_at"].day, 2)
        self.assertEqual(row["observed_at"].day, 1)
        history = pq.read_table(
            output / "public/building_observations.parquet"
        ).to_pylist()
        self.assertEqual([r["run_id"] for r in history], ["new", "old"])
        self.assertEqual(json.loads(history[0]["payload_json"])["name"], "new name")
        self.assertEqual(json.loads(history[1]["payload_json"])["name"], "old name")
        card = dataset_card("new", counts)
        self.assertIn("config_name: buildings_current", card)
        self.assertIn("https://map.wisc.edu/buildings/", card)

    def test_section_grades_keep_coteachers_and_replace_old_assignments(self):
        for run, people in [
            ("old", [{"id": 1, "name": "Old Name"}, {"id": 3, "name": "Gone"}]),
            ("new", [{"id": 1, "name": "New Name"}, {"id": 2, "name": "New Name"}]),
        ]:
            payload = {
                "source_id": "source-course",
                "course_reference": self.record["course_reference"],
                "courseOfferings": [
                    {
                        "termCode": 1262,
                        "sections": [
                            {
                                "sectionNumber": 1,
                                "aCount": 0,
                                "total": 4,
                                "instructors": people,
                            }
                        ],
                    }
                ],
            }
            self.db.execute(
                "INSERT INTO observations VALUES(?,?,?,?,?,?,?,?)",
                (
                    run,
                    "madgrades",
                    "grades",
                    "source-course",
                    None,
                    "2026-09-01T00:00:00+00:00",
                    "hash",
                    canonical(payload),
                ),
            )
        self.db.commit()
        output, counts = self.export()

        def rows(name):
            return pq.read_table(output / f"public/{name}.parquet").to_pylist()

        self.assertEqual(counts["section_grades_latest"], 1)
        grade = rows("section_grades_latest")[0]
        self.assertEqual(grade["a"], 0)
        self.assertIsNone(grade["b"])
        self.assertEqual(grade["course_uid"], rows("courses_current")[0]["course_uid"])
        self.assertEqual(counts["grade_section_instructors"], 2)
        roster = {r["instructor_uid"]: r for r in rows("instructors")}
        teachers = [
            roster[r["instructor_uid"]] for r in rows("grade_section_instructors")
        ]
        self.assertEqual({r["source_instructor_id"] for r in teachers}, {"1", "2"})
        renamed = next(r for r in teachers if r["source_instructor_id"] == "1")
        self.assertEqual(renamed["name"], "New Name")
        self.assertEqual(renamed["first_observed_at"].year, 2025)
        self.assertEqual(renamed["last_observed_at"].year, 2026)
        self.assertEqual(
            {
                r["name"]
                for r in rows("instructor_aliases")
                if r["instructor_uid"] == renamed["instructor_uid"]
            },
            {"Old Name", "New Name"},
        )
        versions = {r["catalog_version_id"] for r in rows("catalog_versions")}
        self.assertTrue(
            all(
                r["catalog_version_id"] in versions for r in rows("course_observations")
            )
        )

    def test_section_identity_uses_class_number_not_course_local_label(self):
        for i, class_number in [(1, 101), (2, 202), (3, 101)]:
            if i > 1:
                self.db.execute(
                    "INSERT INTO offerings SELECT run_id,?,term_id,course_id,source_course_id,source_subject_id,course_reference_json,details_json FROM offerings WHERE offering_id='offering-1'",
                    (f"offering-{i}",),
                )
            self.db.execute(
                "INSERT INTO sections VALUES(?,?,?,?,?,?)",
                (
                    "new",
                    f"offering-{i}",
                    "LEC:001",
                    "LEC",
                    "001",
                    canonical(
                        {
                            "classUniqueId": {
                                "classNumber": class_number,
                                "termCode": "1262",
                            },
                            "enrollmentStatus": {"capacity": class_number},
                            "startDate": 0,
                        }
                    ),
                ),
            )
        self.db.commit()
        output, counts = self.export()
        self.assertEqual(counts["sections_current"], 2)
        self.assertEqual(counts["offering_sections"], 3)
        sections = pq.read_table(output / "public/sections_current.parquet").to_pylist()
        self.assertEqual({r["source_section_id"] for r in sections}, {"101", "202"})
        self.assertTrue(
            all(
                r["start_date"].year == 1970 and r["start_date"].tzinfo
                for r in sections
            )
        )

    def test_task_version_labels_survive_public_export(self):
        self.add_job("selected", 1)
        raw = self.db.execute(
            "SELECT output_json FROM enrichment_outputs WHERE output_id=?",
            ("selected",),
        ).fetchone()[0]
        value = json.loads(raw)
        value["task_version"] = "10-best-effort-1"
        self.db.execute(
            "UPDATE enrichment_outputs SET output_json=? WHERE output_id=?",
            (canonical(value), "selected"),
        )
        self.db.commit()
        output, _ = self.export()
        current = pq.read_table(output / "public/courses_current.parquet").to_pylist()[
            0
        ]
        self.assertEqual(current["llm_task_version"], "10-best-effort-1")
