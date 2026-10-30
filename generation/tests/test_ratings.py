"""Required RMP coverage, pagination, provenance, and LLM evidence contracts."""

import json
import tempfile
import unittest
from unittest.mock import patch

from scrapy import Request
from scrapy.http import TextResponse

from uwcourses.cli import main
from uwcourses.course_context import CourseContext
from uwcourses.lifecycle import prepare_instructor_refresh
from uwcourses.ratings import SCHOOL_ID, course_reviews, matched_teacher
from uwcourses.release import validate
from uwcourses.spiders import InstructorSpider
from uwcourses.store import Store, SOURCES
import test_pipeline


def response(value):
    request = Request("https://www.ratemyprofessors.com/graphql")
    return TextResponse(
        request.url, request=request, body=json.dumps(value).encode(), encoding="utf-8"
    )


def connection(nodes, more=False, cursor="last"):
    return {
        "edges": [{"node": n} for n in nodes],
        "pageInfo": {"hasNextPage": more, "endCursor": cursor},
    }


def review(identifier, course="CS300", date="2025-05-01"):
    return {
        "id": identifier,
        "class": course,
        "date": date,
        "comment": "Helpful feedback.",
        "qualityRating": 4,
        "difficultyRatingRounded": 3,
    }


def teacher(identifier="teacher-1"):
    return {
        "id": identifier,
        "legacyId": 123,
        "firstName": "Jane",
        "lastName": "Example",
        "school": {"id": SCHOOL_ID},
        "ratings": connection([review("r1")]),
    }


class RatingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_pipeline.PipelineTests()
        self.fixture.setUp()
        self.fixture.seed()
        self.store, self.run = self.fixture.store, self.fixture.run
        self.spider = InstructorSpider(store=self.store, run=self.run)
        self.spider.auth_header = {"Authorization": "Basic fixture"}

    def tearDown(self):
        self.fixture.tearDown()

    def test_course_context_rejects_conflicting_rating_sources(self):
        self.store.put(
            self.run,
            "legacy",
            {
                "kind": "ratings",
                "key": "Jane Example",
                "payload": {
                    "name": "Jane Example",
                    "candidates": [],
                    "collection_complete": True,
                },
                "source_url": "https://example.com/legacy",
            },
        )
        with self.assertRaisesRegex(ValueError, "Conflicting ratings record"):
            CourseContext(self.store, self.run)

    def test_scrape_requires_instructors_without_opt_in(self):
        with tempfile.TemporaryDirectory() as root:
            with (
                patch.dict("os.environ", {"MADGRADES_API_KEY": "fixture"}),
                patch("uwcourses.cli.execute", return_value={}),
                patch("uwcourses.cli.shutil.disk_usage") as disk,
            ):
                disk.return_value.free = 20 * 1024**3
                main(["--workspace", root, "scrape", "--semester", "1272"])
            store = Store(root, readonly=True)
            try:
                config = json.loads(
                    store.db.execute("SELECT config_json FROM runs").fetchone()[0]
                )
                self.assertEqual(config["sources"], list(SOURCES))
                self.assertEqual(config["ratings_contract"], 1)
            finally:
                store.close()

    def test_review_pagination_collects_all_pages_before_complete(self):
        t = teacher()
        t["ratings"] = connection([review("r1")], True, "page1")
        request = list(
            self.spider.rating(
                response({"data": {"newSearch": {"teachers": connection([t])}}}),
                "Jane Example",
            )
        )[0]
        self.assertIsInstance(request, Request)
        self.assertEqual(json.loads(request.body)["variables"]["after"], "page1")
        page = {
            "data": {
                "node": {
                    "id": t["id"],
                    "ratings": connection([review("r1"), review("r2")]),
                }
            }
        }
        row = list(self.spider.review_page(response(page), **request.cb_kwargs))[0]
        self.assertTrue(row["payload"]["collection_complete"])
        self.assertEqual(len(row["payload"]["candidates"][0]["ratings"]["edges"]), 2)
        self.assertEqual(len(row["payload"]["course_reviews"]), 2)
        self.assertEqual(row["payload"]["matched_teacher_id"], t["id"])

    def test_search_pagination_and_loop_detection(self):
        page = {
            "data": {
                "newSearch": {"teachers": connection([teacher()], True, "search1")}
            }
        }
        request = list(self.spider.rating(response(page), "Jane Example"))[0]
        with self.assertRaisesRegex(ValueError, "pagination"):
            list(self.spider.rating(response(page), **request.cb_kwargs))
        final = {"data": {"newSearch": {"teachers": connection([])}}}
        row = list(self.spider.rating(response(final), **request.cb_kwargs))[0]
        self.assertEqual(len(row["payload"]["candidates"]), 1)

    def test_failed_or_stuck_review_page_cannot_complete(self):
        t = teacher()
        t["ratings"] = connection([review("r1")], True, "page1")
        args = {
            "name": "Jane Example",
            "candidates": [t],
            "index": 0,
            "cursors": ["page1"],
        }
        with self.assertRaisesRegex(ValueError, "GraphQL"):
            list(
                self.spider.review_page(
                    response({"errors": [{"message": "failed"}]}), **args
                )
            )
        with self.assertRaisesRegex(ValueError, "pagination"):
            list(self.spider.review_page(response({"data": {"node": t}}), **args))

    def test_wrong_school_and_ambiguous_people_are_not_attributed(self):
        other = teacher("teacher-2")
        self.assertIsNone(matched_teacher("Jane Example", [teacher(), other]))
        other["school"]["id"] = "other-school"
        self.assertIsNone(matched_teacher("Jane Example", [other]))
        self.assertEqual(
            matched_teacher("Jane Example", [teacher(), other])["id"], "teacher-1"
        )

    def test_collected_reviews_reach_qwen_once_with_source_identity(self):
        t = teacher()
        t["ratings"] = connection(
            [review("r1"), review("r2", date=None), review("r3", course="MATH221")]
        )
        record = {
            "name": "Jane Example",
            "course_reviews": course_reviews(t),
            "candidates": [t],
            "collection_complete": True,
        }
        for key in ["Jane Example", "EXAMPLE JANE"]:
            self.store.put(
                self.run,
                "instructors",
                {
                    "kind": "ratings",
                    "key": key,
                    "payload": record,
                    "source_url": "https://www.ratemyprofessors.com/graphql",
                },
            )
        context = CourseContext(self.store, self.run)
        rows = context.get("COMPSCI 300")["reviews"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_review_id"], "r1")
        self.assertEqual(rows[0]["instructor_id"], "rmp:123")
        self.assertEqual(rows[0]["quality_rating"], 4)
        self.assertEqual(rows[0]["course_id"], "COMPSCI 300")
        self.assertEqual(
            len(
                self.store.records(self.run, "ratings")["Jane Example"]["candidates"][
                    0
                ]["ratings"]["edges"]
            ),
            3,
        )

    def test_required_coverage_distinguishes_no_match_from_failed_lookup(self):
        config = json.loads(self.store.run(self.run)["config_json"])
        config["ratings_contract"] = 1
        self.store.db.execute(
            "UPDATE runs SET config_json=? WHERE run_id=?",
            (json.dumps(config), self.run),
        )
        self.store.db.commit()
        with self.assertRaisesRegex(ValueError, "RMP collection incomplete"):
            validate(self.store, self.run)
        self.store.put(
            self.run,
            "instructors",
            {
                "kind": "ratings",
                "key": "Jane Example",
                "payload": {
                    "name": "Jane Example",
                    "candidates": [],
                    "collection_complete": True,
                },
                "source_url": "https://www.ratemyprofessors.com/graphql",
            },
        )
        validate(self.store, self.run)

    def test_refresh_keeps_original_source_timestamps_and_snapshot_immutable(self):
        self.store.finish(self.run)
        before = self.store.input_hash(self.run)
        with tempfile.TemporaryDirectory() as root:
            destination = Store(root)
            try:
                run = prepare_instructor_refresh(destination, self.run, self.store.root)
                config = json.loads(destination.run(run)["config_json"])
                self.assertEqual(config["reused_sources"]["catalog"], self.run)
                self.assertEqual(config["ratings_contract"], 1)
                for source in SOURCES[:3]:
                    self.assertEqual(destination.stage_status(run, source), "complete")
                self.assertEqual(
                    destination.stage_status(run, "instructors"), "pending"
                )
                self.assertEqual(destination.records(run, "ratings"), {})
                old = list(
                    self.store.db.execute(
                        "SELECT source,entity_id,observed_at,content_hash FROM observations WHERE run_id=? AND source!='instructors' ORDER BY source,entity_id",
                        (self.run,),
                    )
                )
                new = list(
                    destination.db.execute(
                        "SELECT source,entity_id,observed_at,content_hash FROM observations WHERE run_id=? ORDER BY source,entity_id",
                        (run,),
                    )
                )
                self.assertEqual([tuple(r) for r in old], [tuple(r) for r in new])
                self.assertEqual(self.store.input_hash(self.run), before)
            finally:
                destination.close()
