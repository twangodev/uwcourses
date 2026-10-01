import json
import sqlite3
import unittest
from uwcourses_site.search_projection import build_search_projection, lecture_sections


def fixture():
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE courses(uid TEXT PRIMARY KEY,payload TEXT);
        CREATE TABLE subjects(subject TEXT,uid TEXT,PRIMARY KEY(subject,uid));
        CREATE TABLE grades(uid TEXT,term TEXT);
        CREATE TABLE teaching(term TEXT,course_uid TEXT,instructor_uid TEXT);
        CREATE TABLE offerings(term TEXT,uid TEXT);
        CREATE TABLE reviews(payload TEXT);
        CREATE TABLE instructors(uid TEXT PRIMARY KEY,payload TEXT);
        CREATE TABLE grade_summaries(uid TEXT,term TEXT,a INTEGER,ab INTEGER,b INTEGER,bc INTEGER,c INTEGER,d INTEGER,f INTEGER,PRIMARY KEY(uid,term));
    """)
    for i in range(12):
        uid = str(i)
        course = {"course_uid": uid, "course_id": f"TEST {i}", "semester": "1272",
                  "sections": [{"section_uid": uid, "term_id": "1272", "section_type": "LEC", "enrolled": 20 + i}],
                  "student_summary": {"quick_take": [{"text": "Original claim", "citations": [{"type": "review", "source_review_id": "review"}]}]},
                  "evidence": {"reviews": ["/data/review.json"], "traces": ["/data/large.json"]},
                  "offerings": [{"term_id": "1272", "extra": "discard"}], "unneeded": "x" * 10000}
        db.execute("INSERT INTO courses VALUES(?,?)", (uid, json.dumps(course)))
        db.execute("INSERT INTO subjects VALUES('TEST',?)", (uid,))
        db.execute("INSERT INTO grades VALUES(?,'1264')", (uid,))
        db.execute("INSERT INTO grade_summaries VALUES(?,'1264',?,?,?,?,?,?,?)", (uid, 40 if i else 0, 0, 0, 0, 40 if not i else 0, 0, 0))
    db.execute("INSERT INTO grade_summaries VALUES('0','1272',1,0,0,0,0,0,0)")
    db.execute("INSERT INTO grade_summaries VALUES('0','1222',100,0,0,0,0,0,0)")
    db.execute("INSERT INTO reviews VALUES(?)", (json.dumps({"quality_rating": 3.5}),))
    db.execute("INSERT INTO instructors VALUES('teacher',?)", (json.dumps({"ratings": {"quality": 5, "quality_count": 20}}),))
    db.execute("INSERT INTO teaching VALUES('1272','0','teacher')")
    return db


class SearchProjectionTests(unittest.TestCase):
    def test_grade_windows_cohorts_ratings_and_compact_evidence(self):
        db = fixture()
        metadata = build_search_projection(db)
        self.assertEqual(metadata["version"], 1)
        self.assertIn("1272", metadata["terms"])
        # The five-year lower boundary is excluded, including its grades.
        self.assertEqual(db.execute("SELECT a,c,grade_count,first_term,last_term FROM grade_windows WHERE uid='0' AND term='1272'").fetchone(), (1, 40, 41, "1264", "1272"))
        self.assertEqual(db.execute("SELECT gpa,size FROM grade_benchmarks WHERE term='1264' AND subject='TEST'").fetchone(), (46 / 12, 12))
        self.assertIsNone(db.execute("SELECT * FROM grade_benchmarks WHERE term='1272'").fetchone())
        self.assertEqual(db.execute("SELECT bayesian_quality FROM instructor_search_ratings").fetchone()[0], 4.25)
        preview = json.loads(db.execute("SELECT payload FROM course_previews WHERE uid='0'").fetchone()[0])
        self.assertNotIn("unneeded", preview)
        self.assertEqual(preview["evidence"], {"reviews": ["/data/review.json"]})
        self.assertEqual(preview["student_summary"]["difficulty_workload"][0]["citations"][0]["source_review_id"], "review")
        self.assertEqual(preview["offerings"], [{"term_id": "1272"}])
        self.assertEqual(db.execute("SELECT median,sections FROM lecture_sizes WHERE uid='0'").fetchone(), (20, 1))
        db.close()

    def test_lecture_identity_keeps_last_positive_observation_per_term(self):
        base = {"section_uid": "shared", "term_id": "1272", "section_type": "LEC"}
        rows = [dict(base, enrolled=100), dict(base, enrolled=20), dict(base, enrolled=0),
                dict(base, term_id="1264", enrolled=70), dict(base, section_type="DIS", enrolled=500),
                dict(base, enrolled=True), dict(base, enrolled=float("nan"))]
        self.assertEqual([r["enrolled"] for r in lecture_sections({"sections": rows})], [20, 70])
        db = fixture()
        db.execute("UPDATE courses SET payload=? WHERE uid='0'", (json.dumps({"semester": "1272", "sections": rows[:5]}),))
        build_search_projection(db)
        self.assertEqual(db.execute("SELECT term,median,sections FROM lecture_sizes WHERE uid='0' ORDER BY term").fetchall(), [("1264", 70, 1), ("1272", 20, 1)])
        db.close()

    def test_missing_prior_does_not_invent_an_adjusted_rating(self):
        db = fixture()
        db.execute("DELETE FROM reviews")
        build_search_projection(db)
        self.assertIsNone(db.execute("SELECT bayesian_quality FROM instructor_search_ratings").fetchone()[0])
        db.close()
