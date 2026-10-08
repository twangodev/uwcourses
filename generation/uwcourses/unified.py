"""Course-specific evidence and requirement validation shared by AI agents."""

import copy
import re

import jsonschema

from .course_context import text_view
from .requirements import (
    ambiguous_semicolons,
    graph_diagnostics,
    restore_quotes,
    validate_graph,
)
from .requirements_eval import expression, normalize


SECTIONS = ("search_profile", "requirements", "student_experience")


def outcome_quote(citation, course):
    """Outcome evidence identifies one source record, never a merged text blob."""
    outcomes = course.get("official_learning_outcomes", []) if course else []
    index = citation.get("outcome_index")
    if (
        not isinstance(index, int)
        or isinstance(index, bool)
        or not 0 <= index < len(outcomes)
    ):
        raise ValueError("Outcome evidence requires an available outcome_index")
    outcome = outcomes[index]
    if citation.get("source_url") != outcome.get("source_url"):
        raise ValueError(
            "Outcome evidence source_url must match the selected official source"
        )
    quote = citation["quote"]
    if not quote.strip() or quote not in outcome["text"]:
        raise ValueError(
            "Outcome evidence requires an exact substring of the selected official outcome"
        )
    return quote


def compare_parsers(section, original):
    def convert(node):
        if isinstance(node, str):
            if text_view(node).lower().rstrip(".") in {
                "",
                "none",
                "no prerequisites",
                "no requisites",
            }:
                return None
            return {"condition": text_view(node)}
        if isinstance(node, dict) and "course_number" in node:
            return {
                "course": {
                    "subjects": node["subjects"],
                    "course_number": node["course_number"],
                    "timing": "prior",
                    "minimum_grade": None,
                }
            }
        if isinstance(node, dict) and node.get("operator") in {"AND", "OR", "NOT"}:
            return {
                {"AND": "all", "OR": "any", "NOT": "not"}[node["operator"]]: [
                    convert(c) for c in node["children"]
                ]
            }
        raise ValueError("Unsupported legacy AST form")

    comparison = {
        "structural_match": None,
        "note": "Both parsers are candidates; structural agreement does not prove semantic correctness.",
    }
    if original.get("ast") is not None and section.get("value") is not None:
        try:
            comparison["structural_match"] = normalize(
                convert(original["ast"])
            ) == normalize(expression(section["value"]))
        except (ValueError, KeyError, TypeError, IndexError):
            comparison["note"] = (
                "Legacy AST could not be compared; preserve both candidates for review."
            )
        if comparison["structural_match"] is False and section["status"] == "valid":
            section["status"] = "needs_review"
    section["parser_comparison"] = comparison


def quote_projection(text):
    chars, positions = [], []
    for i, char in enumerate(text):
        char = {"’": "'", "‘": "'", "“": '"', "”": '"'}.get(char, char)
        if char == '"' or (
            char == "'"
            and not (
                i > 0
                and i + 1 < len(text)
                and text[i - 1].isalnum()
                and text[i + 1].isalnum()
            )
        ):
            continue
        chars.append(char)
        positions.append(i)
    return "".join(chars), positions


def literal_span(quote, source):
    position = source.find(quote)
    if position >= 0:
        return position, position + len(quote)
    projected, positions = quote_projection(source)
    needle, _ = quote_projection(quote)
    position = projected.find(needle) if needle else -1
    if position >= 0:
        return positions[position], positions[position + len(needle) - 1] + 1
    return None


def source_quote(quote, source):
    if text_view(quote).casefold() == text_view(source).casefold():
        return source
    if quote in source:
        return quote
    quote = text_view(quote)
    span = literal_span(quote, source)
    if span is not None:
        return source[span[0] : span[1]]
    parts = [part.strip() for part in re.split(r"\.{3}|…", quote) if part.strip()]
    if len(parts) < 2:
        return None
    start, end = None, 0
    for part in parts:
        span = literal_span(part, source[end:])
        if span is None:
            return None
        if start is None:
            start = end + span[0]
        end += span[1]
    return source[start:end]


def excluded_background(course, root):
    ref = course["course_reference"]
    for clause in re.findall(r"Not open[^.!?]*", root["requirements_text"], re.I):
        compact = re.sub(r"[^A-Z0-9]", "", clause.upper())
        if re.search(
            r"(?<!\d)" + str(ref["course_number"]) + r"(?!\d)", clause
        ) and any(
            re.sub(r"[^A-Z0-9]", "", subject.upper()) in compact
            for subject in ref["subjects"]
        ):
            return True
    return False


def review_handles(root):
    return {f"review:{i}": r["id"] for i, r in enumerate(root["reviews"], 1)}


def validate_section(name, candidate, task, root, lookup):
    if (
        name == "search_profile"
        and not root.get("description", "").strip()
        and not root.get("official_learning_outcomes")
    ):
        return {
            "status": "insufficient_evidence",
            "value": None,
            "error": "The catalog description is empty; use the source title instead of inferred search metadata.",
            "citation_repairs": [],
        }
    jsonschema.Draft202012Validator(task["schema"]["properties"][name]).validate(
        candidate
    )
    value = copy.deepcopy(candidate)
    state = "valid"
    repairs = []
    if name == "search_profile":
        summary = value["summary"]["text"].rstrip()
        if summary.endswith((",", ";", ":")):
            raise ValueError(
                "Summary appears clipped; rewrite it as a short complete sentence, never cut a word or end with a comma."
            )
        claims = [
            value["summary"],
            *value["topics"],
            *value["skills_taught"],
            *value["assumed_background"],
            *value.get("activity_tags", []),
        ]
        for claim in claims:
            if not claim["evidence"]:
                raise ValueError("Search claims require evidence")
            for citation in claim["evidence"]:
                original = copy.deepcopy(citation)
                key = lookup.context.resolve(citation["course_id"])
                course = lookup.evidence.get(key)
                if citation["field"] == "official_learning_outcomes":
                    quote = outcome_quote(citation, course)
                    citation.update(course_id=key, quote=quote)
                    if citation != original:
                        repairs.append(
                            {"original": original, "resolved": copy.deepcopy(citation)}
                        )
                    continue
                if "outcome_index" in citation:
                    raise ValueError(
                        "outcome_index is only valid for official learning outcome evidence"
                    )
                if "source_url" in citation and (
                    not course or citation["source_url"] != course.get("source_url")
                ):
                    raise ValueError(
                        "Evidence source_url must match the supplied course source"
                    )
                quote = (
                    source_quote(citation["quote"], course.get(citation["field"], ""))
                    if course
                    else None
                )
                if not quote and course:
                    matches = [
                        (field, source_quote(citation["quote"], course.get(field, "")))
                        for field in ("title", "description", "requirements_text")
                        if field != citation["field"]
                    ]
                    matches = [(field, span) for field, span in matches if span]
                    if len(matches) == 1:
                        citation["field"], quote = matches[0]
                if not quote:
                    matches = [
                        {"course_id": source_id, "field": field, "quote": span}
                        for source_id, source in lookup.evidence.items()
                        for field in ("title", "description", "requirements_text")
                        if (
                            span := source_quote(
                                citation["quote"], source.get(field, "")
                            )
                        )
                    ]
                    hint = (
                        f" This quote occurs at {matches!r}; cite the course containing the quote, not the course mentioned in it."
                        if matches
                        else ""
                    )
                    raise ValueError(
                        f"Invalid evidence for {citation['course_id']}.{citation['field']}: {citation['quote']!r}. Copy a short exact substring from supplied text; do not paraphrase or invent omitted text."
                        + hint
                    )
                citation.update(course_id=key, quote=quote)
                if course.get("source_url"):
                    citation["source_url"] = course["source_url"]
                if citation != original:
                    repairs.append(
                        {"original": original, "resolved": copy.deepcopy(citation)}
                    )
        for claim in [
            value["summary"],
            *value["topics"],
            *value["skills_taught"],
            *value.get("activity_tags", []),
        ]:
            if any(
                e["course_id"] != root["course_id"]
                or e["field"]
                not in {"description", "title", "official_learning_outcomes"}
                for e in claim["evidence"]
            ):
                raise ValueError(
                    "Taught content must cite the root course description, title or official learning outcomes, not prerequisites. Omit claims supported only by another course."
                )
        labels = [tag["label"] for tag in value.get("activity_tags", [])]
        if len(labels) != len(set(labels)):
            raise ValueError("Activity tags must have distinct labels")
        for tag in value.get("activity_tags", []):
            if any(e["field"] == "title" for e in tag["evidence"]):
                raise ValueError(
                    "Activity tags require descriptions or official outcomes; a title alone does not establish an activity"
                )
        for claim in value["assumed_background"]:
            for citation in claim["evidence"]:
                key = citation["course_id"]
                if key != root["course_id"] and excluded_background(
                    lookup.evidence[key], root
                ):
                    raise ValueError(
                        f"{key} is listed in a credit exclusion, not a positive prerequisite. Remove background claims imported from this excluded course; do not relabel taught content as assumed knowledge."
                    )
        jsonschema.Draft202012Validator(task["schema"]["properties"][name]).validate(
            value
        )
    elif name == "requirements":
        if ambiguous_semicolons(root["requirements_text"]):
            value["status"] = "needs_review"
            note = "Best-effort Boolean grouping inferred from ambiguous punctuation; consult the original requirements text."
            if note not in value["notes"]:
                value["notes"].append(note)
        linked = list(root["linked_courses"])
        compact = re.sub(r"[^A-Z0-9]", "", root["requirements_text"].upper())
        for key, course in lookup.evidence.items():
            ref = course["course_reference"]
            number = str(ref["course_number"])
            if (
                key != root["course_id"]
                and re.search(
                    r"(?<!\d)" + number + r"(?!\d)", root["requirements_text"]
                )
                and any(re.sub(r"[^A-Z0-9]", "", s) in compact for s in ref["subjects"])
            ):
                if ref not in linked:
                    linked.append(ref)
        payload = {
            "requirements_text": root["requirements_text"],
            "linked_courses": linked,
        }
        restore_quotes(value, payload)
        repairs.extend(
            {"original": before, "resolved": copy.deepcopy(after)}
            for before, after in zip(candidate["nodes"], value["nodes"])
            if before != after
        )
        diagnostics = graph_diagnostics(value, payload)
        if diagnostics:
            raise ValueError("\n".join(diagnostics))
        validate_graph(value, payload)
        state = "needs_review" if value["status"] == "needs_review" else "valid"
    else:
        reviews = {r["id"]: r for r in root["reviews"]}
        if value["status"] == "insufficient_evidence":
            if value["themes"]:
                raise ValueError(
                    "Insufficient evidence cannot contain sentiment claims"
                )
            state = "insufficient_evidence"
        else:
            if not reviews or not value["themes"]:
                raise ValueError(
                    "Supported sentiment requires attributable reviews and themes"
                )
            for theme in value["themes"]:
                original_ids = theme["review_ids"]
                handles = review_handles(root)
                ids = [
                    key if key in reviews else handles.get(key, key)
                    for key in original_ids
                ]
                if (
                    not ids
                    or len(set(ids)) != len(ids)
                    or any(key not in reviews for key in ids)
                ):
                    raise ValueError(
                        "Sentiment cites unavailable or duplicate review evidence. "
                        f"Unknown IDs: {[key for key in ids if key not in reviews]}. "
                        f"Use distinct citation_id handles from the course reviews: {list(handles)}. "
                        "Copy the handle exactly; do not shorten or reconstruct a hash."
                    )
                if ids != original_ids:
                    repairs.append(
                        {
                            "field": "review_ids",
                            "original": original_ids,
                            "resolved": ids,
                        }
                    )
                theme["review_ids"] = ids
                theme["evidence_count"] = len(ids)
                theme["evidence"] = [reviews[key] for key in ids]
                evidence = theme["evidence"]
                years = sorted(
                    {r["date"][:4] for r in evidence if re.match(r"\d{4}", r["date"])}
                )
                people = {
                    r["instructor_id"]: r.get("instructor_name") for r in evidence
                }
                subject = theme.get("subject_instructor_id")
                if (
                    task.get("named_instructor_themes")
                    and subject is None
                    and any(people.values())
                    and (
                        theme["aspect"] == "teaching_clarity"
                        or (theme["aspect"] == "overall" and len(people) == 1)
                    )
                ):
                    raise ValueError(
                        "Name the instructor: teaching_clarity themes and single-instructor overall themes require subject_instructor_id. "
                        "Split teaching feedback into separate named-instructor themes, each citing only that instructor's reviews."
                    )
                if subject is not None:
                    if set(people) != {subject}:
                        raise ValueError(
                            "Instructor-specific themes must cite only reviews attributed to subject_instructor_id"
                        )
                    name = people[subject]
                    if not name or name not in theme["summary"]:
                        raise ValueError(
                            "Instructor-specific summary must include the exact instructor_name from its cited reviews"
                        )
                theme["scope"] = {
                    "instructors": [
                        {"id": key, "name": people[key]} for key in sorted(people)
                    ],
                    "review_year_start": years[0] if years else None,
                    "review_year_end": years[-1] if years else None,
                    "historical": True,
                }
                # Normalize an explicit leading date label from the citations;
                # model-written thematic prose is preserved and scope is always typed.
                prefix = re.match(
                    r"^Reviews (?:from \d{4}(?:\s*(?:to|[-–—])\s*\d{4})?|of .+?\(\d{4}(?:\s*(?:to|[-–—])\s*\d{4})?\))",
                    theme["summary"],
                    re.I,
                )
                if prefix and years:
                    period = (
                        years[0]
                        if years[0] == years[-1]
                        else years[0] + "–" + years[-1]
                    )
                    names = {name for name in people.values() if name}
                    label = (
                        f"Reviews of {next(iter(names))} ({period})"
                        if len(people) == 1 and len(names) == 1
                        else f"Reviews from {period}"
                    )
                    original = theme["summary"]
                    theme["summary"] = label + original[prefix.end() :]
                    if theme["summary"] != original:
                        repairs.append(
                            {
                                "field": "summary_scope",
                                "original": original,
                                "resolved": theme["summary"],
                            }
                        )
    return {"status": state, "value": value, "error": None, "citation_repairs": repairs}
