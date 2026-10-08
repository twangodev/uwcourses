import copy
import json
import unittest

import test_unified
from uwcourses.reuse import ReuseIndex, facts
from uwcourses.unified import validate_section
from uwcourses.agents import evidence_view, output_budget
from uwcourses.requirements import restore_quotes, shared_subject_references


class ReuseTests(unittest.TestCase):
    def setUp(self):
        f = self.f = test_unified.UnifiedTests()
        f.setUp()
        self.index = ReuseIndex.__new__(ReuseIndex)
        self.index.context, self.index.task = f.context, f.task
        self.index.contexts = {"old": copy.deepcopy(f.context)}
        self.previous = {
            "model": "test",
            "model_revision": "a" * 40,
            "sections": {
                "search_profile": validate_section(
                    "search_profile", f.search, f.task, f.root, f.lookup
                ),
                "requirements": validate_section(
                    "requirements", f.requirements, f.task, f.root, f.lookup
                ),
            },
            "provenance": {},
        }
        self.index.jobs = {
            "job": (
                {"source_run": "old"},
                {
                    "task": {
                        "version": 5,
                        "search_profile_evidence_version": 2,
                    }
                },
            )
        }
        self.refresh()

    def refresh(self):
        self.index.rows = {"COMPSCI 300": ("job", json.dumps(self.previous))}

    def test_reviews_refresh_without_regenerating_unchanged_facts(self):
        self.f.root["reviews"] = [{"comment": "New review"}]
        seed = self.index.seed("COMPSCI 300")
        self.assertEqual(
            seed["output"]["sections"]["search_profile"],
            self.previous["sections"]["search_profile"],
        )
        self.assertEqual(
            seed["output"]["sections"]["student_experience"]["status"], "invalid"
        )
        self.assertEqual(seed["section_origins"]["search_profile"]["task_version"], 5)
        self.assertEqual(
            seed["section_origins"]["search_profile"]["model_revision"], "a" * 40
        )

    def test_changed_source_or_supporting_course_prevents_reuse(self):
        for field in ("description", "requirements_text"):
            with self.subTest(field=field):
                original = self.f.root[field]
                self.f.root[field] = "Changed"
                self.assertIsNone(self.index.seed("COMPSCI 300"))
                self.f.root[field] = original
        self.previous["provenance"]["dependencies"] = {"COMPSCI 200": "old-fingerprint"}
        self.refresh()
        self.f.context.get("COMPSCI 200")["description"] = "Changed dependency"
        self.assertIsNone(self.index.seed("COMPSCI 300"))

    def test_outcome_only_changes_prevent_description_claim_reuse(self):
        self.f.outcome_evidence()
        self.assertIsNone(
            self.index.seed("COMPSCI 300"), "New outcomes need new skill extraction"
        )
        old = self.index.contexts["old"].get("COMPSCI 300")
        old["official_learning_outcomes"] = copy.deepcopy(
            self.f.root["official_learning_outcomes"]
        )
        self.assertIsNotNone(self.index.seed("COMPSCI 300"))
        outcome = self.f.root["official_learning_outcomes"][0]
        for field, changed in [
            ("text", "Write C programs."),
            ("source_url", "https://example.org/new"),
            ("source", "enrollment"),
            ("term", "1272"),
            ("catalog_year", "2027-2028"),
        ]:
            with self.subTest(field=field):
                original = outcome[field]
                outcome[field] = changed
                self.assertIsNone(self.index.seed("COMPSCI 300"))
                outcome[field] = original
        self.f.root["official_learning_outcomes"] = []
        self.assertIsNone(
            self.index.seed("COMPSCI 300"), "Removed evidence invalidates reuse"
        )

    def test_outcome_refetch_time_does_not_invalidate_reuse(self):
        self.f.outcome_evidence()
        old = self.index.contexts["old"].get("COMPSCI 300")
        old["official_learning_outcomes"] = copy.deepcopy(
            self.f.root["official_learning_outcomes"]
        )
        self.f.root["official_learning_outcomes"][0]["observed_at"] = "2026-10-09"
        self.assertEqual(facts(old), facts(self.f.root))
        self.assertIsNotNone(self.index.seed("COMPSCI 300"))

    def test_old_description_only_policy_regenerates_search_but_keeps_requirements(
        self,
    ):
        self.index.jobs["job"][1]["task"].pop("search_profile_evidence_version")
        seed = self.index.seed("COMPSCI 300")
        self.assertEqual(
            seed["output"]["sections"]["search_profile"]["status"], "invalid"
        )
        self.assertEqual(seed["output"]["sections"]["requirements"]["status"], "valid")
        self.assertNotIn("search_profile", seed["section_origins"])

    def test_no_reviews_requires_no_new_sentiment(self):
        seed = self.index.seed("COMPSCI 300")
        self.assertEqual(
            seed["output"]["sections"]["student_experience"]["status"],
            "insufficient_evidence",
        )

    def test_unchanged_missing_lookup_is_reusable_but_new_identity_is_not(self):
        self.previous["provenance"]["dependencies"] = {"COMPSCI 302": "missing"}
        self.refresh()
        self.assertIsNotNone(self.index.seed("COMPSCI 300"))
        self.f.context.courses["COMPSCI 302"] = test_unified.course("COMPSCI 302")
        self.assertIsNone(self.index.seed("COMPSCI 300"))

    def test_unchanged_course_without_reviews_makes_no_model_request(self):
        from pydantic_ai.models.function import FunctionModel
        from uwcourses.agents import generate_unified

        def forbidden(*args):
            raise AssertionError("Unchanged accepted evidence needs no inference")

        seed = self.index.seed("COMPSCI 300")
        output, usage = generate_unified(
            self.f.profile,
            self.f.task,
            {**self.f.root, "reuse_seed": seed},
            self.f.context,
            FunctionModel(forbidden),
        )
        self.assertEqual(usage["requests"], 0)
        self.assertTrue(output["provenance"]["validation_only"])
        self.assertEqual(
            output["provenance"]["section_origins"]["search_profile"]["source_run"],
            "old",
        )

    def test_saved_claims_are_revalidated(self):
        self.previous["sections"]["search_profile"]["value"]["summary"]["evidence"][0][
            "quote"
        ] = "Invented"
        self.refresh()
        seed = self.index.seed("COMPSCI 300")
        self.assertEqual(
            seed["output"]["sections"]["search_profile"]["status"], "invalid"
        )
        self.assertNotIn("search_profile", seed["section_origins"])

    def test_repair_evidence_excludes_accepted_sections(self):
        self.f.root["reviews"] = [{"comment": "X" * 50000}]
        view = evidence_view(self.f.root, {"requirements"})
        self.assertNotIn("reviews", view)
        self.assertNotIn("description", view)
        self.assertIn("requirements_text", view)
        small = output_budget(
            {"context_length": 32768, "max_output_tokens": 16384},
            [],
            self.f.task,
            {},
            repair=True,
        )
        self.assertLessEqual(small, 8192)

    def test_shorthand_preserves_source_and_does_not_invent_subjects(self):
        payload = {
            "requirements_text": "COMP SCI 200,220, 302,310, 301",
            "linked_courses": [{"subjects": ["COMPSCI"], "course_number": 200}],
        }
        refs = shared_subject_references(payload)
        self.assertEqual([r["course_number"] for r in refs], [220, 302, 310, 301])
        for r in refs:
            self.assertEqual(
                payload["requirements_text"][r["start"] : r["end"]], r["text"]
            )
        value = {
            "status": "needs_review",
            "notes": [],
            "nodes": [
                {"kind": "condition", "condition": "COMP SCI 302", "evidence": "302"}
            ],
        }
        restore_quotes(value, payload)
        self.assertEqual(value["nodes"][0]["condition"], "302")
        value["nodes"][0]["condition"] = "MATH 302"
        restore_quotes(value, payload)
        self.assertEqual(value["nodes"][0]["condition"], "MATH 302")

    def test_ambiguous_semicolons_preserve_best_effort_tree(self):
        self.f.root["requirements_text"] = (
            "COMP SCI 200; graduate standing; declared in certificate."
        )
        value = {
            "status": "parsed",
            "root": "n",
            "nodes": [
                {
                    "id": "n",
                    "kind": "condition",
                    "children": [],
                    "course": None,
                    "condition": self.f.root["requirements_text"],
                    "evidence": self.f.root["requirements_text"],
                }
            ],
            "notes": [],
        }
        result = validate_section(
            "requirements", value, self.f.task, self.f.root, self.f.lookup
        )
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["value"]["root"], "n")
        self.assertEqual(len(result["value"]["nodes"]), 1)
        self.assertTrue(result["value"]["notes"])

    def test_related_lookup_cannot_replace_target_requirements_or_reviews(self):
        related = {
            "course_id": "COMPSCI 200",
            "course_reference": {"subjects": ["COMPSCI"], "course_number": 200},
            "title": "Programming I",
            "description": "Introduction to programming.",
            "requirements_text": "MATH 221",
            "reviews": [{"id": "foreign"}],
        }
        ast = evidence_view(
            related, {"requirements", "student_experience"}, related=True
        )
        self.assertEqual(set(ast), {"course_id", "course_reference", "title"})
        search = evidence_view(related, {"search_profile"}, related=True)
        self.assertIn("description", search)
        self.assertNotIn("requirements_text", search)
        self.assertNotIn("reviews", search)
