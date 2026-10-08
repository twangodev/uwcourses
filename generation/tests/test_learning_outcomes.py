import logging
import unittest

from bs4 import BeautifulSoup

from uwcourses.course import Course
from uwcourses.learning_outcomes import (
    catalog_outcomes,
    enrollment_outcomes,
    merge_outcomes,
    response_observed_at,
)


# Matches Guide's nested bubblehide/numbered outcome markup, including inline text.
BLOCK = """
<div class="courseblock">
<p class="courseblocktitle noindent"><span class="courseblockcode">COMP SCI 300</span> — Programming II</p>
<p class="courseblockdesc noindent">Object-oriented programming.</p>
<div class="cb-extras"><p><span class="cbextra-data"><div class="bubblehide">
<p><span class="cbextra-label"><strong>Learning Outcomes: </strong></span>
<span class="cbextra-data">1. Implement <em>data structures</em>.<br/>Audience: Undergraduate<br/><br/>
2. Compare algorithms.<br/>Audience: Undergraduate</span></p>
</div></span></p></div></div>
"""


class LearningOutcomeTests(unittest.TestCase):
    def test_catalog_refresh_replaces_its_sequence_and_keeps_other_sources(self):
        from uwcourses.learning_outcomes import merge_catalog_observations

        def payload(url, text, observed_at):
            return {
                "description": text,
                "official_learning_outcomes": [
                    {
                        "text": text,
                        "source": "catalog",
                        "source_url": url,
                        "observed_at": observed_at,
                        "term": None,
                        "catalog_year": None,
                    }
                ],
            }

        a, b = "https://guide.wisc.edu/courses/a/", "https://guide.wisc.edu/courses/b/"
        url, merged = merge_catalog_observations(
            a, payload(a, "Old A", "old"), b, payload(b, "Old B", "old")
        )
        url, refreshed = merge_catalog_observations(
            url, merged, a, payload(a, "New A", "new")
        )
        self.assertEqual((url, refreshed["description"]), (a, "New A"))
        self.assertEqual(
            [v["text"] for v in refreshed["official_learning_outcomes"]],
            ["New A", "Old B"],
        )
        url, refreshed = merge_catalog_observations(
            url, refreshed, b, payload(b, "New B", "new")
        )
        self.assertEqual((url, refreshed["description"]), (a, "New A"))
        self.assertEqual(
            [v["text"] for v in refreshed["official_learning_outcomes"]],
            ["New A", "New B"],
        )
        url, refreshed = merge_catalog_observations(
            url,
            refreshed,
            b,
            {"description": "Empty B", "official_learning_outcomes": []},
        )
        self.assertEqual(
            [v["text"] for v in refreshed["official_learning_outcomes"]], ["New A"]
        )

    def test_crosslisted_catalog_arrival_order_preserves_sources_and_statement_order(
        self,
    ):
        import json
        import test_pipeline

        results = []
        for source_order in (("z", "a"), ("a", "z")):
            fixture = test_pipeline.PipelineTests()
            fixture.setUp()
            try:
                for subject in source_order:
                    url = f"https://guide.wisc.edu/courses/{subject}/"
                    course = Course.from_block(
                        BeautifulSoup(BLOCK, "html.parser").select_one(".courseblock"),
                        logging.getLogger("test"),
                        source_url=url,
                        catalog_year="2026-2027",
                    )
                    course.description = f"Description from {subject}"
                    course.course_reference.subjects = {"COMP SCI", "ECE"}
                    fixture.store.put(
                        fixture.run,
                        "catalog",
                        {
                            "kind": "courses",
                            "key": course.get_identifier(),
                            "source_url": url,
                            "payload": course.to_dict(),
                        },
                    )
                row = fixture.store.db.execute(
                    "SELECT source_url,payload_json,content_hash FROM observations WHERE run_id=? AND kind='courses'",
                    (fixture.run,),
                ).fetchone()
                results.append(tuple(row))
                payload = json.loads(row[1])
                self.assertEqual(payload["description"], "Description from a")
                self.assertEqual(row[0], "https://guide.wisc.edu/courses/a/")
                self.assertEqual(
                    [
                        value["source_url"]
                        for value in payload["official_learning_outcomes"]
                    ],
                    [
                        "https://guide.wisc.edu/courses/a/",
                        "https://guide.wisc.edu/courses/a/",
                        "https://guide.wisc.edu/courses/z/",
                        "https://guide.wisc.edu/courses/z/",
                    ],
                )
                self.assertEqual(
                    [value["text"] for value in payload["official_learning_outcomes"]],
                    ["Implement data structures.", "Compare algorithms."] * 2,
                )
            finally:
                fixture.tearDown()
        self.assertEqual(results[0], results[1])

    def test_nested_guide_statements_have_explicit_source_and_no_audience_markers(self):
        block = BeautifulSoup(BLOCK, "html.parser").select_one(".courseblock")
        course = Course.from_block(
            block,
            logging.getLogger("test"),
            source_url="https://guide.wisc.edu/courses/comp_sci/",
            observed_at="2026-10-08T10:00:00Z",
            catalog_year="2026-2027",
        )
        self.assertEqual(
            [v["text"] for v in course.official_learning_outcomes],
            [
                "Implement data structures.",
                "Compare algorithms.",
            ],
        )
        first = course.official_learning_outcomes[0]
        self.assertEqual(first["source"], "catalog")
        self.assertEqual(first["catalog_year"], "2026-2027")
        self.assertIsNone(first["term"])
        self.assertEqual(
            Course.from_json(course.to_dict()).official_learning_outcomes,
            course.official_learning_outcomes,
        )
        old = course.to_dict()
        del old["official_learning_outcomes"]
        self.assertEqual(Course.from_json(old).official_learning_outcomes, [])

    def test_missing_outcome_sibling_does_not_capture_next_course(self):
        soup = BeautifulSoup(
            '<div class="courseblock"><span class="cbextra-label">Learning Outcomes:</span></div>'
            + BLOCK,
            "html.parser",
        )
        self.assertEqual(
            catalog_outcomes(
                soup.select_one(".courseblock"),
                source_url="https://guide.wisc.edu/courses/comp_sci/",
            ),
            [],
        )

    def test_enrollment_explicit_fields_only_and_source_conflicts_preserved(self):
        context = {
            "source_url": "https://public.enroll.wisc.edu/api/search/v1",
            "term": "1272",
        }
        self.assertEqual(
            enrollment_outcomes({"description": "Develop software."}, **context), []
        )
        records = enrollment_outcomes(
            {
                "learningOutcomes": [
                    "Write programs.",
                    {"text": "Analyze algorithms."},
                    {},
                    3,
                ]
            },
            **context,
        )
        self.assertEqual(len(records), 2)
        self.assertIsNone(records[0]["observed_at"])
        catalog = dict(
            records[0],
            source="catalog",
            source_url="https://guide.wisc.edu/courses/comp_sci/",
            term=None,
        )
        self.assertEqual(len(merge_outcomes(records, records, [catalog])), 3)

    def test_original_archive_fetch_time_is_used(self):
        import test_pipeline

        fixture = test_pipeline.PipelineTests()
        fixture.setUp()
        try:
            store, run = fixture.store, fixture.run
            url = "https://guide.wisc.edu/courses/comp_sci/"
            with store.db:
                store.db.execute(
                    "INSERT INTO responses(run_id,source,fingerprint,url,status,content_type,body_hash,fetched_at) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        run,
                        "catalog",
                        "fixture",
                        url,
                        200,
                        "text/html",
                        "hash",
                        "2026-01-02T03:04:05Z",
                    ),
                )
            self.assertEqual(
                response_observed_at(store, run, "catalog", url), "2026-01-02T03:04:05Z"
            )
            self.assertIsNone(response_observed_at(store, run, "enrollment", url))
        finally:
            fixture.tearDown()

    def test_reconcile_recovers_old_enrollment_hit_without_replacing_catalog(self):
        import json
        import test_pipeline
        from uwcourses.reconcile import reconcile

        fixture = test_pipeline.PipelineTests()
        fixture.setUp()
        try:
            fixture.seed()
            store, run = fixture.store, fixture.run
            row = store.db.execute(
                "SELECT entity_id,payload_json FROM observations WHERE run_id=? AND kind='offerings'",
                (run,),
            ).fetchone()
            data = json.loads(row[1])
            data.pop("official_learning_outcomes", None)
            data["hit"]["learningOutcomes"] = ["Analyze algorithm complexity."]
            catalog_row = store.db.execute(
                "SELECT entity_id,payload_json FROM observations WHERE run_id=? AND kind='courses' LIMIT 1",
                (run,),
            ).fetchone()
            catalog = json.loads(catalog_row[1])
            catalog["official_learning_outcomes"] = [
                {
                    "text": "Implement data structures.",
                    "source": "catalog",
                    "source_url": "https://guide.wisc.edu/courses/comp_sci/",
                    "observed_at": None,
                    "term": None,
                    "catalog_year": "2026-2027",
                }
            ]
            with store.db:
                store.db.execute(
                    "UPDATE observations SET payload_json=? WHERE run_id=? AND kind='offerings' AND entity_id=?",
                    (json.dumps(data), run, row[0]),
                )
                store.db.execute(
                    "UPDATE observations SET payload_json=? WHERE run_id=? AND kind='courses' AND entity_id=?",
                    (json.dumps(catalog), run, catalog_row[0]),
                )
            courses, *_ = reconcile(store, run)
            values = next(
                course.official_learning_outcomes
                for course in courses.values()
                if any(
                    v["source"] == "enrollment"
                    for v in course.official_learning_outcomes
                )
            )
            self.assertEqual(values[0]["text"], "Implement data structures.")
            self.assertEqual(values[1]["text"], "Analyze algorithm complexity.")
            self.assertEqual(values[1]["term"], "1272")
            self.assertIsNone(values[1]["observed_at"])
        finally:
            fixture.tearDown()
