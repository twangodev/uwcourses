"""Compact, disposable search read models derived from canonical serving records."""

from collections import defaultdict
import json
import math
from pathlib import Path
from statistics import median

POLICY_PATH = Path(__file__).resolve().parents[2] / "src/lib/search-policy.json"
POLICY = json.loads(POLICY_PATH.read_text())
VERSION = 1
TABLES = (
    "lecture_sizes",
    "grade_metrics",
    "grade_benchmarks",
    "grade_windows",
    "instructor_search_ratings",
    "course_previews",
)


def lecture_sections(course):
    """The last positive observation wins, matching the badge's section identity."""
    sections = {}
    for row in course.get("sections") or []:
        enrolled = row.get("enrolled")
        if (
            row.get("section_type") != "LEC"
            or isinstance(enrolled, bool)
            or not isinstance(enrolled, (int, float))
            or not math.isfinite(enrolled)
            or enrolled <= 0
            or not row.get("term_id")
        ):
            continue
        identity = (
            row.get("section_uid")
            or f"{row['term_id']}:LEC:{row.get('section_number', '')}"
        )
        # Identities are term scoped, as badge selection precedes deduplication.
        sections[(row["term_id"], identity)] = {
            key: row.get(key)
            for key in (
                "term_id",
                "section_uid",
                "section_type",
                "section_number",
                "enrolled",
            )
        }
    return list(sections.values())


def build_search_projection(db):
    db.executescript("""
    CREATE TABLE lecture_sizes(uid TEXT NOT NULL,term TEXT NOT NULL,median REAL NOT NULL,sections INTEGER NOT NULL,PRIMARY KEY(uid,term));
    CREATE INDEX lecture_sizes_lookup ON lecture_sizes(term,median,uid);
    CREATE TABLE grade_metrics(uid TEXT NOT NULL,term TEXT NOT NULL,grade_count INTEGER NOT NULL,gpa REAL NOT NULL,PRIMARY KEY(uid,term));
    CREATE INDEX grade_metrics_term ON grade_metrics(term,grade_count,uid);
    CREATE TABLE grade_benchmarks(term TEXT NOT NULL,subject TEXT NOT NULL,gpa REAL NOT NULL,size INTEGER NOT NULL,PRIMARY KEY(term,subject));
    CREATE TABLE grade_windows(term TEXT NOT NULL,uid TEXT NOT NULL,a INTEGER NOT NULL,ab INTEGER NOT NULL,b INTEGER NOT NULL,bc INTEGER NOT NULL,c INTEGER NOT NULL,d INTEGER NOT NULL,f INTEGER NOT NULL,grade_count INTEGER NOT NULL,history_gpa REAL,first_term TEXT,last_term TEXT,PRIMARY KEY(term,uid));
    CREATE INDEX grade_windows_gpa ON grade_windows(term,history_gpa,uid);
    CREATE TABLE instructor_search_ratings(uid TEXT PRIMARY KEY,quality REAL,quality_count INTEGER NOT NULL,bayesian_quality REAL);
    CREATE INDEX instructor_search_ratings_quality ON instructor_search_ratings(bayesian_quality,quality_count,uid);
    CREATE TABLE course_previews(uid TEXT PRIMARY KEY,payload TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS teaching_term ON teaching(term,course_uid,instructor_uid);
    CREATE INDEX IF NOT EXISTS grade_summaries_term ON grade_summaries(term,uid);
    """)
    terms = {
        r[0]
        for r in db.execute(
            "SELECT term FROM grades UNION SELECT term FROM teaching UNION SELECT term FROM offerings"
        )
    }
    for uid, raw in db.execute("SELECT uid,payload FROM courses"):
        course = json.loads(raw)
        if course.get("semester"):
            terms.add(course["semester"])
        sections = lecture_sections(course)
        grouped = defaultdict(list)
        for section in sections:
            grouped[section["term_id"]].append(section["enrolled"])
        db.executemany(
            "INSERT INTO lecture_sizes VALUES(?,?,?,?)",
            [(uid, term, median(sizes), len(sizes)) for term, sizes in grouped.items()],
        )
        preview = {
            key: course.get(key)
            for key in ("course_uid", "course_id", "semester", "llm_summary")
        }
        summary = course.get("student_summary") or {}
        claim = next(
            (
                row
                for row in [
                    *(summary.get("difficulty_workload") or []),
                    *(summary.get("quick_take") or []),
                ]
                if any(c.get("type") == "review" for c in row.get("citations") or [])
            ),
            None,
        )
        instructors = []
        seen_instructors = set()
        for row in summary.get("current_instructors") or []:
            instructor_uid = row.get("instructor_uid")
            if not instructor_uid or instructor_uid in seen_instructors:
                continue
            seen_instructors.add(instructor_uid)
            cited = next(
                (claim for claim in row.get("summary") or [] if claim.get("citations")),
                None,
            )
            instructors.append(
                {"instructor_uid": instructor_uid, "summary": [cited] if cited else []}
            )
        preview["student_summary"] = {
            "difficulty_workload": [claim] if claim else [],
            "current_instructors": instructors,
        }
        preview["sections"] = sections
        preview["offerings"] = [
            {"term_id": row["term_id"]} for row in course.get("offerings") or []
        ]
        preview["evidence"] = {
            "reviews": (course.get("evidence") or {}).get("reviews") or []
        }
        db.execute(
            "INSERT INTO course_previews VALUES(?,?)",
            (
                uid,
                json.dumps(
                    preview, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                ),
            ),
        )
    count = "a+ab+b+bc+c+d+f"
    db.execute(f"""INSERT INTO grade_metrics
        SELECT uid,term,{count},(a*4+ab*3.5+b*3+bc*2.5+c*2+d)*1.0/({count})
        FROM grade_summaries WHERE ({count})>0""")
    thresholds = POLICY["tagThresholds"]
    db.execute(
        """INSERT INTO grade_benchmarks
        SELECT term,subject,AVG(gpa),COUNT(*) FROM (
            SELECT g.*,s.subject FROM grade_metrics g JOIN subjects s ON s.uid=g.uid
            UNION ALL SELECT g.*,'school' subject FROM grade_metrics g
        ) WHERE grade_count>=? GROUP BY term,subject HAVING COUNT(*)>=?""",
        (thresholds["letterGrades"], thresholds["benchmarkCourses"]),
    )
    # Only published view terms are materialized; arbitrary valid terms use indexed SQL.
    for term in sorted(terms):
        db.execute(
            f"""INSERT INTO grade_windows
            SELECT ?,uid,SUM(a),SUM(ab),SUM(b),SUM(bc),SUM(c),SUM(d),SUM(f),SUM({count}),
            SUM(a*4+ab*3.5+b*3+bc*2.5+c*2+d)*1.0/NULLIF(SUM({count}),0),
            MIN(CASE WHEN ({count})>0 THEN term END),MAX(CASE WHEN ({count})>0 THEN term END)
            FROM grade_summaries WHERE term<=? AND term>? GROUP BY uid""",
            (term, term, f"{int(term) - 50:04d}"),
        )
    prior = db.execute(
        "SELECT AVG(json_extract(payload,'$.quality_rating')) FROM reviews WHERE json_extract(payload,'$.quality_rating') BETWEEN 1 AND 5"
    ).fetchone()[0]
    for uid, raw in db.execute("SELECT uid,payload FROM instructors"):
        ratings = json.loads(raw).get("ratings") or {}
        quality = ratings.get("quality")
        count = ratings.get("quality_count") or 0
        valid = (
            isinstance(quality, (int, float))
            and not isinstance(quality, bool)
            and math.isfinite(quality)
            and 1 <= quality <= 5
            and isinstance(count, (int, float))
            and math.isfinite(count)
            and count > 0
        )
        adjusted = (
            (
                (quality * count + prior * POLICY["ratingPriorWeight"])
                / (count + POLICY["ratingPriorWeight"])
            )
            if valid and prior is not None
            else None
        )
        db.execute(
            "INSERT INTO instructor_search_ratings VALUES(?,?,?,?)",
            (uid, quality, count, adjusted),
        )
    return {"version": VERSION, "terms": sorted(terms, reverse=True)}
