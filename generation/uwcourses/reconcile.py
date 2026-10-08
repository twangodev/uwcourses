"""Reconcile catalog, grades, instructors, and meetings into a source snapshot."""

import asyncio

from .models import canonical


def plain(value):
    if hasattr(value, "to_dict"):
        return plain(value.to_dict())
    if isinstance(value, dict):
        result = {str(key): plain(v) for key, v in value.items()}
        for key in (
            "subjects",
            "course_references",
            "satisfies",
            "instructors",
            "courses_taught",
        ):
            if isinstance(result.get(key), list):
                result[key] = sorted(result[key], key=canonical)
        return result
    if isinstance(value, set):
        return sorted((plain(v) for v in value), key=canonical)
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    return value


def reconcile(store, run):
    from uwcourses.course import Course
    from uwcourses.enrollment import apply_enrollment
    from uwcourses.enrollment_data import EnrollmentData, MadgradesData, TermData
    from uwcourses.instructors import FullInstructor, RMPData, merge_instructors
    from uwcourses.name_matcher import (
        find_best_name_match,
        find_best_structured_match,
    )
    from uwcourses.sanitization import sanitize_instructor_id
    from uwcourses.learning_outcomes import course_outcome_map

    EnrollmentData.MeetingLocation._all_locations.clear()
    courses = {
        Course.Reference.from_json(data["course_reference"]): Course.from_json(data)
        for data in store.records(run, "courses").values()
    }
    outcome_map = course_outcome_map(store, run)
    for ref, course in courses.items():
        course.official_learning_outcomes = outcome_map[ref.get_identifier()]
    aliases = {}
    for ref in courses:
        for subject in ref.subjects:
            key = (subject, ref.course_number)
            if key in aliases and aliases[key] != ref:
                raise ValueError(f"Ambiguous course alias: {key}")
            aliases[key] = ref

    def candidates_for(data):
        return {
            aliases[(s, data["course_number"])]
            for s in data["subjects"]
            if (s, data["course_number"]) in aliases
        }

    def resolve(data):
        candidates = candidates_for(data)
        if len(candidates) > 1:
            raise ValueError(f"Ambiguous source course: {data}")
        return next(iter(candidates), None)

    terms = {code: data["name"] for code, data in store.records(run, "terms").items()}
    unmatched = {"grades": [], "offerings": [], "ambiguous_grades": {}}
    for key, data in store.records(run, "grades").items():
        candidates = candidates_for(data["course_reference"])
        if len(candidates) > 1:
            # Historical cross-listings can map to several distinct current
            # courses. Preserve raw grades without choosing an arbitrary owner.
            unmatched["grades"].append(key)
            unmatched["ambiguous_grades"][key] = sorted(str(ref) for ref in candidates)
            continue
        ref = next(iter(candidates), None)
        if ref is None:
            unmatched["grades"].append(key)
            continue
        grades = MadgradesData.from_response(data)
        courses[ref].cumulative_grade_data = grades.cumulative
        for term, grade in grades.by_term.items():
            if term not in terms:
                raise ValueError(f"Grade references unknown term: {term}")
            courses[ref].term_data[term] = TermData(None, grade)

    emails, meetings = {}, {}
    for key, data in store.records(run, "offerings").items():
        ref = resolve(data["course_reference"])
        if ref is None:
            unmatched["offerings"].append(key)
            continue
        original_ref = Course.Reference.from_json(data["course_reference"])
        # Preserve the existing parser, including its DST and room-capacity logic.
        result = apply_enrollment(
            data["hit"],
            data["sections"],
            data["term"],
            {int(k): v for k, v in terms.items()},
            {original_ref: courses[ref]},
        )
        if result is None:
            unmatched["offerings"].append(key)
            continue
        names, occurrences, _ = result
        emails.update(names)
        for meeting in occurrences:
            meeting.course_reference = ref
        meetings.setdefault(ref, set()).update(occurrences)
        courses[ref].has_meetings = bool(meetings[ref])

    additional = {
        name
        for course in courses.values()
        for term in course.term_data.values()
        if term.grade_data
        for name in (term.grade_data.instructors or [])
        if name
    }
    asyncio.run(
        merge_instructors(
            additional, emails, courses, str(store.root / "runs" / run / "name-cache")
        )
    )
    faculty = store.records(run, "faculty")
    ratings = store.records(run, "ratings")
    instructors = {}
    for name, email in sorted(emails.items()):
        official = find_best_name_match(
            query_name=name,
            candidates=list(faculty),
            threshold=80,
            require_exact_last=True,
        )
        details = faculty.get(official.matched_item, {}) if official.is_match else {}
        rating_record = ratings.get(name, {})
        candidates = rating_record.get("candidates", [])
        if "matched_teacher_id" in rating_record:
            candidates = [
                c for c in candidates if c["id"] == rating_record["matched_teacher_id"]
            ]
        match = find_best_structured_match(
            query_name=name,
            candidates=candidates,
            first_name_key="firstName",
            last_name_key="lastName",
            threshold=80,
            require_exact_last=True,
        )
        rating = RMPData.from_rmp_data(match.matched_item) if match.is_match else None
        identifier = sanitize_instructor_id(name)
        if not identifier:
            raise ValueError(f"Invalid instructor identifier: {name}")
        inst = FullInstructor(
            name,
            email,
            rating,
            details.get("position"),
            details.get("department"),
            details.get("credentials"),
            details.get("name")
            or (official.matched_item if official.is_match else None),
        )
        if identifier not in instructors or (
            rating and not instructors[identifier].rmp_data
        ):
            instructors[identifier] = inst
    return courses, instructors, meetings, terms, unmatched


def encode_state(courses, instructors, meetings, terms, unmatched):
    return plain(
        {
            "courses": courses,
            "instructors": instructors,
            "meetings": meetings,
            "terms": terms,
            "unmatched": unmatched,
        }
    )
