import json
import sqlite3
import unittest
from uwcourses_site.discovery import (
    build_discovery,
    class_meeting_rows,
    designation_parts,
    requisite_kind,
    seasons_in,
)


class DiscoveryTests(unittest.TestCase):
    def test_latest_reviews_keep_unmapped_courses_and_profiles_separate(self):
        db = sqlite3.connect(":memory:")
        db.executescript(
            "CREATE TABLE courses(uid,payload);CREATE TABLE grades(uid,term,section,payload);"
        )
        db.execute(
            "INSERT INTO courses VALUES(?,?)",
            (
                "c",
                json.dumps({"offerings": [{"term_id": "1272"}, {"term_id": "1272"}]}),
            ),
        )
        db.executemany(
            "INSERT INTO grades VALUES(?,?,?,?)",
            [("c", "1264", "", '{"a":10}'), ("c", "1264", "001", '{"a":10}')],
        )
        base = {
            "source_instructor_id": "p",
            "source_review_id": "r",
            "course_uid": None,
            "review_date": None,
            "observed_at": "2026-01-01",
            "comment": "old",
        }
        build_discovery(
            db,
            [
                base,
                {**base, "observed_at": "2026-02-01", "comment": "new"},
                {**base, "source_instructor_id": "q"},
            ],
        )
        self.assertEqual(db.execute("SELECT COUNT(*) FROM reviews").fetchone()[0], 2)
        self.assertEqual(
            json.loads(
                db.execute(
                    "SELECT payload FROM reviews WHERE profile_id='p'"
                ).fetchone()[0]
            )["comment"],
            "new",
        )
        self.assertEqual(
            db.execute("SELECT SUM(a) FROM grade_summaries").fetchone()[0], 10
        )
        self.assertEqual(db.execute("SELECT COUNT(*) FROM offerings").fetchone()[0], 1)


class DiscoveryFactTests(unittest.TestCase):
    def test_season_and_requisite_and_designation_rules(self):
        self.assertEqual(seasons_in("Fall, Spring, Summer"), ["fall", "spring", "summer"])
        self.assertEqual(seasons_in("Every Other Fall"), ["fall"])
        self.assertEqual(seasons_in("Occasionally"), [])
        self.assertEqual(seasons_in("Not Applicable"), [])
        self.assertEqual(requisite_kind({"status": "parsed", "nodes": []}), "none")
        self.assertEqual(
            requisite_kind(
                {
                    "status": "parsed",
                    "nodes": [{"condition": "No prerequisites listed.", "course": None}],
                }
            ),
            "none",
        )
        self.assertNotEqual(
            requisite_kind(
                {
                    "status": "needs_review",
                    "nodes": [{"course": {"subjects": ["COMPSCI"], "course_number": 200}}],
                }
            ),
            "none",
        )
        self.assertEqual(
            requisite_kind(
                {
                    "status": "parsed",
                    "nodes": [{"condition": "Satisfied Quantitative Reasoning (QR) A"}],
                }
            ),
            "listed",
        )
        self.assertEqual(
            designation_parts("Breadth - Natural Science"),
            ("breadth", "natural-science"),
        )
        self.assertEqual(
            designation_parts("Comm QR - Quantitative Reasoning B"),
            ("quantitative-reasoning", "b"),
        )
        self.assertEqual(designation_parts("Ethnic Studies"), ("ethnic-studies", "yes"))

    def test_unparsed_meeting_name_is_not_guessed_across_terms(self):
        sections = {
            "c": [
                {
                    "term_id": "1264",
                    "section_type": "LEC",
                    "section_number": "001",
                    "start_date": "2026-09-01T00:00:00+00:00",
                    "end_date": "2026-12-20T00:00:00+00:00",
                },
                {
                    "term_id": "1272",
                    "section_type": "LEC",
                    "section_number": "001",
                    "start_date": "2026-09-02T00:00:00+00:00",
                    "end_date": "2026-12-09T00:00:00+00:00",
                },
            ]
        }
        meeting = {
            "course_uid": "c",
            "meeting_type": "CLASS",
            "name": "seminar",
            "starts_at": "2026-09-23T16:00:00+00:00",
            "ends_at": "2026-09-23T16:50:00+00:00",
        }
        self.assertEqual(class_meeting_rows(sections, [meeting]), [])
        rows = class_meeting_rows({"c": sections["c"][:1]}, [meeting])
        self.assertEqual(rows[0][2:4], ("", ""))

    def test_schedule_seasons_requisites_and_designations_are_indexed(self):
        db = sqlite3.connect(":memory:")
        db.executescript("CREATE TABLE courses(uid,payload);CREATE TABLE grades(uid,term,section,payload);")
        course = {
            "course_uid": "c",
            "course_number": 300,
            "offerings": [
                {"term_id": "1272", "typically_offered": "Fall, Spring"},
                {"term_id": "1272", "typically_offered": "Occasionally"},
            ],
            "requirements": {"status": "parsed", "nodes": []},
            "designations": [
                "Breadth - Natural Science",
                "Comm QR - Quantitative Reasoning B",
                "Level - Intermediate",
            ],
            "sections": [
                {
                    "term_id": "1272",
                    "section_type": "LEC",
                    "section_number": "003",
                    "instruction_mode": "Classroom Instruction",
                    "start_date": "2026-09-02T05:00:00+00:00",
                    "end_date": "2026-12-09T06:00:00+00:00",
                },
                {
                    "term_id": "1272",
                    "section_type": "LEC",
                    "section_number": "004",
                    "instruction_mode": "Something Else",
                    "start_date": "2026-09-02T05:00:00+00:00",
                    "end_date": "2026-12-09T06:00:00+00:00",
                },
            ],
        }
        db.execute("INSERT INTO courses VALUES(?,?)", ("c", json.dumps(course)))
        meetings = [
            self.meeting("2026-09-22T16:00:00+00:00", "2026-09-22T16:50:00+00:00"),
            self.meeting("2026-09-29T16:00:00+00:00", "2026-09-29T16:50:00+00:00"),
            self.meeting(
                "2026-12-12T17:00:00+00:00",
                "2026-12-12T19:00:00+00:00",
                meeting_type="EXAM",
                name="LEC 003 #99",
            ),
            self.meeting(
                "2026-12-20T16:00:00+00:00",
                "2026-12-20T16:50:00+00:00",
                name="LEC 003 #40",
            ),
        ]
        build_discovery(db, [], meetings)
        self.assertEqual(
            db.execute("SELECT mode FROM section_modes ORDER BY section_number").fetchall(),
            [("in_person",), ("other",)],
        )
        rows = db.execute(
            "SELECT term,section_type,section_number,weekday,start_minute FROM class_meetings"
        ).fetchall()
        self.assertEqual(rows, [("1272", "LEC", "003", 1, 11 * 60)])
        self.assertEqual(
            db.execute("SELECT season FROM course_seasons ORDER BY season").fetchall(),
            [("fall",), ("spring",)],
        )
        self.assertEqual(db.execute("SELECT kind FROM requisite_kinds").fetchone()[0], "none")
        self.assertEqual(
            db.execute("SELECT family,value FROM course_designations ORDER BY family").fetchall(),
            [
                ("breadth", "natural-science"),
                ("catalog-level", "intermediate"),
                ("quantitative-reasoning", "b"),
            ],
        )

    def meeting(self, start, end, meeting_type="CLASS", name="LEC 003 #10"):
        return {
            "course_uid": "c",
            "meeting_type": meeting_type,
            "name": name,
            "starts_at": start,
            "ends_at": end,
        }
