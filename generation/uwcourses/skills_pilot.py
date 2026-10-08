"""Build a reproducible local source-coverage pilot and unreviewed annotation queue.

Usage: python -m uwcourses.skills_pilot --guide comp_sci=/tmp/comp_sci.html
       --guide stat=/tmp/stat.html --output .coursemap/skills-pilot
This command does not run inference, assign gold labels, or publish data.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re

from bs4 import BeautifulSoup

from .classification import LABELS, TAXONOMY_VERSION
from .course import Course
from .learning_outcomes import merge_outcomes
from .models import canonical
from .reconcile import plain


def partition(identity):
    bucket = int(hashlib.sha256(identity.encode()).hexdigest()[:8], 16) % 10
    return "train" if bucket < 6 else "calibration" if bucket < 8 else "eval"


def read_guide(subject, path):
    if not re.fullmatch(r"[a-z_]+", subject):
        raise ValueError("Guide subject must be a lowercase URL slug")
    body = Path(path).read_bytes()
    soup = BeautifulSoup(body, "html.parser")
    blocks = soup.select("div.courseblock")
    if not blocks:
        raise ValueError(f"No course blocks in {path}; refuse an error-page pilot")
    tagline = soup.select_one(".site-tagline")
    year = tagline.get_text(strip=True) if tagline else None
    year = year if year and re.fullmatch(r"\d{4}-\d{4}", year) else None
    url = f"https://guide.wisc.edu/courses/{subject}/"
    courses = []
    for block in blocks:
        course = Course.from_block(
            block, logging.getLogger(__name__), source_url=url, catalog_year=year
        )
        if course is None:
            raise ValueError(f"Unparseable course block in {path}")
        value = plain(course)
        value["course_id"] = course.get_identifier()
        value["source_url"] = url
        courses.append(value)
    return courses, {
        "subject": subject,
        "source_url": url,
        "catalog_year": year,
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
        "courses": len(courses),
        "courses_with_outcomes": sum(
            bool(c["official_learning_outcomes"]) for c in courses
        ),
        "outcomes": sum(len(c["official_learning_outcomes"]) for c in courses),
        "original_fetch_time": None,
    }


def select_sample(courses, count, excluded=()):
    candidates = [
        c
        for c in courses
        if c["course_id"] not in excluded
        and c["course_reference"]["course_number"] < 700
    ]
    ordered = sorted(
        candidates, key=lambda c: hashlib.sha256(c["course_id"].encode()).hexdigest()
    )
    selected = []
    for predicate in (
        lambda c: not c["official_learning_outcomes"],
        lambda c: len(c["course_reference"]["subjects"]) > 1,
    ):
        match = next((c for c in ordered if predicate(c) and c not in selected), None)
        if match is not None and len(selected) < count:
            selected.append(match)
    selected.extend(c for c in ordered if c not in selected)
    return selected[:count]


def annotations(courses):
    """Unreviewed is distinct from a human-reviewed unknown classification."""
    rows = []
    for course in courses:
        identity = course["course_id"]
        ref = course["course_reference"]
        aliases = [f"{subject} {ref['course_number']}" for subject in ref["subjects"]]
        sources = course["official_learning_outcomes"]
        if sources:
            source = next((s for s in sources if len(s["text"]) <= 1800), None)
            if source is None:
                continue  # Never silently truncate an official statement.
            passage, url = source["text"], source["source_url"]
        else:
            passage, url = course["description"], course["source_url"]
        if not passage.strip() or len(passage) > 1800:
            continue
        source_id = hashlib.sha256(canonical([url, passage]).encode()).hexdigest()
        for label in LABELS:
            rows.append(
                {
                    "course_id": identity,
                    "course_identity": identity,
                    "aliases": aliases,
                    "passage": passage,
                    "quote": passage,
                    "source_url": url,
                    "source_id": source_id,
                    "label": label,
                    "gold": None,
                    "reviewed": False,
                    "split": partition(identity),
                    "taxonomy_version": TAXONOMY_VERSION,
                }
            )
    return rows


def build(guides, output, courses_per_subject=8, annotation_courses=100):
    output = Path(output)
    # Refuse accidental replacement of an existing review dataset.
    output.mkdir(parents=True, exist_ok=False)
    (output / "sources").mkdir()
    groups, sources, all_courses = {}, [], {}
    for subject, path in guides:
        courses, source = read_guide(subject, path)
        (output / "sources" / f"{subject}.html").write_bytes(Path(path).read_bytes())
        sources.append(source)
        groups[subject] = courses
        for course in courses:
            previous = all_courses.get(course["course_id"])
            if previous:
                previous["official_learning_outcomes"] = merge_outcomes(
                    previous["official_learning_outcomes"],
                    course["official_learning_outcomes"],
                )
            else:
                all_courses[course["course_id"]] = course
    selected, used = [], set()
    for courses in groups.values():
        for course in select_sample(courses, courses_per_subject, used):
            selected.append(all_courses[course["course_id"]])
            used.add(course["course_id"])
    annotation_sample = select_sample(list(all_courses.values()), annotation_courses)
    review_rows = annotations(annotation_sample)
    for name, rows in (
        ("courses.jsonl", selected),
        ("annotations.pending.jsonl", review_rows),
    ):
        (output / name).write_text("".join(canonical(row) + "\n" for row in rows))
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
        "unique_courses": len(all_courses),
        "pilot_courses": len(selected),
        "pilot_courses_with_outcomes": sum(
            bool(c["official_learning_outcomes"]) for c in selected
        ),
        "pilot_crosslisted_courses": sum(
            len(c["course_reference"]["subjects"]) > 1 for c in selected
        ),
        "selection": "Eight per subject by stable identity hash, preferring missing outcomes and cross-listings; course numbers below 700. This is not a degree eligibility determination.",
        "pending_annotation_decisions": len(review_rows),
        "annotation_splits": dict(Counter(r["split"] for r in review_rows)),
        "manually_reviewed_decisions": 0,
        "qwen_inference_run": False,
        "laya_inference_run": False,
        "automatic_classification_enabled": False,
        "enrollment_api_outcomes_verified": False,
        "limitations": [
            "Source-only pilot; pending annotations are not gold labels.",
            "Add reviewed unknown, unrelated and option-order cases before classifier acceptance.",
            "Original Guide fetch times are unknown; no observation date was invented.",
        ],
    }
    (output / "coverage.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--guide", action="append", required=True, metavar="SUBJECT=HTML"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--courses-per-subject", type=int, default=8)
    parser.add_argument("--annotation-courses", type=int, default=100)
    args = parser.parse_args()
    if args.courses_per_subject < 1 or args.annotation_courses < 1:
        parser.error("Sample sizes must be positive")
    guides = []
    for spec in args.guide:
        if "=" not in spec:
            parser.error("Each --guide must be SUBJECT=HTML")
        subject, path = spec.split("=", 1)
        if subject in {s for s, _ in guides}:
            parser.error("Repeated Guide subject")
        guides.append((subject, path))
    print(
        json.dumps(
            build(
                guides, args.output, args.courses_per_subject, args.annotation_courses
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
