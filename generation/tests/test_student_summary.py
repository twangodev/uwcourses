import copy
import unittest
from pathlib import Path
from uwcourses.tasks import load_task
from uwcourses.student_context import (
    grade_sentence,
    match_name,
    teaching_history,
    select_course_grades,
    review_course_correction,
)
from uwcourses.student_summary import (
    generate_student,
    validate_claims,
)


def grade(term, a, b, section=1):
    return {
        "term_id": term,
        "term_name": term,
        "counts": {"a": a, "ab": 0, "b": b, "bc": 0, "c": 0, "d": 0, "f": 0},
        "citation": {
            "type": "grade",
            "run_id": "run",
            "table": "section_grades_latest",
            "term_id": term,
            "section_number": section,
        },
    }


def review(id, instructor):
    return {
        "id": id,
        "instructor_id": instructor,
        "instructor_name": instructor,
        "course_id": "COMPSCI 300",
        "source_review_id": id,
        "source_url": "https://example.com/" + id,
        "date": "2025-01-01",
        "comment": "Clear lectures and useful projects.",
    }


class StudentSummaryTests(unittest.TestCase):
    def test_past_only_reviews_generate_one_preview_and_preserve_citations(self):
        calls = []
        historical = review("old-review", "Former Instructor")
        task = load_task(
            Path(__file__).resolve().parents[2] / "inference/tasks/student_summary.json"
        )
        payload = {
            "source_run": "run",
            "summary_seed": {"job_id": "parent", "output": {"sections": {}}},
            "student_context": {
                "course_id": "COMPSCI 300",
                "term_id": "1274",
                "term_name": "Spring 2027",
                "offered": True,
                "current_instructors": [
                    {
                        "name": "New Teacher",
                        "instructor_uid": "uw:new",
                        "rmp_instructor_id": None,
                        "reviews": [],
                        "grade_records": [],
                    }
                ],
                "historical_reviews": [historical],
                "teaching_history": [],
                "grade_records": [],
            },
        }

        def fake(profile, scoped_task, request):
            calls.append(request)
            return {
                "quick_take": [
                    {
                        "text": historical["comment"],
                        "review_ids": ["review:1"],
                    }
                ],
                "difficulty_workload": [],
                "student_experience": [],
            }, {}

        result, _ = generate_student(
            {"model": "test", "revision": "abc", "max_output_tokens": 1000},
            task,
            payload,
            generate=fake,
        )
        value = result["sections"]["student_summary"]["value"]
        self.assertEqual([request["mode"] for request in calls], ["overview"])
        self.assertEqual(value["historical_context"], [])
        self.assertEqual(
            value["current_instructors"][0]["review_status"], "no_course_reviews"
        )
        self.assertEqual(
            value["quick_take"][0]["text"],
            historical["comment"],
        )
        self.assertEqual(
            value["quick_take"][0]["evidence_scope"], "past_student_reviews"
        )
        citation = value["quick_take"][0]["citations"][0]
        self.assertEqual(citation["source_review_id"], "old-review")
        self.assertEqual(citation["instructor_name"], "Former Instructor")
        self.assertEqual(citation["run_id"], "run")

    def test_review_course_corrections_require_explicit_resolvable_opening(self):
        aliases = {"AAE 635": "AAE 635", "ECE 759": "COMPSCI/ECE 759"}
        for text, expected in [
            ("Actually AAE635. He cares about his students.", "AAE 635"),
            ("This review is for ECE 759, a good course.", "COMPSCI/ECE 759"),
            ("Actually AAE999, a good course.", None),
            ("AAE635 was harder than this class.", None),
            ("Actually a great instructor.", None),
        ]:
            with self.subTest(text=text):
                self.assertEqual(
                    review_course_correction({"comment": text}, aliases.get), expected
                )

    def test_conflicting_alias_grades_follow_selected_record_without_summing(self):
        first, second = grade("1262", 8, 2), grade("1262", 26, 8)
        first["citation"]["source_record"] = {"entity_id": "first"}
        second["citation"]["source_record"] = {"entity_id": "second"}
        selected = select_course_grades([first, second])
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["counts"]["a"], 26)
        self.assertEqual(
            selected[0]["citation"]["alternative_source_records"],
            [{"entity_id": "first"}],
        )
        sentence = grade_sentence(selected)
        self.assertIn("n=34 letter grades", sentence["text"])
        self.assertIn("source records differ", sentence["text"])

    def test_teaching_history_keeps_both_seasons_and_zero_grade_sections(self):
        fall = grade("1252", 0, 0)
        spring = grade("1264", 10, 0)
        history = teaching_history({"Dan Negrut": [spring, fall, copy.deepcopy(fall)]})
        self.assertEqual([t["term_id"] for t in history[0]["terms"]], ["1252", "1264"])
        self.assertEqual(len(history[0]["terms"][0]["citations"]), 1)
        self.assertNotIn("counts", str(history))

    def test_grades_deduplicate_weight_and_use_last_three_usable_terms(self):
        data = [
            grade("1", 10, 0),
            grade("2", 10, 10),
            grade("3", 0, 10),
            grade("4", 10, 0),
            grade("4", 0, 30, 2),
            grade("5", 0, 0),
        ]
        data.append(copy.deepcopy(data[3]))
        result = grade_sentence(data)
        self.assertNotIn("1:", result["text"])
        self.assertIn("4: 3.25 GPA, 25.0% A/AB (n=40 letter grades)", result["text"])
        self.assertEqual(len(result["citations"]), 4)
        self.assertEqual(set(result), {"text", "citations"})
        data[-1]["counts"]["a"] = None
        self.assertIsNone(grade_sentence([data[-1]]))

    def test_joint_teaching_and_ambiguous_names(self):
        row = grade("1", 10, 10)
        row["joint"] = True
        self.assertIn("jointly taught", grade_sentence([row])["text"])
        self.assertIsNone(match_name("J Smith", ("Jane Smith", "John Smith")))
        self.assertEqual(
            match_name("Jane Smith", ("Jane Smith", "John Smith")), "Jane Smith"
        )

    def test_claims_reject_other_scope_citations_and_generated_grades(self):
        request = {
            "mode": "professor",
            "instructor_name": "Jane Doe",
            "reviews": [{"citation_id": "review:1"}],
        }
        output = {
            "summary": [
                {"text": "Jane Doe explains clearly.", "review_ids": ["review:1"]}
            ],
            "quick_take": [],
            "difficulty_workload": [],
            "student_experience": [],
        }
        validate_claims(output, request)
        for text, ids in [
            ("Someone explains clearly.", ["review:1"]),
            ("Jane Doe gives a 4.0 GPA.", ["review:1"]),
            ("Jane Doe explains clearly.", ["review:2"]),
        ]:
            output["summary"][0].update(text=text, review_ids=ids)
            with self.assertRaises(ValueError):
                validate_claims(output, request)

    def test_claims_reject_repetition_and_overlong_quick_take(self):
        request = {"mode": "overview", "reviews": [{"citation_id": "review:1"}]}
        claim = {
            "text": "Reviewers describe useful projects.",
            "review_ids": ["review:1"],
        }
        with self.assertRaisesRegex(ValueError, "repeat"):
            validate_claims(
                {"quick_take": [claim], "student_experience": [claim]}, request
            )
        with self.assertRaisesRegex(ValueError, "Shorten"):
            validate_claims(
                {"quick_take": [{**claim, "text": "useful " * 56 + "projects."}]},
                request,
            )
        with self.assertRaisesRegex(ValueError, "consensus"):
            validate_claims(
                {
                    "quick_take": [
                        {**claim, "text": "This instructor is widely praised."}
                    ]
                },
                request,
            )

    def test_review_variation_is_not_consensus(self):
        request = {"mode": "overview", "reviews": [{"citation_id": "review:1"}]}
        for text in [
            "Experiences vary widely.",
            "Reported workload varies widely.",
            "Historical experiences differed widely.",
        ]:
            with self.subTest(text=text):
                validate_claims(
                    {"quick_take": [{"text": text, "review_ids": ["review:1"]}]},
                    request,
                )
        with self.assertRaisesRegex(ValueError, "consensus"):
            validate_claims(
                {
                    "quick_take": [
                        {
                            "text": "Experiences vary widely, but this instructor is widely praised.",
                            "review_ids": ["review:1"],
                        }
                    ]
                },
                request,
            )

    def test_inline_review_handles_require_native_repair(self):
        request = {"mode": "history", "reviews": [{"citation_id": "review:1"}]}
        for text in [
            "The reviewer liked the course (review:1).",
            "Clear lectures [review:1, review:2].",
        ]:
            with (
                self.subTest(text=text),
                self.assertRaisesRegex(ValueError, "inline review handles"),
            ):
                validate_claims(
                    {"summary": [{"text": text, "review_ids": ["review:1"]}]}, request
                )

    def test_review_availability_is_not_a_cited_claim(self):
        request = {"mode": "history", "reviews": [{"citation_id": "review:1"}]}
        for text in [
            "The current instructors have no reviewed history in this dataset.",
            "No course-specific reviews are available for the current instructor.",
        ]:
            with (
                self.subTest(text=text),
                self.assertRaisesRegex(ValueError, "availability"),
            ):
                validate_claims(
                    {"summary": [{"text": text, "review_ids": ["review:1"]}]}, request
                )
        validate_claims(
            {
                "summary": [
                    {
                        "text": "A reviewer reported receiving no feedback on assignments.",
                        "review_ids": ["review:1"],
                    }
                ]
            },
            request,
        )

    def test_independent_professors_history_and_missing_reviews(self):
        calls = []
        profiles_seen = []

        def fake(profile, task, request):
            expected = (
                {"quick_take", "difficulty_workload", "student_experience"}
                if request["mode"] == "overview"
                else {"summary"}
            )
            self.assertEqual(set(task["schema"]["properties"]), expected)
            self.assertNotIn("- professor:", task["prompt"])
            self.assertNotIn("- overview:", task["prompt"])
            self.assertNotIn("- history:", task["prompt"])
            if request["mode"] != "overview":
                self.assertNotIn("quick_take", task["prompt"])
            if request["mode"] == "history":
                self.assertNotIn("Prioritize current instructors.", task["prompt"])
                self.assertIn("only the supplied historical reviews", task["prompt"])
            calls.append(request)
            profiles_seen.append(profile)
            result = {
                k: []
                for k in (
                    "summary",
                    "quick_take",
                    "difficulty_workload",
                    "student_experience",
                )
            }
            name = request["instructor_name"] or "Historical reviewers"
            result["quick_take" if request["mode"] == "overview" else "summary"] = [
                {"text": name + " reported clear lectures.", "review_ids": ["review:1"]}
            ]
            return result, {"total_tokens": 5}

        people = [
            {
                "name": "Jane Doe",
                "instructor_uid": "uw:1",
                "rmp_instructor_id": "rmp:1",
                "reviews": [review("1", "rmp:1")],
                "grade_records": [grade("1", 1, 1)],
            },
            {
                "name": "New Teacher",
                "instructor_uid": "uw:2",
                "rmp_instructor_id": None,
                "reviews": [],
                "grade_records": [],
            },
        ]
        base = {
            "search_profile": {
                "status": "valid",
                "value": {"summary": "Original catalog summary"},
            },
            "requirements": {"status": "needs_review", "value": {"nodes": []}},
            "student_experience": {"status": "valid", "value": {}},
        }
        payload = {
            "source_run": "run",
            "summary_seed": {
                "job_id": "parent",
                "output": {"sections": base},
                "failed_subtasks": [
                    {
                        "mode": "professor",
                        "instructor_uid": "uw:1",
                        "conversation": ["stale input"],
                    }
                ],
            },
            "student_context": {
                "course_id": "COMPSCI 300",
                "term_id": "1272",
                "term_name": "Fall 2026",
                "offered": True,
                "current_instructors": people,
                "historical_reviews": [review("2", "rmp:old")],
                "teaching_history": teaching_history({"Jane Doe": [grade("1", 1, 1)]}),
                "grade_records": [grade("1", 1, 1)],
            },
        }
        result, _ = generate_student(
            {"model": "test", "revision": "abc", "max_output_tokens": 1000},
            load_task(
                Path(__file__).resolve().parents[2]
                / "inference/tasks/student_summary.json"
            ),
            payload,
            generate=fake,
        )
        self.assertEqual({k: result["sections"][k] for k in base}, base)
        section = result["sections"]["student_summary"]
        self.assertEqual(section["status"], "valid")
        self.assertNotIn("_history", calls[0])
        self.assertEqual(
            calls[0]["teaching_history"], [{"name": "Jane Doe", "terms": ["1"]}]
        )
        teaching = section["value"]["teaching_history"][0]
        self.assertIn("Jane Doe is recorded teaching in 1.", teaching["text"])
        self.assertEqual(teaching["citations"], [grade("1", 1, 1)["citation"]])
        value = section["value"]
        for claims in (
            value["quick_take"],
            value["historical_context"],
            *(person["summary"] for person in value["current_instructors"]),
        ):
            for claim in claims:
                if all(c["type"] == "review" for c in claim["citations"]):
                    self.assertEqual(claim["evidence_scope"], "past_student_reviews")
                else:
                    self.assertNotIn("evidence_scope", claim)
        current = section["value"]["current_instructors"]
        self.assertEqual(current[1]["review_status"], "no_course_reviews")
        self.assertEqual(
            current[0]["summary"][0]["citations"][0]["source_instructor_id"], "rmp:1"
        )
        self.assertEqual(
            section["value"]["historical_context"][0]["citations"][0][
                "source_instructor_id"
            ],
            "rmp:old",
        )
        self.assertEqual(
            [r["instructor_name"] for r in calls[-1]["reviews"]], ["rmp:1"]
        )
        self.assertNotIn("id", calls[-1]["reviews"][0])
        self.assertNotIn("source_review_id", calls[-1]["reviews"][0])

        payload["summary_seed"] = {"job_id": "previous", "output": result}
        before = len(calls)
        resumed, _ = generate_student(
            {"model": "test", "revision": "abc", "max_output_tokens": 1000},
            load_task(
                Path(__file__).resolve().parents[2]
                / "inference/tasks/student_summary.json"
            ),
            payload,
            generate=fake,
        )
        self.assertEqual(len(calls), before)
        self.assertEqual(
            resumed["sections"]["student_summary"]["value"], section["value"]
        )
        self.assertEqual(len(resumed["provenance"]["reused_scopes"]), 3)
        self.assertNotIn("student_summary", resumed["provenance"]["section_origins"])
        for suffix in [
            " No reviews are available for the current instructor.",
            " (review:1).",
        ]:
            before = len(calls)
            misleading = copy.deepcopy(payload)
            misleading["summary_seed"]["output"]["sections"]["student_summary"][
                "value"
            ]["historical_context"][0]["text"] += suffix
            corrected, _ = generate_student(
                {"model": "test", "revision": "abc", "max_output_tokens": 1000},
                load_task(
                    Path(__file__).resolve().parents[2]
                    / "inference/tasks/student_summary.json"
                ),
                misleading,
                generate=fake,
            )
            self.assertEqual(len(calls), before + 1)
            self.assertEqual(calls[-1]["mode"], "history")
            self.assertEqual(len(corrected["provenance"]["reused_scopes"]), 2)
            self.assertEqual(
                corrected["sections"]["student_summary"]["value"][
                    "current_instructors"
                ],
                section["value"]["current_instructors"],
            )
        before = len(calls)
        from uwcourses.models import digest

        old_profile = {
            "model": "test",
            "revision": "abc",
            "max_output_tokens": 1000,
            "request_timeout_seconds": 900,
        }
        legacy = copy.deepcopy(result)
        legacy_value = legacy["sections"]["student_summary"]["value"]
        legacy_value["profile_hash"] = digest(old_profile)
        legacy_value["errors"] = [{"mode": "professor", "instructor_uid": "uw:1"}]
        retry_payload = copy.deepcopy(payload)
        retry_payload["summary_seed"] = {
            "job_id": "legacy",
            "profile": old_profile,
            "output": legacy,
            "failed_subtasks": [
                {
                    "mode": "professor",
                    "instructor_uid": "uw:1",
                    "conversation": ["saved repair turn"],
                    "error": "UnexpectedModelBehavior: validation retries exhausted",
                }
            ],
        }
        adjusted = {**old_profile, "request_timeout_seconds": 1800, "concurrency": 256}
        task = load_task(
            Path(__file__).resolve().parents[2] / "inference/tasks/student_summary.json"
        )
        repaired, _ = generate_student(adjusted, task, retry_payload, generate=fake)
        self.assertEqual(len(calls), before + 1)
        self.assertEqual(calls[-1]["_history"], ["saved repair turn"])
        self.assertEqual(len(repaired["provenance"]["reused_scopes"]), 2)
        self.assertTrue(profiles_seen[-1]["thinking"])
        self.assertTrue(repaired["provenance"]["subtasks"][0]["inference"]["thinking"])
        generate_student(
            {**adjusted, "temperature": 0.1}, task, retry_payload, generate=fake
        )
        self.assertEqual(len(calls), before + 4)
        self.assertTrue(all("_history" not in call for call in calls[-3:]))
        self.assertTrue(all(not p["thinking"] for p in profiles_seen[-3:]))
        retry_payload["summary_seed"]["failed_subtasks"][0]["error"] = (
            "ModelAPIError: server unavailable"
        )
        generate_student(adjusted, task, retry_payload, generate=fake)
        self.assertFalse(profiles_seen[-1]["thinking"])
        exhausted = copy.deepcopy(retry_payload)
        larger_profile = {**adjusted, "max_output_tokens": 16384}
        exhausted["summary_seed"]["profile"] = larger_profile
        exhausted["summary_seed"]["output"]["sections"]["student_summary"]["value"][
            "profile_hash"
        ] = digest(larger_profile)
        exhausted["summary_seed"]["failed_subtasks"][0]["error"] = (
            "UnexpectedModelBehavior: Model token limit (8192) exceeded before any response was generated."
        )
        repaired, _ = generate_student(larger_profile, task, exhausted, generate=fake)
        self.assertEqual(profiles_seen[-1]["max_output_tokens"], 16384)
        self.assertEqual(calls[-1]["_history"], ["saved repair turn"])
        self.assertEqual(len(repaired["provenance"]["reused_scopes"]), 2)
        self.assertEqual(
            repaired["provenance"]["subtasks"][0]["inference"]["max_output_tokens"],
            16384,
        )
        exhausted["summary_seed"]["failed_subtasks"][0].update(
            error="UnexpectedModelBehavior: Model token limit (16384) exceeded before any response was generated.",
            inference={"thinking": True, "max_output_tokens": 16384},
            grounding_checks=[
                {
                    "input": {
                        "claims": [
                            {
                                "claim_id": "claim:1",
                                "text": "Incorrect instructor attribution.",
                            }
                        ]
                    },
                    "output": {
                        "issues": [
                            {
                                "claim_id": "claim:1",
                                "reason": "The cited review concerns a different instructor.",
                            }
                        ]
                    },
                }
            ],
        )
        direct, _ = generate_student(larger_profile, task, exhausted, generate=fake)
        self.assertFalse(profiles_seen[-1]["thinking"])
        self.assertEqual(profiles_seen[-1]["max_output_tokens"], 4096)
        self.assertTrue(calls[-1]["_compact_history"])
        self.assertEqual(
            calls[-1]["repair_feedback"],
            [
                {
                    "claim": "Incorrect instructor attribution.",
                    "reason": "The cited review concerns a different instructor.",
                }
            ],
        )
        self.assertEqual(calls[-1]["_history"], ["saved repair turn"])
        self.assertEqual(len(direct["provenance"]["reused_scopes"]), 2)
        before = len(calls)
        archive = {
            "file": "tables/observations.parquet",
            "entity_id": "grade-source",
            "source": "madgrades",
            "kind": "grades",
        }
        payload["student_context"]["grade_records"][0]["citation"]["source_record"] = (
            archive
        )
        anchored, _ = generate_student(
            {"model": "test", "revision": "abc", "max_output_tokens": 1000},
            load_task(
                Path(__file__).resolve().parents[2]
                / "inference/tasks/student_summary.json"
            ),
            payload,
            generate=fake,
        )
        self.assertEqual(len(calls), before)
        self.assertEqual(
            anchored["sections"]["student_summary"]["value"]["quick_take"][-1][
                "citations"
            ][0]["source_record"],
            archive,
        )
        payload["student_context"]["has_description"] = False
        limited, _ = generate_student(
            {"model": "test", "revision": "abc", "max_output_tokens": 1000},
            load_task(
                Path(__file__).resolve().parents[2]
                / "inference/tasks/student_summary.json"
            ),
            payload,
            generate=fake,
        )
        self.assertEqual(
            {k: v for k, v in limited["sections"].items() if k != "student_summary"},
            {
                k: v
                for k, v in payload["summary_seed"]["output"]["sections"].items()
                if k != "student_summary"
            },
        )
        self.assertEqual(limited["provenance"]["section_overrides"], {})
        self.assertEqual(result["sections"]["search_profile"], base["search_profile"])

    def test_current_roster_uses_term_and_deduplicates_cross_listings(self):
        from uwcourses.student_context import StudentContext

        class DB:
            def execute(self, *args):
                return []

        person = {"name": {"first": "Jane", "last": "Doe"}, "netid": "jdoe"}
        current = {
            "course_reference": {"subjects": ["COMPSCI"], "course_number": 300},
            "term": "1272",
            "sections": [
                {
                    "sections": [
                        {
                            "type": "LEC",
                            "classUniqueId": {"classNumber": 1},
                            "instructors": [person],
                        },
                        {
                            "type": "DIS",
                            "classUniqueId": {"classNumber": 2},
                            "instructors": [
                                {"name": "Teaching Assistant", "netid": "ta"}
                            ],
                        },
                    ]
                }
            ],
        }
        old = {**current, "term": "1264"}

        class Store:
            db = DB()

            def run(self, run):
                return {"semester": "1272"}

            def records(self, run, kind):
                return {
                    "terms": {"1272": {"name": "Fall 2026"}},
                    "offerings": {"one": current, "cross_listing": current, "old": old},
                    "grades": {
                        "grade-source": {
                            "course_reference": current["course_reference"],
                            "source_id": "grade-source",
                            "courseOfferings": [
                                {
                                    "termCode": 1264,
                                    "cumulative": {},
                                    "sections": [
                                        {
                                            "sectionNumber": 1,
                                            "instructors": [{"name": "Jane Doe"}],
                                        }
                                    ],
                                }
                            ],
                        }
                    },
                }[kind]

        class Base:
            reviews = {}
            courses = {"COMPSCI 300": {"description": "Programming."}}

            def resolve(self, key):
                return key if key == "COMPSCI 300" else None

        context = StudentContext(Store(), "run", Base()).get("COMPSCI 300")
        self.assertEqual(
            [p["name"] for p in context["current_instructors"]], ["Jane Doe"]
        )
        self.assertEqual(context["term_id"], "1272")
        self.assertEqual(context["historical_reviews"], [])
        for row in [
            context["grade_records"][0],
            context["current_instructors"][0]["grade_records"][0],
        ]:
            self.assertEqual(
                row["citation"]["source_record"],
                {
                    "file": "tables/observations.parquet",
                    "source": "madgrades",
                    "kind": "grades",
                    "entity_id": "grade-source",
                },
            )
