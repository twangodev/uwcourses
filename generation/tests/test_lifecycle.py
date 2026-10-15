"""Recovery and isolation guarantees for source snapshots and enrichment."""

import json
import sqlite3
import unittest
from unittest.mock import patch

import test_pipeline
from uwcourses.cli import code_hash
from uwcourses.jobs import Jobs
from uwcourses.lifecycle import scrape, release
from uwcourses.models import canonical
from uwcourses.profiles import ModelProfile, load_profile, lock_profiles
from uwcourses.release import verify_release, publish
from uwcourses.store import Store, SOURCES


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_pipeline.PipelineTests()
        self.fixture.setUp()
        self.store = self.fixture.store
        self.run = self.fixture.run
        self.root = self.store.root
        self.fixture.seed()
        self.profile = ModelProfile(
            model="test/model", revision="a" * 40, base_url="http://127.0.0.1:8003/v1"
        )
        self.task = self.root / "task.json"
        self.task.write_text(
            canonical(
                {
                    "name": "test",
                    "version": 1,
                    "prompt": "Ground in source",
                    "schema": {
                        "type": "object",
                        "required": ["summary"],
                        "properties": {"summary": {"type": "string"}},
                        "additionalProperties": False,
                    },
                }
            )
        )

    def tearDown(self):
        self.fixture.tearDown()

    def core(self):
        with self.store.db:
            self.store.db.execute("DELETE FROM observations WHERE source='instructors'")
            self.store.db.execute("DELETE FROM artifacts")
            self.store.db.execute(
                "UPDATE stages SET status='pending' WHERE stage IN ('instructors','derive','export')"
            )
            self.store.db.execute(
                "UPDATE runs SET config_json=? WHERE run_id=?",
                (
                    canonical(
                        {
                            "workflow": "snapshot-v1",
                            "code_hash": code_hash(),
                            "sources": list(SOURCES[:3]),
                        }
                    ),
                    self.run,
                ),
            )
        return scrape(self.store, self.run)

    def create_job(self, jobs, run=None):
        with patch("uwcourses.jobs.load_profile", return_value=self.profile):
            return jobs.create(
                run or self.run, "unused", "enrichment", self.task, limit=0
            )

    def test_historical_graph_state_remains_readable(self):
        from uwcourses.release import snapshot_state

        self.core()
        original = snapshot_state(self.store, self.run)
        with self.store.db:
            self.store.db.execute(
                "UPDATE artifacts SET name='graph' WHERE run_id=? AND name='source_state'",
                (self.run,),
            )
        self.assertEqual(snapshot_state(self.store, self.run), original)

    def test_cli_has_no_website_build_commands(self):
        import io
        from uwcourses.cli import parser

        cli = parser()
        for argv in (
            ["derive", "run"],
            ["derive-resume", "build"],
            ["export", "run"],
            ["release", "run", "--build", "build"],
        ):
            with self.subTest(argv=argv), patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as error:
                    cli.parse_args(argv)
                self.assertEqual(error.exception.code, 2)
        self.assertEqual(cli.parse_args(["release", "run"]).command, "release")

    def test_missing_task_schema_and_generic_reuse_fail_before_job_creation(self):
        self.core()
        jobs = Jobs(self.root)
        try:
            task = json.loads(self.task.read_text())
            del task["schema"]
            self.task.write_text(canonical(task))
            with self.assertRaisesRegex(ValueError, "JSON schema"):
                self.create_job(jobs)
            task["schema"] = {}
            self.task.write_text(canonical(task))
            with (
                patch("uwcourses.jobs.load_profile", return_value=self.profile),
                self.assertRaisesRegex(ValueError, "Reuse requires unified"),
            ):
                jobs.create(
                    self.run,
                    "unused",
                    "enrichment",
                    self.task,
                    reuse_job_ids=["missing"],
                )
            self.assertEqual(
                jobs.db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0
            )
        finally:
            jobs.close()

    def test_explicit_repair_selection_ignores_sample_limit(self):
        from uwcourses.repair import create_repair

        self.core()
        jobs = Jobs(self.root)
        try:
            parent = self.create_job(jobs)
            spec = json.loads(jobs.status(parent)["spec_json"])
            spec["task"]["workflow"] = "unified_v1"
            rejected = canonical({"sections": {"requirements": {"status": "invalid"}}})
            with jobs.db:
                jobs.db.execute(
                    "UPDATE jobs SET status='complete',spec_json=? WHERE job_id=?",
                    (canonical(spec), parent),
                )
                jobs.db.execute(
                    "UPDATE results SET status='complete',output_json=? WHERE job_id=?",
                    (rejected, parent),
                )
                row = jobs.db.execute(
                    "SELECT cache_key,input_json FROM results WHERE job_id=? LIMIT 1",
                    (parent,),
                ).fetchone()
                jobs.db.execute(
                    "INSERT INTO results(job_id,course_id,cache_key,input_json,status,output_json) "
                    "VALUES(?,?,?,?,?,?)",
                    (
                        parent,
                        "EXTRA 999",
                        row[0] + "extra",
                        row[1],
                        "complete",
                        rejected,
                    ),
                )
            selected = [
                r[0]
                for r in jobs.db.execute(
                    "SELECT course_id FROM results WHERE job_id=?", (parent,)
                )
            ]
            self.assertGreater(len(selected), 1)
            with patch("uwcourses.repair.load_profile", return_value=self.profile):
                repair = create_repair(
                    jobs, parent, "unused", "enrichment", limit=1, course_ids=selected
                )
            actual = {
                r[0]
                for r in jobs.db.execute(
                    "SELECT course_id FROM results WHERE job_id=?", (repair,)
                )
            }
            self.assertEqual(actual, set(selected))
        finally:
            jobs.close()

    def test_summary_reuse_keeps_catalog_and_student_ownership_separate(self):
        import copy
        from uwcourses.student_summary import summary_seeds
        from uwcourses.models import digest

        self.core()
        jobs = Jobs(self.root)
        try:
            catalog = self.create_job(jobs)
            course = jobs.db.execute(
                "SELECT course_id FROM results WHERE job_id=? ORDER BY course_id LIMIT 1",
                (catalog,),
            ).fetchone()[0]
            source = self.store.records(self.run, "courses")[course]
            original = {
                "model": self.profile.model,
                "model_revision": self.profile.revision,
                "task_version": json.loads(self.task.read_text())["version"],
                "sections": {
                    "search_profile": {
                        "status": "valid",
                        "value": source["description"],
                    }
                },
            }
            with jobs.db:
                jobs.db.execute(
                    "UPDATE jobs SET status='complete' WHERE job_id=?", (catalog,)
                )
                jobs.db.execute(
                    "UPDATE results SET status='complete',output_json=? WHERE job_id=?",
                    (canonical(original), catalog),
                )
            task = json.loads(self.task.read_text())
            task["workflow"] = "student_summary_v1"
            self.task.write_text(canonical(task))
            with (
                patch("uwcourses.jobs.load_profile", return_value=self.profile),
                patch("uwcourses.student_context.StudentContext") as context,
            ):
                context.return_value.get.side_effect = lambda key: {"course_id": key}
                student = jobs.create(
                    self.run,
                    "unused",
                    "enrichment",
                    self.task,
                    course_ids=[course],
                    reuse_job_ids=[catalog],
                )
            previous = copy.deepcopy(original)
            previous["sections"]["search_profile"]["value"] = None
            previous["sections"]["student_summary"] = {
                "status": "valid",
                "value": {"text": source["course_title"]},
            }
            with jobs.db:
                jobs.db.execute(
                    "UPDATE jobs SET status='complete' WHERE job_id=?", (student,)
                )
                jobs.db.execute(
                    "UPDATE results SET status='complete',output_json=? WHERE job_id=?",
                    (canonical(previous), student),
                )
            seed = summary_seeds(jobs, [student, catalog], self.run)[course]
            self.assertEqual(seed["job_id"], student)
            self.assertEqual(
                seed["output"]["sections"]["search_profile"],
                original["sections"]["search_profile"],
            )
            self.assertEqual(
                seed["output"]["sections"]["student_summary"],
                previous["sections"]["student_summary"],
            )
            origin = seed["section_origins"]["search_profile"]
            self.assertEqual(origin["job_id"], catalog)
            self.assertEqual(
                origin["section_hash"], digest(original["sections"]["search_profile"])
            )
            stored = jobs.db.execute(
                "SELECT output_json FROM results WHERE job_id=? AND course_id=?",
                (student, course),
            ).fetchone()[0]
            self.assertEqual(json.loads(stored), previous)
        finally:
            jobs.close()

    def test_partial_summary_reuse_freezes_completed_results(self):
        from uwcourses.student_summary import summary_seeds

        self.core()
        jobs = Jobs(self.root)
        try:
            parent = self.create_job(jobs)
            original = {
                "sections": {
                    "student_summary": {
                        "status": "invalid",
                        "value": {"draft": "first"},
                    }
                }
            }
            with jobs.db:
                jobs.db.execute(
                    "UPDATE jobs SET status='running' WHERE job_id=?", (parent,)
                )
                jobs.db.execute(
                    "UPDATE results SET status='complete',output_json=? WHERE job_id=?",
                    (canonical(original), parent),
                )
                jobs.db.execute(
                    "INSERT INTO results(job_id,course_id,cache_key,input_json,status) VALUES(?, 'unfinished', 'unused', '{}', 'pending')",
                    (parent,),
                )
            with self.assertRaises(ValueError):
                summary_seeds(jobs, [parent], self.run)
            seeds = summary_seeds(jobs, [parent], self.run, allow_partial=True)
            self.assertNotIn("unfinished", seeds)
            with self.assertRaises(ValueError):
                summary_seeds(jobs, [parent], "different-snapshot", allow_partial=True)
            task = json.loads(self.task.read_text())
            task["workflow"] = "student_summary_v1"
            self.task.write_text(canonical(task))
            with (
                patch("uwcourses.jobs.load_profile", return_value=self.profile),
                patch("uwcourses.student_context.StudentContext") as context,
            ):
                context.return_value.get.return_value = {"course_id": "COMPSCI 300"}

                def create():
                    return jobs.create(
                        self.run,
                        "unused",
                        "enrichment",
                        self.task,
                        limit=0,
                        reuse_job_ids=[parent],
                        allow_partial_reuse=True,
                    )

                child = create()
                self.assertEqual(child, create())
                frozen = jobs.db.execute(
                    "SELECT input_json FROM results WHERE job_id=?", (child,)
                ).fetchone()[0]
                original["sections"]["student_summary"]["value"]["draft"] = "second"
                with jobs.db:
                    jobs.db.execute(
                        "UPDATE results SET output_json=? WHERE job_id=? AND status='complete'",
                        (canonical(original), parent),
                    )
                self.assertNotEqual(child, create())
                self.assertEqual(
                    frozen,
                    jobs.db.execute(
                        "SELECT input_json FROM results WHERE job_id=?", (child,)
                    ).fetchone()[0],
                )
            self.assertEqual(jobs.status(parent)["status"], "running")
        finally:
            jobs.close()

    def test_source_only_release_and_publish_during_scrape_lock(self):
        with patch(
            "huggingface_hub.HfApi",
            side_effect=AssertionError("No model metadata needed"),
        ):
            self.core()
            before = self.store.input_hash(self.run)
            with self.store.lock():
                readonly = Store(self.root, readonly=True)
                try:
                    target = release(readonly, self.run)
                    manifest = verify_release(target)
                    self.assertNotIn("website_included", manifest)
                    self.assertFalse((target / "web").exists())
                    self.assertFalse((target / "serving").exists())
                    self.assertNotIn("processing_builds", manifest["tables"])
                    self.assertEqual(manifest["tables"]["course_snapshots"], 1)
                    self.assertGreater(manifest["tables"]["meetings"], 0)
                    self.assertEqual(release(readonly, self.run), target)
                    hub = test_pipeline.FakeHub(self.root)
                    result = publish(
                        readonly, target.name, "owner/data", hub, hub.download
                    )
                    self.assertIn("revision", result)
                    self.assertIn("public/courses_current.parquet", hub.files["main"])
                    self.assertIn(b"default: true", hub.files["main"]["README.md"])
                    self.assertNotIn(b"archive_grades", hub.files["main"]["README.md"])
                    with self.assertRaises(sqlite3.OperationalError):
                        readonly.db.execute("DELETE FROM runs")
                finally:
                    readonly.close()
        self.assertEqual(self.store.input_hash(self.run), before)
        self.assertIsNone(self.store.run(self.run)["revision"])
        self.assertIsNone(self.store.stage_status(self.run, "derive"))

    def test_resume_concurrency_override_preserves_job_spec_and_records_execution(self):
        from concurrent.futures import ThreadPoolExecutor

        self.core()
        jobs = Jobs(self.root)
        try:
            job = self.create_job(jobs)
            original = jobs.status(job)["spec_json"]
            with self.assertRaisesRegex(ValueError, "Concurrency"):
                jobs.run(job, worker=lambda *args: ({}, {}), concurrency=0)
            with self.assertRaisesRegex(ValueError, "Request timeout"):
                jobs.run(job, worker=lambda *args: ({}, {}), request_timeout=0)

            def worker(profile, *args):
                self.assertEqual(profile["request_timeout_seconds"], 1800)
                return {"summary": "Programming"}, {}

            with patch(
                "uwcourses.jobs.ThreadPoolExecutor", wraps=ThreadPoolExecutor
            ) as pool:
                jobs.run(
                    job,
                    worker=worker,
                    concurrency=384,
                    request_timeout=1800,
                )
                pool.assert_called_once_with(max_workers=384)
            self.assertEqual(jobs.status(job)["spec_json"], original)
            output = json.loads(
                jobs.db.execute(
                    "SELECT output_json FROM results WHERE job_id=?", (job,)
                ).fetchone()[0]
            )
            self.assertEqual(output["provenance"]["client_concurrency"], 384)
            self.assertEqual(output["provenance"]["request_timeout_seconds"], 1800)
        finally:
            jobs.close()

    def test_failed_source_does_not_block_other_sources_and_resumes(self):
        with self.store.db:
            self.store.db.execute("UPDATE stages SET status='pending'")
            self.store.db.execute(
                "UPDATE runs SET config_json=?",
                (
                    canonical(
                        {
                            "workflow": "snapshot-v1",
                            "code_hash": code_hash(),
                            "sources": list(SOURCES[:3]),
                        }
                    ),
                ),
            )
        called = []

        def worker(store, run, source):
            called.append(source)
            if source == "madgrades":
                raise RuntimeError("unavailable")
            store.stage(run, source, "complete")

        with patch("uwcourses.cli.execute_source", side_effect=worker):
            with self.assertRaisesRegex(RuntimeError, "madgrades"):
                scrape(self.store, self.run)
        self.assertEqual(called, list(SOURCES[:3]))
        called.clear()

        def resume(store, run, source):
            called.append(source)
            store.stage(run, source, "complete")

        with patch("uwcourses.cli.execute_source", side_effect=resume):
            scrape(self.store, self.run)
        self.assertEqual(called, ["madgrades"])

    def test_enrichment_failure_resume_cache_and_explicit_selection(self):
        self.core()
        jobs = Jobs(self.root)
        try:
            job = self.create_job(jobs)
            with self.assertRaises(RuntimeError):
                jobs.run(
                    job,
                    worker=lambda *args: (_ for _ in ()).throw(
                        ValueError("bad output")
                    ),
                )
            self.assertEqual(
                jobs.db.execute(
                    "SELECT error FROM results WHERE job_id=?", (job,)
                ).fetchone()[0],
                "ValueError: bad output",
            )
            with self.assertRaisesRegex(ValueError, "completed enrichment"):
                release(self.store, self.run, enrichment_ids=[job])
            calls = []

            def worker(*args):
                calls.append(args)
                return {"summary": "Grounded summary"}, {"completion_tokens": 3}

            self.assertEqual(jobs.run(job, worker)["status"], "complete")
            jobs.run(job, worker)
            self.assertEqual(len(calls), 1)
            path = release(self.store, self.run, enrichment_ids=[job])
            manifest = verify_release(path)
            self.assertEqual(manifest["tables"]["course_enrichment_runs"], 1)
            with sqlite3.connect(path / "coursemap.sqlite") as db:
                spec = db.execute("SELECT spec_json FROM enrichment_jobs").fetchone()[0]
                self.assertNotIn("127.0.0.1", spec)
                self.assertFalse(db.execute("PRAGMA foreign_key_check").fetchall())
            other = self.store.new_run("1272", {})
            self.fixture.seed(other)
            self.store.finish(other)
            reused = self.create_job(jobs, other)
            jobs.run(reused, worker)
            self.assertEqual(
                len(calls),
                1,
                "unchanged courses reuse validated outputs across snapshots",
            )
            task = json.loads(self.task.read_text())
            task["version"] = 2
            self.task.write_text(canonical(task))
            changed = self.create_job(jobs, other)
            jobs.run(changed, worker)
            self.assertEqual(len(calls), 2, "task changes invalidate cached outputs")
        finally:
            jobs.close()

    def test_unified_dependency_cache_and_dataset_sections(self):
        from pathlib import Path
        from uwcourses.course_context import CourseContext

        task = (
            Path(__file__).resolve().parents[2]
            / "inference/tasks/course_enrichment.json"
        )
        jobs = Jobs(self.root)
        calls = []
        runs = []
        try:
            for description in [
                "First prerequisite description",
                "Changed prerequisite description",
                "Changed prerequisite description",
            ]:
                run = self.store.new_run("1272", {})
                self.fixture.seed(run)
                dependency = self.store.records(run, "courses")["COMPSCI 300"].copy()
                dependency["course_reference"] = {
                    "subjects": ["COMPSCI"],
                    "course_number": 200,
                }
                dependency["description"] = description
                self.store.put(
                    run,
                    "catalog",
                    {
                        "kind": "courses",
                        "key": "COMPSCI 200",
                        "source_url": "https://guide.wisc.edu/courses/comp_sci/",
                        "payload": dependency,
                    },
                )
                self.store.finish(run)
                context = CourseContext(self.store, run)
                with patch("uwcourses.jobs.load_profile", return_value=self.profile):
                    job = jobs.create(
                        run, "unused", "unified", task, course_ids=["CS 300"]
                    )

                def worker(*args):
                    calls.append(run)
                    return {
                        "model": self.profile.model,
                        "model_revision": self.profile.revision,
                        "sections": {
                            "search_profile": {
                                "status": "valid",
                                "value": {"summary": "fixture"},
                            },
                            "requirements": {
                                "status": "invalid",
                                "value": None,
                                "candidate": {"root": "missing"},
                                "error": "Missing root",
                            },
                        },
                        "provenance": {
                            "dependencies": {
                                "COMPSCI 200": context.fingerprint("COMPSCI 200")
                            }
                        },
                    }, {}

                self.assertEqual(jobs.run(job, worker)["status"], "complete")
                runs.append(run)
            self.assertEqual(calls, runs[:2])
            value = json.loads(
                jobs.db.execute(
                    "SELECT output_json FROM results WHERE job_id=?", (job,)
                ).fetchone()[0]
            )
            self.assertEqual(value["provenance"]["generated_from_snapshot"], runs[1])
            path = release(self.store, run, enrichment_ids=[job])
            manifest = verify_release(path)
            self.assertEqual(manifest["tables"]["enrichment_output_sections"], 4)
            self.assertEqual(manifest["tables"]["course_enrichment_runs"], 3)
            self.assertIn(self.profile.served_model, (path / "README.md").read_text())
            with sqlite3.connect(path / "coursemap.sqlite") as db:
                rows = db.execute(
                    "SELECT section,status,model,model_revision,value_json,candidate_json FROM current_enrichment_sections ORDER BY section"
                ).fetchall()
            self.assertEqual(
                rows[0][:4],
                ("requirements", "invalid", self.profile.model, self.profile.revision),
            )
            self.assertIsNone(rows[0][4])
            self.assertEqual(json.loads(rows[0][5]), {"root": "missing"})
            self.assertEqual(rows[1][1], "valid")
        finally:
            jobs.close()

    def test_partial_resume_only_retries_failed_courses(self):
        original = self.store.records(self.run, "courses")["COMPSCI 300"]
        copied = json.loads(canonical(original))
        copied["course_reference"]["course_number"] = 301
        self.store.put(
            self.run,
            "catalog",
            {
                "kind": "courses",
                "key": "COMPSCI 301",
                "payload": copied,
                "source_url": "https://example.org",
            },
        )
        self.core()
        jobs = Jobs(self.root)
        try:
            job = self.create_job(jobs)
            calls = []

            def worker(profile, task, payload):
                number = payload["course_reference"]["course_number"]
                calls.append(number)
                if number == 301:
                    raise ValueError("failed")
                return {"summary": "OK"}, {}

            with self.assertRaises(RuntimeError):
                jobs.run(job, worker)

            def retry(profile, task, payload):
                calls.append(payload["course_reference"]["course_number"])
                return {"summary": "OK"}, {}

            jobs.run(job, retry)
            self.assertEqual(calls.count(300), 1)
            self.assertEqual(calls.count(301), 2)
        finally:
            jobs.close()

    def test_unresolved_enrollment_hit_preserves_raw_offering(self):
        from uwcourses.reconcile import reconcile

        before = self.store.records(self.run, "offerings")
        self.assertTrue(before)
        with patch("uwcourses.enrollment.apply_enrollment", return_value=None):
            *_, unmatched = reconcile(self.store, self.run)
        self.assertEqual(set(unmatched["offerings"]), set(before))
        self.assertEqual(self.store.records(self.run, "offerings"), before)

    def test_offline_model_fails_before_scheduling_courses(self):
        import requests

        self.core()
        jobs = Jobs(self.root)
        try:
            job = self.create_job(jobs)
            with (
                patch(
                    "uwcourses.jobs.requests.get",
                    side_effect=requests.ConnectionError,
                ),
                patch("uwcourses.agents.generate_generic") as inference,
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "Inference server unavailable"
                ):
                    jobs.run(job)
                inference.assert_not_called()
            self.assertEqual(jobs.status(job)["counts"], {"pending": 1})
        finally:
            jobs.close()

    def test_http_limits_are_configurable_and_keep_backoff(self):
        from uwcourses.crawl import http_settings

        settings = http_settings({})
        self.assertEqual(settings["CONCURRENT_REQUESTS"], 32)
        self.assertEqual(settings["CONCURRENT_REQUESTS_PER_DOMAIN"], 16)
        self.assertTrue(settings["AUTOTHROTTLE_ENABLED"])
        self.assertEqual(settings["AUTOTHROTTLE_MAX_DELAY"], 60)
        custom = http_settings(
            {
                "http": {
                    "concurrency": 12,
                    "per_domain": 6,
                    "target_concurrency": 3,
                    "download_delay": 0.2,
                }
            }
        )
        self.assertEqual(custom["CONCURRENT_REQUESTS_PER_DOMAIN"], 6)
        self.assertEqual(custom["DOWNLOAD_DELAY"], 0.2)
        for limits in [
            {"concurrency": 8, "per_domain": 16},
            {"target_concurrency": 0},
            {"download_delay": -1},
        ]:
            with self.assertRaises(ValueError):
                http_settings({"http": limits})

    def test_historical_crosslisting_ambiguity_preserves_raw_grades(self):
        from uwcourses.reconcile import reconcile, encode_state

        course = self.store.records(self.run, "courses")["COMPSCI 300"]
        course["course_reference"]["subjects"] = ["MUSIC"]
        self.store.put(
            self.run,
            "catalog",
            {
                "kind": "courses",
                "key": "MUSIC 300",
                "payload": course,
                "source_url": "https://example.org/catalog",
            },
        )
        key, grades = next(iter(self.store.records(self.run, "grades").items()))
        grades["course_reference"]["subjects"] = ["COMPSCI", "MUSIC"]
        self.store.put(
            self.run,
            "madgrades",
            {
                "kind": "grades",
                "key": key,
                "payload": grades,
                "source_url": "https://example.org/grades",
            },
        )
        state = encode_state(*reconcile(self.store, self.run))
        self.assertIn(key, state["unmatched"]["grades"])
        self.assertEqual(
            state["unmatched"]["ambiguous_grades"][key], ["COMPSCI 300", "MUSIC 300"]
        )
        self.assertEqual(self.store.records(self.run, "grades")[key], grades)
        self.assertIsNone(state["courses"]["COMPSCI 300"]["cumulative_grade_data"])

    def test_task_projections_exclude_existing_parser_output(self):
        self.core()
        task = json.loads(self.task.read_text())
        task["input_fields"] = {
            "requirements_text": "prerequisites.prerequisites_text",
            "linked_courses": "prerequisites.course_references",
        }
        self.task.write_text(canonical(task))
        jobs = Jobs(self.root)
        try:
            job = self.create_job(jobs)
            payload = json.loads(
                jobs.db.execute(
                    "SELECT input_json FROM results WHERE job_id=?", (job,)
                ).fetchone()[0]
            )
            self.assertEqual(set(payload), {"requirements_text", "linked_courses"})
            self.assertIsInstance(payload["requirements_text"], str)
            self.assertIsInstance(payload["linked_courses"], list)
        finally:
            jobs.close()

    def test_profiles_lock_shared_by_client_and_server(self):
        path = self.root / "models.toml"
        path.write_text(
            '[profiles.test]\nmodel="test/model"\nbase_url="http://127.0.0.1:8003/v1"\n'
        )
        output = self.root / "locked.json"
        with self.assertRaisesRegex(ValueError, ".json"):
            lock_profiles(path, ["test"], self.root / "locked.toml")
        with patch("huggingface_hub.HfApi") as hub:
            hub.return_value.model_info.return_value.sha = "b" * 40
            lock_profiles(path, ["test"], output)
        profile = load_profile(output, "test", resolve=False)
        self.assertEqual(profile.revision, "b" * 40)
        self.assertEqual(profile.served_model, "test/model@" + "b" * 40)

    def test_versioned_course_and_enrichment_history_survives_new_semesters(self):
        import pyarrow.parquet as pq

        self.core()
        original = self.store.records(self.run, "courses")["COMPSCI 300"]
        jobs = Jobs(self.root)
        calls = []
        runs, identifiers = [self.run], []

        def worker(profile, task, payload):
            calls.append(payload["description"])
            return {"summary": payload["description"]}, {"completion_tokens": 1}

        try:
            identifiers.append(self.create_job(jobs))
            jobs.run(identifiers[-1], worker)
            for semester in ["1274", "1282"]:
                run = self.store.new_run(semester, {})
                self.fixture.seed(run)
                self.store.put(
                    run,
                    "enrollment",
                    {
                        "kind": "terms",
                        "key": semester,
                        "payload": {"name": semester},
                        "source_url": "https://example.test/terms",
                    },
                )
                changed = {
                    **original,
                    "description": "Updated programming description.",
                }
                self.store.put(
                    run,
                    "catalog",
                    {
                        "kind": "courses",
                        "key": "COMPSCI 300",
                        "payload": changed,
                        "source_url": "https://example.test/course",
                    },
                )
                self.store.finish(run)
                runs.append(run)
                identifiers.append(self.create_job(jobs, run))
                jobs.run(identifiers[-1], worker)
            self.assertEqual(len(calls), 2)
            task = json.loads(self.task.read_text())
            task["version"] = 2
            self.task.write_text(canonical(task))
            pending = self.create_job(jobs, runs[-1])
            first = release(self.store, runs[-1], enrichment_ids=[identifiers[-1]])
            manifest = verify_release(first)
            self.assertEqual(len(manifest["enrichment_history"]), 3)
            self.assertEqual(manifest["tables"]["course_versions"], 2)
            self.assertEqual(manifest["tables"]["course_snapshots"], 3)
            self.assertEqual(manifest["tables"]["enrichment_outputs"], 2)
            self.assertEqual(manifest["tables"]["course_enrichment_runs"], 3)
            with sqlite3.connect(first / "coursemap.sqlite") as db:
                self.assertFalse(db.execute("PRAGMA foreign_key_check").fetchall())
                descriptions = dict(
                    db.execute("SELECT run_id,description FROM course_history")
                )
                self.assertEqual(descriptions[runs[0]], original["description"])
                self.assertEqual(
                    descriptions[runs[1]], "Updated programming description."
                )
                self.assertEqual(
                    db.execute(
                        "SELECT count(*) FROM course_enrichment_history"
                    ).fetchone()[0],
                    3,
                )
                self.assertEqual(
                    db.execute(
                        "SELECT job_id FROM current_course_enrichments"
                    ).fetchall(),
                    [(identifiers[-1],)],
                )
                self.assertIsNone(
                    db.execute(
                        "SELECT 1 FROM enrichment_jobs WHERE job_id=?", (pending,)
                    ).fetchone()
                )
            self.assertEqual(
                pq.read_table(first / "tables/course_versions.parquet").num_rows, 2
            )
            self.assertEqual(
                pq.read_table(first / "tables/course_enrichment_runs.parquet").num_rows,
                3,
            )
            jobs.run(pending, worker)
            second = release(self.store, runs[-1], enrichment_ids=[identifiers[-1]])
            self.assertNotEqual(
                first, second, "New completed history must change release identity"
            )
            self.assertEqual(len(verify_release(second)["enrichment_history"]), 4)
            self.assertEqual(len(verify_release(first)["enrichment_history"]), 3)
        finally:
            jobs.close()

    def test_release_rejects_enrichment_mutated_after_history_selection(self):
        from uwcourses.history import select_enrichments
        from uwcourses.release import write_database

        self.core()
        jobs = Jobs(self.root)
        try:
            job = self.create_job(jobs)
            jobs.run(job, lambda *args: ({"summary": "original"}, {}))
            history = select_enrichments(self.root, [self.run], [job], self.run)
            target = self.root / "frozen-history.sqlite"
            write_database(self.store, self.run, target)
            with jobs.db:
                jobs.db.execute(
                    "UPDATE results SET output_json=? WHERE job_id=?",
                    (canonical({"summary": "changed"}), job),
                )
            with self.assertRaisesRegex(ValueError, "changed after release history"):
                Jobs.append_release(self.root, target, self.run, [job], history)
        finally:
            jobs.close()
