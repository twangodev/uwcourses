import copy
import unittest
from pathlib import Path

from uwcourses.grounding import grounding_request
from uwcourses.tasks import load_task
from uwcourses.student_summary import validate_claims
from test_student_summary import review


class GroundingEvidenceTests(unittest.TestCase):
    def test_unrelated_roster_is_not_available_as_claim_evidence(self):
        source = review("cited", "Reviewed Instructor")
        source.update(citation_id=source["id"], instructor_scope="historical")
        payload = {
            "course_id": source["course_id"],
            "mode": "history",
            "term_id": source["date"][:4],
            "reviews": [source],
            "current_instructors": ["Unreviewed Instructor"],
        }
        task = load_task(
            Path(__file__).resolve().parents[2] / "inference/tasks/student_summary.json"
        )
        draft = {
            "summary": [
                {"text": source["comment"], "review_ids": [source["citation_id"]]}
            ]
        }
        first = grounding_request(task, draft, payload)
        changed = copy.deepcopy(payload)
        changed["current_instructors"] = []
        self.assertEqual(first, grounding_request(task, draft, changed))
        self.assertNotIn("current_instructors", first[1])
        cited = first[1]["claims"][0]["cited_reviews"][0]
        self.assertEqual(cited["instructor"], source["instructor_name"])
        self.assertEqual(cited["instructor_scope"], source["instructor_scope"])
        self.assertNotIn("scope", cited)
        self.assertEqual(cited["comment"], source["comment"])

    def test_roster_boilerplate_is_rejected_before_model_grounding(self):
        source = review("cited", "Reviewed Instructor")
        source.update(citation_id=source["id"], instructor_scope="historical")
        payload = {"reviews": [source], "mode": "history"}
        supported = {
            "summary": [
                {"text": source["comment"], "review_ids": [source["citation_id"]]}
            ]
        }
        validate_claims(supported, payload)
        for role in ["instructors", "roster"]:
            draft = copy.deepcopy(supported)
            draft["summary"][0]["text"] += (
                f" The current {role} includes an unreviewed instructor."
            )
            with (
                self.subTest(role=role),
                self.assertRaisesRegex(ValueError, "current roster"),
            ):
                validate_claims(draft, payload)
