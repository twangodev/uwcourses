import gzip
import hashlib
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace

import pyarrow.parquet as pq
from scrapy.http import Request, Response

from uwcourses.models import canonical
from uwcourses.store import SOURCES, Store
from uwcourses.spiders import (
    CatalogSpider,
    EnrollmentSpider,
    MadgradesSpider,
    InstructorSpider,
)
from uwcourses.release import (
    validate,
    write_database,
    write_parquet,
    verify_release,
    publish,
)
from uwcourses.reconcile import reconcile, encode_state

FIXTURES = Path(__file__).parent / "fixtures"


def response(url, body):
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode()
    if isinstance(body, str):
        body = body.encode()
    return Response(url, body=body, request=Request(url))


def grade_response():
    cumulative = {
        key: 0
        for key in [
            "total",
            "aCount",
            "abCount",
            "bCount",
            "bcCount",
            "cCount",
            "dCount",
            "fCount",
            "sCount",
            "uCount",
            "crCount",
            "nCount",
            "pCount",
            "iCount",
            "nwCount",
            "nrCount",
            "otherCount",
        ]
    }
    cumulative.update(total=5, aCount=5)
    return {
        "cumulative": cumulative,
        "courseOfferings": [
            {
                "termCode": 1272,
                "cumulative": cumulative,
                "sections": [{"instructors": [{"name": "Jane Example"}]}],
            }
        ],
    }


def enrollment_hit():
    subject = {
        "shortDescription": "COMP SCI",
        "subjectCode": "266",
        "schoolCollege": {
            "shortDescription": "Letters and Science",
            "academicOrgCode": "L&S",
            "schoolCollegeURI": "https://ls.wisc.edu",
        },
    }
    return {
        "catalogNumber": "300",
        "courseId": "123",
        "subject": subject,
        "allCrossListedSubjects": [subject],
        "lastTaught": "1272",
        "typicallyOffered": "Fall",
        "minimumCredits": 3,
        "maximumCredits": 3,
        "generalEd": None,
        "ethnicStudies": None,
    }


def enrollment_sections():
    return [
        {
            "sections": [
                {
                    "type": "LEC",
                    "sectionNumber": "001",
                    "startDate": 1788238800000,
                    "endDate": 1788238800000,
                    "instructors": [
                        {
                            "name": {"first": "Jane", "last": "Example"},
                            "email": "jane@example.edu",
                        }
                    ],
                    "enrollmentStatus": {"currentlyEnrolled": 10, "capacity": 20},
                    "classMeetings": [
                        {
                            "meetingDaysList": ["TUESDAY"],
                            "meetingType": "CLASS",
                            "meetingTimeStart": 54000000,
                            "meetingTimeEnd": 57600000,
                            "building": None,
                        }
                    ],
                }
            ]
        }
    ]


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(self.directory.name)
        self.run = self.store.new_run(
            "1272", {"code_hash": "test", "sitemap_base": "https://uwcourses.com"}
        )

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def seed(self, run=None):
        run = run or self.run
        self.store.put(
            run,
            "buildings",
            {
                "kind": "buildings",
                "key": "366",
                "payload": json.loads((FIXTURES / "campus-building.json").read_text()),
                "source_url": "https://map.wisc.edu/?initObj=0155",
            },
        )
        spider = CatalogSpider(store=self.store, run=run)
        for row in spider.department(
            response(
                "https://guide.wisc.edu/courses/comp_sci/",
                (FIXTURES / "catalog.html").read_bytes(),
            )
        ):
            self.store.put(run, "catalog", row)
        for source in ("madgrades", "enrollment"):
            self.store.put(
                run,
                source,
                {
                    "kind": "terms",
                    "key": "1272",
                    "payload": {"name": "Fall 2026"},
                    "source_url": "https://example.org/terms",
                },
            )
        spider = MadgradesSpider(store=self.store, run=run)
        for row in spider.grades(
            response("https://api.madgrades.com/v1/courses/1/grades", grade_response()),
            {"subjects": ["COMPSCI"], "course_number": 300},
            "1",
        ):
            self.store.put(run, "madgrades", row)
        spider = EnrollmentSpider(store=self.store, run=run)
        for row in spider.package(
            response("https://public.enroll.wisc.edu/packages", enrollment_sections()),
            enrollment_hit(),
            {"subjects": ["COMPSCI"], "course_number": 300},
        ):
            self.store.put(run, "enrollment", row)
        spider = InstructorSpider(store=self.store, run=run)
        for row in spider.faculty(
            response(
                "https://guide.wisc.edu/faculty/",
                (FIXTURES / "faculty.html").read_bytes(),
            )
        ):
            self.store.put(run, "instructors", row)
        self.store.put(
            run,
            "instructors",
            {
                "kind": "ratings",
                "key": "Jane Example",
                "payload": {"name": "Jane Example", "candidates": []},
                "source_url": "https://www.ratemyprofessors.com/graphql",
            },
        )
        for source in SOURCES:
            self.store.stage(run, source, "complete")
        state = encode_state(*reconcile(self.store, run))
        self.store.artifact(run, "source_state", state, self.store.input_hash(run), {})
        return state

    def test_history_and_current_view_ignore_incomplete_run(self):
        self.seed()
        self.store.finish(self.run)
        later = self.store.new_run("1274", {})
        self.seed(later)
        self.store.db.execute(
            "UPDATE observations SET payload_json=json_set(payload_json,'$.course_title','CHANGED') WHERE run_id=? AND kind='courses'",
            (later,),
        )
        self.store.db.commit()
        self.assertEqual(
            self.store.db.execute("SELECT title FROM current_courses").fetchone()[0],
            "PROGRAMMING II",
        )
        self.store.finish(later)
        self.assertEqual(
            self.store.db.execute("SELECT title FROM current_courses").fetchone()[0],
            "CHANGED",
        )
        self.assertEqual(
            self.store.db.execute("SELECT count(*) FROM courses").fetchone()[0], 2
        )

    def test_duplicate_replay_is_idempotent(self):
        self.seed()
        before = self.store.input_hash(self.run)
        self.seed()
        self.assertEqual(before, self.store.input_hash(self.run))
        self.assertEqual(len(self.store.records(self.run, "courses")), 1)

    def test_building_refresh_preserves_other_sources_and_original_snapshot(self):
        from uwcourses.lifecycle import prepare_source_refresh

        self.seed()
        self.store.finish(self.run)
        before = self.store.input_hash(self.run)
        refreshed = prepare_source_refresh(self.store, self.run, "buildings")

        def reused(run):
            return [
                tuple(row)
                for row in self.store.db.execute(
                    "SELECT source,kind,entity_id,observed_at,content_hash FROM observations "
                    "WHERE run_id=? AND source!='buildings' ORDER BY source,kind,entity_id",
                    (run,),
                )
            ]

        self.assertEqual(reused(self.run), reused(refreshed))
        self.assertEqual(self.store.stage_status(refreshed, "buildings"), "pending")
        self.assertEqual(self.store.records(refreshed, "buildings"), {})
        for source in SOURCES[:-1]:
            self.assertEqual(self.store.stage_status(refreshed, source), "complete")
        self.assertEqual(self.store.input_hash(self.run), before)

    def test_building_refresh_accepts_snapshot_predating_buildings(self):
        from uwcourses.lifecycle import prepare_source_refresh

        self.seed()
        with self.store.db:
            self.store.db.execute("DELETE FROM observations WHERE source='buildings'")
            self.store.db.execute("DELETE FROM stages WHERE stage='buildings'")
        self.store.finish(self.run)
        refreshed = prepare_source_refresh(self.store, self.run, "buildings")
        self.assertEqual(self.store.stage_status(refreshed, "buildings"), "pending")
        self.assertEqual(self.store.stage_status(refreshed, "instructors"), "complete")

    def test_invalid_item_does_not_modify_database(self):
        with self.assertRaises(ValueError):
            self.store.put(
                self.run,
                "catalog",
                {
                    "kind": "courses",
                    "key": "bad",
                    "payload": {},
                    "source_url": "https://example.org",
                },
            )
        self.assertEqual(self.store.records(self.run, "courses"), {})

    def test_missing_references_are_rejected_before_storage(self):
        for kind, payload in [
            ("offerings", {"sections": []}),
            ("grades", {"courseOfferings": [], "cumulative": {}}),
        ]:
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.store.put(
                    self.run,
                    "enrollment" if kind == "offerings" else "madgrades",
                    {
                        "kind": kind,
                        "key": "bad",
                        "payload": payload,
                        "source_url": "https://example.org",
                    },
                )
            self.assertEqual(self.store.records(self.run, kind), {})

    def test_replaced_observation_records_the_new_observation_time(self):
        from unittest.mock import patch

        self.seed()
        key, value = next(iter(self.store.records(self.run, "courses").items()))
        item = {
            "kind": "courses",
            "key": key,
            "payload": value,
            "source_url": "https://example.org",
        }
        with patch("uwcourses.store.now", return_value="2026-01-01T00:00:00+00:00"):
            self.store.put(self.run, "catalog", item)
        value["description"] = "Updated catalog description"
        with patch("uwcourses.store.now", return_value="2026-02-01T00:00:00+00:00"):
            self.store.put(self.run, "catalog", item)
        row = self.store.db.execute(
            "SELECT observed_at,payload_json FROM observations WHERE run_id=? AND source='catalog' AND kind='courses' AND entity_id=?",
            (self.run, key),
        ).fetchone()
        self.assertEqual(row["observed_at"], "2026-02-01T00:00:00+00:00")
        self.assertEqual(
            json.loads(row["payload_json"])["description"],
            "Updated catalog description",
        )

    def test_explicitly_empty_department_is_valid(self):
        catalog = CatalogSpider(store=self.store, run=self.run)
        title = '<h1 class="page-title">Otolaryngology (OTOLARYN)</h1>'
        notice = '<div id="textcontainer">The subject OTOLARYN does not have any active courses at time of Guide publication.</div>'
        items = list(
            catalog.department(
                response("https://guide.wisc.edu/courses/otolaryn/", title + notice)
            )
        )
        self.assertEqual([item["kind"] for item in items], ["subjects"])
        self.assertEqual(items[0]["key"], "OTOLARYN")
        with self.assertRaisesRegex(ValueError, "no course blocks"):
            list(
                catalog.department(
                    response("https://guide.wisc.edu/courses/otolaryn/", title)
                )
            )

    def test_malformed_source_pages_fail(self):
        catalog = CatalogSpider(store=self.store, run=self.run)
        with self.assertRaises(ValueError):
            list(
                catalog.department(
                    response("https://guide.wisc.edu", "<h1>Unavailable</h1>")
                )
            )
        with self.assertRaises(ValueError):
            list(
                catalog.sitemap(
                    response("https://guide.wisc.edu/sitemap.xml", "<urlset/>")
                )
            )
        enrollment = EnrollmentSpider(store=self.store, run=self.run)
        with self.assertRaises(ValueError):
            list(
                enrollment.hits(
                    response(
                        "https://public.enroll.wisc.edu", {"found": 3, "hits": []}
                    ),
                    1,
                )
            )

    def test_missing_source_or_reference_blocks_release(self):
        self.seed()
        validate(self.store, self.run)
        self.store.stage(self.run, "instructors", "failed")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            validate(self.store, self.run)
        self.store.stage(self.run, "instructors", "complete")
        self.store.db.execute("DELETE FROM observations WHERE kind='subjects'")
        self.store.db.commit()
        with self.assertRaisesRegex(ValueError, "missing subject"):
            validate(self.store, self.run)

    def test_reconciliation_and_relational_export(self):
        state = self.seed()
        self.assertEqual(
            state["courses"]["COMPSCI 300"]["term_data"]["1272"]["grade_data"]["total"],
            5,
        )
        self.assertEqual(len(state["instructors"]), 1)
        self.assertTrue(state["meetings"]["COMPSCI 300"])
        validate(self.store, self.run)
        db_path = Path(self.directory.name) / "public.sqlite"
        write_database(self.store, self.run, db_path)
        counts = write_parquet(db_path, Path(self.directory.name) / "tables")
        db = sqlite3.connect(db_path)
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(
            db.execute("SELECT name FROM current_instructors").fetchone()[0],
            "Jane Example",
        )
        self.assertNotIn("responses", counts)
        self.assertNotIn("stages", counts)
        archived = pq.read_table(
            Path(self.directory.name) / "tables/observations.parquet"
        ).to_pylist()
        (building,) = [row for row in archived if row["kind"] == "buildings"]
        self.assertEqual(building["entity_id"], "366")
        self.assertEqual(
            json.loads(building["payload_json"])["building_number"], "0155"
        )
        for table, count in counts.items():
            data = pq.read_table(
                Path(self.directory.name) / "tables" / f"{table}.parquet"
            )
            self.assertEqual(data.num_rows, count)
            columns = data.column_names
            expected = [
                dict(zip(columns, row))
                for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")
            ]
            self.assertEqual(data.to_pylist(), expected)
        db.close()

    def release(self, files=1):
        self.store.finish(self.run)
        root = self.store.root / "releases" / self.run
        root.mkdir(parents=True)
        metadata = {}
        for i in range(files):
            content = str(i).encode()
            name = f"{i}.json"
            (root / name).write_bytes(content)
            metadata[name] = {
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        (root / "manifest.json").write_text(
            canonical(
                {
                    "files": metadata,
                    "input_hash": self.store.input_hash(self.run),
                    "run_id": self.run,
                }
            )
        )
        return root

    def test_corruption_blocks_publication_before_network(self):
        root = self.release()
        (root / "0.json").write_text("corrupt")
        with self.assertRaisesRegex(ValueError, "checksum"):
            verify_release(root)

    def test_failed_upload_does_not_activate_and_resumes(self):
        root = self.release(110)
        api = FakeHub(root)
        api.fail_on_commit = 2
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            publish(self.store, self.run, "owner/data", api, api.download)
        self.assertFalse(api.tags)
        self.assertNotIn("latest.json", api.files["main"])
        self.assertNotIn("sync.json", api.files["main"])
        self.assertEqual(len(api.files["runs/" + self.run]), 100)
        api.fail_on_commit = None
        result = publish(self.store, self.run, "owner/data", api, api.download)
        self.assertIn(result["tag"], api.tags)
        self.assertIn("latest.json", api.files["main"])
        self.assertEqual(api.added_counts, [100, 11, 2])
        sync = json.loads(api.files["main"]["sync.json"])
        self.assertEqual(sync["data_revision"], result["revision"])
        self.assertEqual(sync["source_run"], self.run)
        self.assertEqual(
            sync["scan_completed_at"], self.store.run(self.run)["completed_at"]
        )
        self.assertEqual(
            result, publish(self.store, self.run, "owner/data", api, api.download)
        )

    def test_concurrent_publication_does_not_replace_latest(self):
        root = self.release()
        api = FakeHub(root)
        api.change_main = True
        with self.assertRaisesRegex(ValueError, "main changed"):
            publish(self.store, self.run, "owner/data", api, api.download)
        self.assertNotIn("latest.json", api.files["main"])
        self.assertNotIn("sync.json", api.files["main"])

    def test_failed_publication_preserves_previous_badge_metadata(self):
        root = self.release()
        api = FakeHub(root)
        previous = b'{"source_run":"previous"}'
        api.files["main"]["sync.json"] = previous
        api.fail_on_commit = 2  # Branch cleanup succeeds; the data upload fails.
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            publish(self.store, self.run, "owner/data", api, api.download)
        self.assertEqual(api.files["main"]["sync.json"], previous)
        api.fail_on_commit = None
        result = publish(self.store, self.run, "owner/data", api, api.download)
        sync = json.loads(api.files["main"]["sync.json"])
        self.assertEqual(sync["source_run"], self.run)
        self.assertEqual(sync["data_revision"], result["revision"])

    def test_http_retries_browser_headers_and_compressed_replay(self):
        body = (FIXTURES / "catalog.html").read_bytes()
        observed = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(handler):
                if handler.path == "/robots.txt":
                    handler.send_response(200)
                    handler.end_headers()
                    handler.wfile.write(b"User-agent: *\nAllow: /\n")
                    return
                observed.append(handler.headers.get("User-Agent"))
                handler.send_response(503 if len(observed) < 3 else 200)
                handler.send_header("Content-Type", "text/html")
                handler.send_header("Content-Encoding", "gzip")
                handler.end_headers()
                handler.wfile.write(gzip.compress(body))

            def log_message(handler, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/courses/comp_sci/"
        code = """
import sys
from uwcourses.spiders import CatalogSpider, SPIDERS
from uwcourses.crawl import crawl
class FixtureSpider(CatalogSpider):
    allowed_domains = ["127.0.0.1"]
    custom_settings = {"AUTOTHROTTLE_ENABLED": False, "DOWNLOAD_DELAY": 0}
    async def start(self):
        yield self.request(sys.argv[3], self.department)
SPIDERS["catalog"] = FixtureSpider
crawl(sys.argv[1], sys.argv[2], "catalog", offline=len(sys.argv) > 4)
"""
        command = [sys.executable, "-c", code, str(self.store.root), self.run, url]
        try:
            first = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(len(observed), 3)
            self.assertTrue(all(ua.startswith("Mozilla/") for ua in observed))
            second = subprocess.run(
                command + ["offline"], capture_output=True, text=True, timeout=30
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(len(observed), 3)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_large_count_drop_blocks_publication(self):
        self.seed()
        row = self.store.records(self.run, "courses")["COMPSCI 300"]
        for number in range(400, 410):
            course = json.loads(json.dumps(row))
            course["course_reference"]["course_number"] = number
            self.store.put(
                self.run,
                "catalog",
                {
                    "kind": "courses",
                    "key": f"COMPSCI {number}",
                    "payload": course,
                    "source_url": "https://guide.wisc.edu/courses/comp_sci/",
                },
            )
        self.store.finish(self.run)
        next_run = self.store.new_run("1272", {})
        self.seed(next_run)
        with self.assertRaisesRegex(ValueError, "fell by more than 10%"):
            validate(self.store, next_run)

    def test_real_scrapy_offline_resume(self):
        from scrapy.settings import Settings
        from uwcourses.crawl import ArchiveMiddleware
        from uwcourses.cli import execute_source

        crawler = SimpleNamespace(
            pipeline_store=self.store,
            settings=Settings({"PIPELINE_RUN": self.run, "PIPELINE_SOURCE": "catalog"}),
            signals=SimpleNamespace(connect=lambda *a, **kw: None),
        )
        archive = ArchiveMiddleware(crawler)
        for url, content in {
            "https://guide.wisc.edu/robots.txt": "User-agent: *\nAllow: /\n",
            "https://guide.wisc.edu/sitemap.xml": "<urlset><url><loc>https://guide.wisc.edu/courses/comp_sci/</loc></url></urlset>",
            "https://guide.wisc.edu/courses/comp_sci/": (
                FIXTURES / "catalog.html"
            ).read_text(),
        }.items():
            request = Request(url)
            archive.process_response(
                request, Response(url, body=content.encode(), request=request)
            )
        execute_source(self.store, self.run, "catalog", offline=True)
        first = self.store.input_hash(self.run)
        execute_source(self.store, self.run, "catalog", offline=True)
        self.assertEqual(self.store.input_hash(self.run), first)
        self.assertEqual(len(self.store.records(self.run, "courses")), 1)

    def test_completed_run_is_immutable(self):
        self.seed()
        self.store.finish(self.run)
        with self.assertRaisesRegex(ValueError, "immutable"):
            self.store.reset_source(self.run, "catalog")

    def test_archive_reuses_body_without_request_credentials(self):
        from scrapy.settings import Settings
        from uwcourses.crawl import ArchiveMiddleware

        crawler = SimpleNamespace(
            pipeline_store=self.store,
            settings=Settings({"PIPELINE_RUN": self.run, "PIPELINE_SOURCE": "catalog"}),
            signals=SimpleNamespace(connect=lambda *a, **kw: None),
        )
        middleware = ArchiveMiddleware(crawler)
        request = Request(
            "https://example.org/course", headers={"Authorization": "secret"}
        )
        fetched = Response(
            request.url,
            body=b"course data",
            headers={"Content-Type": "text/html"},
            request=request,
        )
        middleware.process_response(request, fetched)
        cached = middleware.process_request(request)
        self.assertEqual(cached.body, b"course data")
        row = self.store.db.execute("SELECT * FROM responses").fetchone()
        self.assertNotIn("secret", str(tuple(row)))
        self.assertEqual(
            gzip.decompress((self.store.root / "raw" / row["body_hash"]).read_bytes()),
            b"course data",
        )
        middleware.failed(None, fetched, None)
        self.assertIsNone(middleware.process_request(request))


class FakeHub:
    def __init__(self, root):
        self.root = root
        self.files = {"main": {}}
        self.heads = {"main": "base"}
        self.tags = {}
        self.commits = 0
        self.added_counts = []
        self.fail_on_commit = None
        self.change_main = False

    def create_repo(self, **kw):
        pass

    def create_branch(self, branch, **kw):
        self.files.setdefault(branch, dict(self.files["main"]))
        self.heads.setdefault(branch, "base")

    def repo_info(self, revision, **kw):
        return SimpleNamespace(
            sha=self.tags[revision] if revision in self.tags else self.heads[revision]
        )

    def branch_for(self, revision):
        return (
            revision
            if revision in self.files
            else next(k for k, v in self.heads.items() if v == revision)
        )

    def list_repo_files(self, revision, **kw):
        return list(self.files[self.branch_for(revision)])

    def create_commit(self, revision, parent_commit, operations, **kw):
        self.commits += 1
        if self.commits == self.fail_on_commit:
            raise RuntimeError("interrupted upload")
        assert parent_commit == self.heads[revision]
        for op in operations:
            if not hasattr(op, "path_or_fileobj"):
                self.files[revision].pop(op.path_in_repo, None)
                continue
            content = op.path_or_fileobj
            self.files[revision][op.path_in_repo] = (
                content if isinstance(content, bytes) else Path(content).read_bytes()
            )
        self.added_counts.append(len(operations))
        self.heads[revision] = f"commit{self.commits}"
        if self.change_main and revision != "main":
            self.heads["main"] = "concurrent"
        return SimpleNamespace(oid=self.heads[revision])

    def create_tag(self, tag, revision, **kw):
        self.tags[tag] = revision

    def download(self, repo, path, revision, **kw):
        content = self.files[self.branch_for(revision)][path]
        output = self.root.parent / "download"
        output.write_bytes(content)
        return output


if __name__ == "__main__":
    unittest.main()
