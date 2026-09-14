"""Generate a reviewable article snapshot from the local, pinned course import.

Usage: python3 web/blog/evidence.py <article-selection.json>
The output is checked in; normal builds never silently rewrite an article's data.
"""

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GRADES = ("a", "ab", "b", "bc", "c", "d", "f")
WEIGHTS = (4, 3.5, 3, 2.5, 2, 1, 0)


def summarize(rows):
    counts = {grade: sum(row[grade] for row in rows) for grade in GRADES}
    count = sum(counts.values())
    points = sum(counts[grade] * weight for grade, weight in zip(GRADES, WEIGHTS))
    return {
        "counts": counts,
        "n": count,
        "gpa": points / count if count else None,
        "a_percent": 100 * counts["a"] / count if count else None,
    }


def generate(selection, db, status):
    start, end = selection["start_term"], selection["end_term"]
    if start > end or end >= selection["target_term"]:
        raise ValueError("Grade window must precede the target term")
    candidates = db.execute("""
        SELECT c.uid FROM courses c
        JOIN course_numbers cn ON cn.uid=c.uid
        JOIN grade_summaries g ON g.uid=c.uid
        WHERE cn.number BETWEEN 100 AND 299 AND c.credits_max BETWEEN 2 AND 4
          AND g.term BETWEEN ? AND ?
          AND EXISTS (SELECT 1 FROM grade_summaries latest
                      WHERE latest.uid=c.uid AND latest.term=?
                        AND latest.a+latest.ab+latest.b+latest.bc+latest.c+latest.d+latest.f>0)
        GROUP BY c.uid
        HAVING SUM(g.a+g.ab+g.b+g.bc+g.c+g.d+g.f)>=300
          AND SUM(CASE WHEN g.a+g.ab+g.b+g.bc+g.c+g.d+g.f>0 THEN 1 ELSE 0 END)>=4
    """, (start, end, end)).fetchall()
    eligible = {row["uid"] for row in candidates}
    courses = []
    for item in selection["courses"]:
        row = db.execute("SELECT uid,payload FROM courses WHERE code=?", (item["code"],)).fetchone()
        if not row or row["uid"] not in eligible:
            raise ValueError(f"Selected course does not meet evidence threshold: {item['code']}")
        course = json.loads(row["payload"])
        terms = [dict(row) for row in db.execute(
            "SELECT term,a,ab,b,bc,c,d,f FROM grade_summaries WHERE uid=? AND term BETWEEN ? AND ? ORDER BY term",
            (row["uid"], start, end),
        )]
        reviews = [json.loads(review["payload"]) for review in db.execute(
            "SELECT payload FROM reviews WHERE course_uid=? ORDER BY review_date,profile_id,review_id",
            (row["uid"],),
        )]
        recent = [review for review in reviews if
                  selection["review_start"] <= str(review.get("review_date") or "")[:10] <= status["observed_at"][:10]]
        courses.append({
            **item,
            "uid": row["uid"],
            "title": course["title"],
            "credits_min": course["credits_min"],
            "credits_max": course["credits_max"],
            "requirements": course["requirements_text"],
            "guide_url": f"https://guide.wisc.edu/courses/{item['guide']}/",
            "reviews": {
                "captured_total": len(reviews),
                "in_window_count": len(recent),
                "records": [{
                    "id": review["source_review_id"],
                    "profile": review["source_instructor_id"],
                    "date": str(review["review_date"]),
                    "instructor": review["instructor_name"],
                    "source_url": review["source_url"],
                    "comment_sha256": hashlib.sha256(str(review.get("comment") or "").encode()).hexdigest(),
                } for review in recent],
            },
            "target_offering_recorded": db.execute(
                "SELECT 1 FROM offerings WHERE uid=? AND term=?",
                (row["uid"], selection["target_term"]),
            ).fetchone() is not None,
            "pooled": summarize(terms),
            "terms": [{"term": row["term"], **summarize([row])} for row in terms],
        })
    if len({course["uid"] for course in courses}) != len(courses):
        raise ValueError("Cross-listed course selected more than once")
    return {
        "source": {key: status[key] for key in ("repository", "revision", "projection_id", "observed_at")},
        "selection_sha256": hashlib.sha256(json.dumps(selection, sort_keys=True).encode()).hexdigest(),
        "catalog_checked": selection["catalog_checked"],
        "review_window": {"start": selection["review_start"], "end": status["observed_at"][:10]},
        "target_term": selection["target_term"],
        "window": {"start": start, "end": end},
        "eligible_courses": len(eligible),
        "courses": courses,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("selection", type=Path)
    args = parser.parse_args()
    selection = json.loads(args.selection.read_text())
    status = json.loads((ROOT / ".site/import/status.json").read_text())
    with sqlite3.connect(f"file:{ROOT}/.site/import/site.sqlite?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        evidence = generate(selection, db, status)
    target = ROOT / "static/blog" / f"{selection['slug']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {len(evidence['courses'])} selections from {evidence['eligible_courses']} eligible courses: {target}")


if __name__ == "__main__":
    main()
