from pathlib import Path
import unittest

from uwcourses.course_context import CourseLookup, text_view
from uwcourses.models import digest
from uwcourses.tasks import load_task
from uwcourses.requirements import graph_diagnostics
from uwcourses.unified import (
    compare_parsers,
    source_quote,
    validate_section,
)

TASK = Path(__file__).resolve().parents[2] / "inference/tasks/course_enrichment.json"


def course(key, description="Programming using objects.", requirements="None"):
    return {
        "course_id": key,
        "course_reference": {
            "subjects": ["COMPSCI"],
            "course_number": int(key.split()[-1]),
        },
        "title": "Programming",
        "description": description,
        "requirements_text": requirements,
        "linked_courses": [],
        "history": {"observations": 0, "recent_offerings": []},
        "reviews": [],
        "original_requirements": {"text": requirements, "ast": None},
    }


class Context:
    def __init__(self):
        self.courses = {
            key: course(key)
            for key in ["COMPSCI 300", "COMPSCI 200", "COMPSCI 100", "COMPSCI 400"]
        }

    def resolve(self, key):
        return key if key in self.courses else None

    def get(self, key):
        return self.courses.get(key)

    def fingerprint(self, key):
        return digest(self.get(key))


class UnifiedTests(unittest.TestCase):
    def outcome_evidence(self):
        self.root["official_learning_outcomes"] = [
            {
                "text": "Write and debug Python programs.",
                "source": "guide",
                "source_url": "https://guide.wisc.edu/courses/comp_sci/",
                "observed_at": "2026-10-08",
                "term": None,
                "catalog_year": "2026-2027",
            }
        ]
        return {
            "course_id": "COMPSCI 300",
            "field": "official_learning_outcomes",
            "outcome_index": 0,
            "source_url": self.root["official_learning_outcomes"][0]["source_url"],
            "quote": "Write and debug Python programs.",
        }

    def test_outcomes_support_skills_without_description(self):
        citation = self.outcome_evidence()
        self.root["description"] = ""
        self.search["summary"] = {
            "text": "Programming in Python.",
            "evidence": [citation],
        }
        self.search["skills_taught"] = [
            {"text": "Debug Python programs", "evidence": [citation]}
        ]
        self.search["activity_tags"] = [
            {"label": "programming", "evidence": [citation]}
        ]
        value = validate_section(
            "search_profile", self.search, self.task, self.root, self.lookup
        )
        self.assertEqual(value["status"], "valid")
        self.assertEqual(value["value"]["activity_tags"][0]["evidence"][0], citation)

    def test_outcome_citations_reject_wrong_source_index_and_paraphrase(self):
        citation = self.outcome_evidence()
        self.search["skills_taught"] = [
            {"text": "Debug Python programs", "evidence": [citation]}
        ]
        for field, bad in [
            ("source_url", "https://example.org"),
            ("outcome_index", 10),
            ("quote", "Write/debug Python programs."),
        ]:
            with self.subTest(field=field):
                old = citation[field]
                citation[field] = bad
                with self.assertRaises(ValueError):
                    validate_section(
                        "search_profile", self.search, self.task, self.root, self.lookup
                    )
                citation[field] = old

    def test_activity_citations_reject_titles_and_duplicate_labels(self):
        citation = self.outcome_evidence()
        self.search["activity_tags"] = [
            {"label": "programming", "evidence": [citation]}
        ] * 2
        with self.assertRaisesRegex(ValueError, "distinct labels"):
            validate_section(
                "search_profile", self.search, self.task, self.root, self.lookup
            )
        self.search["activity_tags"] = [
            {
                "label": "programming",
                "evidence": [
                    {
                        "course_id": "COMPSCI 300",
                        "field": "title",
                        "quote": "Programming",
                    }
                ],
            }
        ]
        with self.assertRaisesRegex(ValueError, "title alone"):
            validate_section(
                "search_profile", self.search, self.task, self.root, self.lookup
            )

    def test_missing_description_does_not_preserve_inferred_metadata(self):
        self.root["description"] = ""
        result = validate_section(
            "search_profile", self.search, self.task, self.root, self.lookup
        )
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertIsNone(result["value"])

    def setUp(self):
        self.task = load_task(TASK)
        self.task["ast_repair_attempts"] = 2
        self.context = Context()
        self.root = self.context.get("COMPSCI 300")
        self.lookup = CourseLookup(self.context, "COMPSCI 300")
        self.profile = {"model": "test", "revision": "a" * 40}
        self.search = {
            "summary": {
                "text": "Object-oriented programming.",
                "evidence": [
                    {
                        "course_id": "COMPSCI 300",
                        "field": "description",
                        "quote": "Programming using objects.",
                    }
                ],
            },
            "topics": [],
            "skills_taught": [],
            "assumed_background": [],
            "search_phrases": ["object oriented programming"],
        }
        self.requirements = {"status": "none", "root": None, "nodes": [], "notes": []}
        self.experience = {"status": "insufficient_evidence", "themes": []}

    def test_wrong_course_citation_provides_exact_source_feedback(self):
        self.root["requirements_text"] = "COMPSCI 200 or graduate standing"
        self.search["assumed_background"] = [
            {
                "text": "Prior programming",
                "evidence": [
                    {
                        "course_id": "COMPSCI 200",
                        "field": "requirements_text",
                        "quote": "COMPSCI 200",
                    }
                ],
            }
        ]
        with self.assertRaisesRegex(
            ValueError, "course containing the quote"
        ) as caught:
            validate_section(
                "search_profile", self.search, self.task, self.root, self.lookup
            )
        self.assertIn("COMPSCI 300", str(caught.exception))
        self.assertEqual(
            self.search["assumed_background"][0]["evidence"][0]["course_id"],
            "COMPSCI 200",
        )

    def test_lookup_depth_cycles_missing_and_budget(self):
        self.lookup.get_course("COMPSCI 200", "COMPSCI 300")
        self.assertTrue(
            self.lookup.get_course("COMPSCI 300", "COMPSCI 200")["already_provided"]
        )
        self.lookup.get_course("COMPSCI 100", "COMPSCI 200")
        self.assertIn("error", self.lookup.get_course("COMPSCI 400", "COMPSCI 100"))
        self.lookup.get_course("COMPSCI 999", "COMPSCI 300")
        old = self.lookup.dependencies["COMPSCI 999"]
        self.context.courses["COMPSCI 999"] = course("COMPSCI 999")
        self.assertNotEqual(old, self.context.fingerprint("COMPSCI 999"))
        self.lookup.get_course("COMPSCI 400", "COMPSCI 300")
        self.assertIn(
            "budget", self.lookup.get_course("COMPSCI 100", "COMPSCI 300")["error"]
        )

    def test_background_cannot_become_taught_content_or_formal_requirement(self):
        self.lookup.get_course("COMPSCI 400", "COMPSCI 300")
        self.search["summary"]["evidence"][0]["course_id"] = "COMPSCI 400"
        with self.assertRaisesRegex(ValueError, "Taught content"):
            validate_section(
                "search_profile", self.search, self.task, self.root, self.lookup
            )
        self.root["description"] = "Recommended: COMPSCI 400."
        self.root["requirements_text"] = "Graduate/professional standing"
        value = {
            "status": "parsed",
            "root": "n",
            "notes": [],
            "nodes": [
                {
                    "id": "n",
                    "kind": "course",
                    "children": [],
                    "condition": None,
                    "evidence": "Graduate/professional standing",
                    "course": {
                        "subjects": ["COMPSCI"],
                        "course_number": 400,
                        "timing": "prior",
                        "minimum_grade": None,
                    },
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "absent from the source links"):
            validate_section("requirements", value, self.task, self.root, self.lookup)

    def test_sentiment_requires_root_reviews_and_keeps_attribution(self):
        value = {
            "status": "supported",
            "themes": [
                {
                    "aspect": "projects",
                    "sentiment": "positive",
                    "summary": "Reviews from 2025 described useful projects.",
                    "review_ids": ["r1"],
                }
            ],
        }
        with self.assertRaises(ValueError):
            validate_section(
                "student_experience", value, self.task, self.root, self.lookup
            )
        self.root["reviews"] = [
            {
                "id": "r1",
                "course_id": "COMPSCI 300",
                "comment": "Projects were useful.",
                "date": "2025-05-01",
                "instructor_id": "i1",
                "source_url": "https://example.com/review",
            }
        ]
        result = validate_section(
            "student_experience", value, self.task, self.root, self.lookup
        )
        self.assertEqual(result["value"]["themes"][0]["evidence_count"], 1)
        self.assertEqual(
            result["value"]["themes"][0]["evidence"][0]["instructor_id"], "i1"
        )
        self.assertNotIn("evidence_count", value["themes"][0])

    def test_named_instructor_theme_cannot_borrow_another_teachers_reviews(self):
        self.root["reviews"] = [
            {
                "id": "r1",
                "course_id": "COMPSCI 300",
                "comment": "Clear lectures.",
                "date": "2025-05-01",
                "instructor_id": "i1",
                "instructor_name": "Jane Doe",
            },
            {
                "id": "r2",
                "course_id": "COMPSCI 300",
                "comment": "Helpful teacher.",
                "date": "2024-05-01",
                "instructor_id": "i2",
                "instructor_name": "John Roe",
            },
        ]
        theme = {
            "aspect": "teaching_clarity",
            "sentiment": "positive",
            "summary": "A cited review praises Jane Doe for clear lectures.",
            "subject_instructor_id": "i1",
            "review_ids": ["r1"],
        }
        value = {"status": "supported", "themes": [theme]}
        result = validate_section(
            "student_experience", value, self.task, self.root, self.lookup
        )
        self.assertEqual(result["value"]["themes"][0]["subject_instructor_id"], "i1")
        for ids in (["r2"], ["r1", "r2"]):
            theme["review_ids"] = ids
            with self.assertRaisesRegex(ValueError, "only reviews attributed"):
                validate_section(
                    "student_experience", value, self.task, self.root, self.lookup
                )
        theme["review_ids"] = ["r1"]
        theme["subject_instructor_id"] = None
        with self.assertRaisesRegex(ValueError, "Name the instructor"):
            validate_section(
                "student_experience",
                value,
                {**self.task, "named_instructor_themes": True},
                self.root,
                self.lookup,
            )
        theme["subject_instructor_id"] = "i1"
        theme["summary"] = "A good instructor."
        with self.assertRaisesRegex(ValueError, "exact instructor_name"):
            validate_section(
                "student_experience", value, self.task, self.root, self.lookup
            )

    def test_sentiment_summary_preserves_historical_teacher_scope(self):
        self.root["reviews"] = [
            {
                "id": key,
                "course_id": "COMPSCI 300",
                "comment": "Useful projects.",
                "date": year + "-01-01",
                "instructor_id": "rmp:1",
                "instructor_name": "Jane Doe",
                "source_url": "https://example.com/review",
            }
            for key, year in [("r1", "2017"), ("r2", "2022")]
        ]
        value = {
            "status": "supported",
            "themes": [
                {
                    "aspect": "projects",
                    "sentiment": "positive",
                    "summary": "Useful projects.",
                    "review_ids": ["r1", "r2"],
                }
            ],
        }
        result = validate_section(
            "student_experience", value, self.task, self.root, self.lookup
        )
        theme = result["value"]["themes"][0]
        self.assertEqual(theme["summary"], "Useful projects.")
        self.assertEqual(
            theme["scope"],
            {
                "instructors": [{"id": "rmp:1", "name": "Jane Doe"}],
                "review_year_start": "2017",
                "review_year_end": "2022",
                "historical": True,
            },
        )
        value["themes"][0]["summary"] = (
            "Reviews from 2020 to 2021 describe useful projects."
        )
        result = validate_section(
            "student_experience", value, self.task, self.root, self.lookup
        )
        self.assertEqual(
            result["value"]["themes"][0]["summary"],
            "Reviews of Jane Doe (2017–2022) describe useful projects.",
        )
        self.assertEqual(result["citation_repairs"][0]["field"], "summary_scope")

    def test_sentiment_can_cite_the_full_thirty_review_sample(self):
        self.root["reviews"] = [
            {
                "id": str(i),
                "course_id": "COMPSCI 300",
                "comment": "Useful projects.",
                "date": "2017-01-01",
                "instructor_id": "rmp:1",
                "instructor_name": "Jane Doe",
            }
            for i in range(30)
        ]
        value = {
            "status": "supported",
            "themes": [
                {
                    "aspect": "projects",
                    "sentiment": "positive",
                    "summary": "Reviews of Jane Doe (2017) describe useful projects.",
                    "review_ids": [str(i) for i in range(30)],
                }
            ],
        }
        result = validate_section(
            "student_experience", value, self.task, self.root, self.lookup
        )
        self.assertEqual(result["value"]["themes"][0]["evidence_count"], 30)

    def test_display_normalization_preserves_original_input(self):
        raw = r"COMP\xa0SCI\xa0300"
        self.assertEqual(text_view(raw), "COMP SCI 300")
        self.assertEqual(raw, r"COMP\xa0SCI\xa0300")

    def test_abbreviated_citations_expand_only_ordered_source_fragments(self):
        self.assertEqual(
            source_quote("Programming...objects.", "Programming using objects."),
            "Programming using objects.",
        )
        self.assertIsNone(
            source_quote("objects...Programming", "Programming using objects.")
        )
        self.assertIsNone(
            source_quote("Programming...Java", "Programming using objects.")
        )
        self.search["summary"]["evidence"][0]["quote"] = "Programming...objects."
        result = validate_section(
            "search_profile", self.search, self.task, self.root, self.lookup
        )
        self.assertEqual(
            result["value"]["summary"]["evidence"][0]["quote"],
            "Programming using objects.",
        )
        self.assertEqual(
            result["citation_repairs"][0]["original"]["quote"], "Programming...objects."
        )
        self.assertEqual(
            self.search["summary"]["evidence"][0]["quote"], "Programming...objects."
        )

    def test_legacy_disagreement_flags_review_without_replacing_candidate(self):
        value = {
            "status": "parsed",
            "root": "n",
            "nodes": [
                {
                    "id": "n",
                    "kind": "condition",
                    "children": [],
                    "condition": "Graduate standing",
                    "course": None,
                    "evidence": "Graduate standing",
                }
            ],
            "notes": [],
        }
        section = {"status": "valid", "value": value}
        compare_parsers(section, {"ast": "Graduate standing"})
        self.assertTrue(section["parser_comparison"]["structural_match"])
        compare_parsers(section, {"ast": "Consent of instructor"})
        self.assertEqual(section["status"], "needs_review")
        self.assertFalse(section["parser_comparison"]["structural_match"])
        self.assertEqual(section["value"], value)

    def test_graph_feedback_collects_quotes_cycles_unreachable_and_exclusions(self):
        node = {
            "id": "n0",
            "kind": "any",
            "children": ["n0", "missing"],
            "evidence": "invented",
            "condition": None,
            "course": None,
        }
        value = {
            "status": "needs_review",
            "root": "n0",
            "notes": ["review"],
            "nodes": [node, {**node, "id": "orphan", "children": []}],
        }
        errors = "\n".join(
            graph_diagnostics(
                value,
                {
                    "requirements_text": "Graduate standing. Not open to students with credit for COMP SCI 367."
                },
            )
        )
        for expected in [
            "evidence",
            "references itself",
            "missing nodes",
            "Cycle",
            "Unreachable nodes: orphan",
            "Missing global exclusion",
            "367",
        ]:
            self.assertIn(expected, errors)

    def test_citation_quote_style_and_title_restore_literal_evidence(self):
        for quote in ["the golden age of Hollywood", "the 'golden age' of Hollywood"]:
            resolved = source_quote(quote, 'the "golden age" of Hollywood')
            self.assertEqual(resolved, 'the "golden age" of Hollywood')
        self.assertIsNone(source_quote("students can enroll", "students cannot enroll"))
        self.assertIsNone(source_quote("students cant enroll", "students can't enroll"))
        self.root["title"] = "FOURTH SEMESTER URDU"
        self.search["summary"]["evidence"][0]["quote"] = self.root["title"]
        result = validate_section(
            "search_profile", self.search, self.task, self.root, self.lookup
        )
        self.assertEqual(result["value"]["summary"]["evidence"][0]["field"], "title")
        self.assertEqual(
            result["citation_repairs"][0]["original"]["field"], "description"
        )

    def test_excluded_courses_cannot_supply_assumed_background(self):
        self.lookup.get_course("COMPSCI 200", "COMPSCI 300")
        self.root["requirements_text"] = (
            "Graduate standing. Not open to students with credit for COMP SCI 200."
        )
        self.search["assumed_background"] = [
            {
                "text": "Prior object-oriented programming",
                "evidence": [
                    {
                        "course_id": "COMPSCI 200",
                        "field": "description",
                        "quote": "Programming using objects.",
                    }
                ],
            }
        ]
        with self.assertRaisesRegex(ValueError, "credit exclusion"):
            validate_section(
                "search_profile", self.search, self.task, self.root, self.lookup
            )
        self.root["requirements_text"] = "COMP SCI 200"
        self.assertEqual(
            validate_section(
                "search_profile", self.search, self.task, self.root, self.lookup
            )["status"],
            "valid",
        )

    def test_clipped_summary_is_rejected(self):
        self.search["summary"]["text"] = "Genomics applications in microbi,"
        with self.assertRaisesRegex(ValueError, "clipped"):
            validate_section(
                "search_profile", self.search, self.task, self.root, self.lookup
            )

    def test_none_legacy_ast_agrees_with_empty_graph(self):
        section = {"status": "valid", "value": self.requirements}
        compare_parsers(section, {"ast": "None"})
        self.assertTrue(section["parser_comparison"]["structural_match"])
        self.assertEqual(section["status"], "valid")

    def test_mislabeled_requirement_citation_is_resolved_without_allowing_taught_content(
        self,
    ):
        self.root["requirements_text"] = "Graduate standing"
        self.search["assumed_background"] = [
            {
                "text": "Graduate standing",
                "evidence": [
                    {
                        "course_id": "COMPSCI 300",
                        "field": "description",
                        "quote": "Graduate standing",
                    }
                ],
            }
        ]
        result = validate_section(
            "search_profile", self.search, self.task, self.root, self.lookup
        )
        self.assertEqual(
            result["value"]["assumed_background"][0]["evidence"][0]["field"],
            "requirements_text",
        )
        self.search["summary"]["evidence"] = self.search["assumed_background"][0][
            "evidence"
        ]
        with self.assertRaisesRegex(ValueError, "Taught content"):
            validate_section(
                "search_profile", self.search, self.task, self.root, self.lookup
            )
        self.root["title"] = "Graduate standing"
        with self.assertRaisesRegex(ValueError, "Invalid evidence"):
            validate_section(
                "search_profile", self.search, self.task, self.root, self.lookup
            )

    def test_review_handles_resolve_exactly_and_retain_original_ids(self):
        from uwcourses.agents import evidence_view

        self.root["reviews"] = [
            {
                "id": "abcdef1234567890",
                "date": "2020-01-01",
                "comment": "Clear explanations.",
                "instructor_id": "rmp:1",
            }
        ]
        view = evidence_view(self.root, {"student_experience"})
        self.assertEqual(view["reviews"][0]["citation_id"], "review:1")
        self.assertNotIn("citation_id", self.root["reviews"][0])
        value = {
            "status": "supported",
            "themes": [
                {
                    "aspect": "teaching_clarity",
                    "sentiment": "positive",
                    "summary": "A review describes clear explanations.",
                    "review_ids": ["review:1"],
                }
            ],
        }
        result = validate_section(
            "student_experience", value, self.task, self.root, self.lookup
        )
        self.assertEqual(
            result["value"]["themes"][0]["review_ids"], ["abcdef1234567890"]
        )
        self.assertEqual(result["citation_repairs"][0]["original"], ["review:1"])
        for invalid in [["abcdef123"], ["review:2"], ["review:1", "abcdef1234567890"]]:
            value["themes"][0]["review_ids"] = invalid
            with self.assertRaisesRegex(ValueError, "Use distinct citation_id"):
                validate_section(
                    "student_experience", value, self.task, self.root, self.lookup
                )

    def test_full_field_quote_restores_case_and_spacing_without_fuzzy_matching(self):
        self.assertEqual(
            source_quote("ITALIAN  THEATRE", "Italian Theatre"), "Italian Theatre"
        )
        self.assertIsNone(source_quote("Italian literature", "Italian Theatre"))
