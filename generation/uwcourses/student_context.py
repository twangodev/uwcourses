"""Frozen enrollment, review, and grade evidence for student-facing summaries."""

from collections import defaultdict
from functools import lru_cache
import json
import re

from uwcourses.name_matcher import (
    find_best_name_match,
    HumanName,
    normalize_name_component,
)
from .course_context import sample_reviews
from .dataset_shape import instructor_identity
from sqlalchemy import select
from .schema import observations

from .models import digest

POINTS = {"a": 4, "ab": 3.5, "b": 3, "bc": 2.5, "c": 2, "d": 1, "f": 0}


def review_course_correction(review, resolve):
    """Recognize an explicit opening correction, without guessing a reassignment."""
    match = re.match(
        r"^\s*(?:actually|this (?:review|rating) is for)\s*[:,\-]?\s*"
        r"([a-z&/ -]+?)\s*(\d{3})\b",
        review["comment"],
        re.I,
    )
    return resolve(f"{match[1].strip().upper()} {match[2]}") if match else None


def person_name(person):
    name = person.get("name") or ""
    return (
        " ".join(str(name.get(k) or "").strip() for k in ("first", "last")).strip()
        if isinstance(name, dict)
        else name
    )


@lru_cache(maxsize=50000)
def last_name(name):
    return normalize_name_component(HumanName(name).last)


@lru_cache(maxsize=20000)
def match_name(name, candidates):
    """A unique conservative match; never break a tie by input ordering."""
    if name in candidates:
        return name
    scores = []
    for candidate in candidates:
        if last_name(candidate) != last_name(name):
            continue
        result = find_best_name_match(
            name, [candidate], threshold=80, require_exact_last=True
        )
        if result.is_match:
            scores.append((result.confidence, candidate))
    if not scores:
        return None
    best = max(score for score, _ in scores)
    winners = {candidate for score, candidate in scores if score == best}
    return next(iter(winners)) if len(winners) == 1 else None


def grade_sentence(records):
    """Compute temporary statistics; export only narrative and raw-row citations."""
    terms = defaultdict(list)
    seen = set()
    for record in records:
        identity = json.dumps(
            {
                k: v
                for k, v in record["citation"].items()
                if k not in {"source_record", "alternative_source_records"}
            },
            sort_keys=True,
        )
        if identity in seen:
            continue
        seen.add(identity)
        if all(
            isinstance(record["counts"].get(k), int) and record["counts"][k] >= 0
            for k in POINTS
        ):
            if sum(record["counts"][k] for k in POINTS):
                terms[record["term_id"]].append(record)
    selected = sorted(terms)[-3:]
    if not selected:
        return None
    descriptions, citations = [], []
    for term in selected:
        counts = {k: sum(r["counts"][k] for r in terms[term]) for k in POINTS}
        n = sum(counts.values())
        gpa = sum(POINTS[k] * counts[k] for k in POINTS) / n
        share = (counts["a"] + counts["ab"]) / n * 100
        label = terms[term][0]["term_name"] or term
        descriptions.append(
            f"{label}: {gpa:.2f} GPA, {share:.1f}% A/AB (n={n} letter grades)"
        )
        citations.extend(r["citation"] for r in terms[term])
    joint = any(r.get("joint") for term in selected for r in terms[term])
    conflicts = [
        terms[term][0]["term_name"] or term
        for term in selected
        if any(r["citation"].get("alternative_source_records") for r in terms[term])
    ]
    return {
        "text": "Recent recorded grades — "
        + "; ".join(descriptions)
        + (". Includes jointly taught sections." if joint else ".")
        + (
            " Cross-listed source records differ for "
            + ", ".join(conflicts)
            + "; figures use the selected dataset record."
            if conflicts
            else ""
        ),
        "citations": citations,
    }


def select_course_grades(records):
    """Match reconciliation's last-record selection, retaining conflicting sources."""
    selected = {}
    for record in records:
        previous = selected.get(record["term_id"])
        if previous and (
            previous["counts"] != record["counts"]
            or previous["citation"].get("alternative_source_records")
        ):
            alternatives = previous["citation"].get(
                "alternative_source_records", []
            ) + [previous["citation"]["source_record"]]
            record["citation"]["alternative_source_records"] = [
                r for r in alternatives if r != record["citation"]["source_record"]
            ]
        selected[record["term_id"]] = record
    return list(selected.values())


def teaching_history(professors):
    """Recorded teaching terms, with raw section citations and no inferred schedule."""
    history = []
    for name, records in sorted(professors.items()):
        terms = {}
        for record in records:
            term = terms.setdefault(
                record["term_id"],
                {
                    "term_id": record["term_id"],
                    "term_name": record["term_name"],
                    "citations": [],
                },
            )
            if record["citation"] not in term["citations"]:
                term["citations"].append(record["citation"])
        history.append({"name": name, "terms": [terms[t] for t in sorted(terms)]})
    return history


class StudentContext:
    def __init__(self, store, run, courses):
        self.run, self.base = run, courses
        self.term = str(store.run(run)["semester"])
        self.rosters, self.course_grades, self.professor_grades = (
            {},
            defaultdict(list),
            defaultdict(lambda: defaultdict(list)),
        )
        self.ratings = {}
        for row in store.db.execute(
            select(observations.c.entity_id, observations.c.payload_json).where(
                observations.c.run_id == run, observations.c.kind == "ratings"
            ),
        ):
            record = json.loads(row["payload_json"])
            teacher = next(
                (
                    c
                    for c in record.get("candidates", [])
                    if c["id"] == record.get("matched_teacher_id")
                ),
                None,
            )
            self.ratings[row["entity_id"]] = (
                f"rmp:{teacher['legacyId']}" if teacher else None
            )
        self.rating_names = tuple(sorted(self.ratings))
        terms = store.records(run, "terms")
        self.term_name = terms.get(self.term, {}).get("name") or self.term
        for offering_id, value in store.records(run, "offerings").items():
            key = self.resolve(value["course_reference"])
            if not key or str(value["term"]) != self.term:
                continue
            roster = self.rosters.setdefault(key, {})
            for package in value.get("sections", []):
                for section in package.get("sections", [package]):
                    if section.get("active") is False:
                        continue
                    section_id = (section.get("classUniqueId") or {}).get(
                        "classNumber"
                    ) or section.get("id")
                    section_uid = (
                        f"uw-section:{self.term}:{section_id}"
                        if section_id is not None
                        else "uw-section_"
                        + digest(
                            [
                                self.term,
                                offering_id,
                                f"{section.get('type')}:{section.get('sectionNumber')}",
                            ]
                        )[:24]
                    )
                    for person in section.get("instructors", []):
                        name = person_name(person)
                        if not name:
                            continue
                        identity = instructor_identity(
                            "enrollment",
                            {**person, "name": name},
                            [section_uid, name],
                        )
                        entry = roster.setdefault(
                            identity["instructor_uid"],
                            {
                                "instructor_uid": identity["instructor_uid"],
                                "name": name,
                                "section_types": set(),
                            },
                        )
                        entry["section_types"].add(section.get("type"))
        for key, roster in self.rosters.items():
            lecturers = {
                uid: p for uid, p in roster.items() if "LEC" in p["section_types"]
            }
            self.rosters[key] = lecturers or roster
        for entity_id, value in store.records(run, "grades").items():
            key = self.resolve(value["course_reference"])
            if not key:
                continue
            archive = {
                "file": "tables/observations.parquet",
                "source": "madgrades",
                "kind": "grades",
                "entity_id": entity_id,
            }
            for offering in value.get("courseOfferings", []):
                term = str(offering["termCode"])
                common = {"term_id": term, "term_name": terms.get(term, {}).get("name")}
                self.course_grades[key].append(
                    {
                        **common,
                        "counts": self.counts(offering.get("cumulative", {})),
                        "citation": {
                            "type": "grade",
                            "run_id": run,
                            "table": "grades_latest",
                            "course_id": key,
                            "term_id": term,
                            "source_record": archive,
                        },
                    }
                )
                for section in offering.get("sections", []):
                    if section.get("sectionNumber") is None:
                        continue
                    people = section.get("instructors", [])
                    citation = {
                        "type": "grade",
                        "run_id": run,
                        "table": "section_grades_latest",
                        "course_id": key,
                        "term_id": term,
                        "source_course_id": str(
                            value.get("source_id") or value.get("courseUuid")
                        ),
                        "section_number": section.get("sectionNumber"),
                        "source_record": archive,
                    }
                    record = {
                        **common,
                        "counts": self.counts(section),
                        "citation": citation,
                        "joint": len(people) > 1,
                    }
                    for person in people:
                        if person.get("name"):
                            self.professor_grades[key][person["name"]].append(record)
        for key, records in self.course_grades.items():
            self.course_grades[key] = select_course_grades(records)

    @staticmethod
    def counts(value):
        return {k: value.get(k + "Count") for k in POINTS}

    def resolve(self, ref):
        keys = {
            self.base.resolve(f"{s} {ref['course_number']}") for s in ref["subjects"]
        }
        keys.discard(None)
        return next(iter(keys)) if len(keys) == 1 else None

    def get(self, key):
        reviews = self.base.reviews.get(key, [])
        excluded = []
        retained = []
        for review in reviews:
            corrected = review_course_correction(review, self.base.resolve)
            if corrected and corrected != key:
                excluded.append(
                    {
                        "source_review_id": review["source_review_id"],
                        "claimed_course_id": corrected,
                        "reason": "Review explicitly identifies a different course",
                    }
                )
            else:
                retained.append(review)
        reviews = retained
        people, current_rmp = [], set()
        for p in sorted(self.rosters.get(key, {}).values(), key=lambda p: p["name"]):
            matched = match_name(p["name"], self.rating_names)
            rmp = self.ratings.get(matched)
            if rmp:
                current_rmp.add(rmp)
            matching = [r for r in reviews if r["instructor_id"] == rmp]
            grade_name = match_name(
                p["name"], tuple(sorted(self.professor_grades[key]))
            )
            people.append(
                {
                    "instructor_uid": p["instructor_uid"],
                    "name": p["name"],
                    "rmp_instructor_id": rmp,
                    "reviews": sample_reviews(matching, 10),
                    "grade_records": self.professor_grades[key].get(grade_name, []),
                }
            )
        historical = sample_reviews(
            [r for r in reviews if r["instructor_id"] not in current_rmp], 12
        )
        history_names = {
            match_name(name, tuple(sorted(self.professor_grades[key])))
            for name in {
                *(p["name"] for p in people),
                *(r.get("instructor_name") for r in historical),
            }
            if name
        }
        return {
            "course_id": key,
            **({"excluded_reviews": excluded} if excluded else {}),
            "has_description": bool(
                self.base.courses[key].get("description", "").strip()
            ),
            "term_id": self.term,
            "term_name": self.term_name,
            "offered": key in self.rosters,
            "current_instructors": people,
            "historical_reviews": historical,
            "teaching_history": teaching_history(
                {
                    name: self.professor_grades[key][name]
                    for name in history_names
                    if name
                }
            ),
            "grade_records": self.course_grades[key],
        }
