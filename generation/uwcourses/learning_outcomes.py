"""Official outcome statements with source context, without generated additions."""

import re


def statement(text):
    return re.sub(r"\s+", " ", text).strip()


def outcome(
    text, *, source, source_url, observed_at=None, term=None, catalog_year=None
):
    return {
        "text": statement(text),
        "source": source,
        "source_url": source_url,
        "observed_at": observed_at,
        "term": str(term) if term is not None else None,
        "catalog_year": catalog_year,
    }


def catalog_outcomes(block, **context):
    """Guide's numbered statements are separated by audience display lines."""
    label = next(
        (
            node
            for node in block.select(".cbextra-label")
            if statement(node.get_text(" ", strip=True)) == "Learning Outcomes:"
        ),
        None,
    )
    if label is None:
        return []
    data = label.find_next_sibling(class_="cbextra-data")
    if data is None:
        return []
    # Restrict to this label's sibling: find_next could capture another course.
    from bs4 import BeautifulSoup

    # Inline emphasis must not introduce spaces into the quoted source text.
    copy = BeautifulSoup(str(data), "html.parser")
    for br in copy.find_all("br"):
        br.replace_with("\n")
    lines = copy.get_text().splitlines()
    texts, current = [], []

    def flush():
        if current:
            texts.append(statement(" ".join(current)))
            current.clear()

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("Audience:"):
            flush()
            continue
        numbered = re.match(r"^\d+\.\s+(.*)$", line)
        if numbered:
            flush()
            current.append(numbered[1])
        else:
            current.append(line)
    flush()
    return [outcome(text, source="catalog", **context) for text in texts if text]


def enrollment_outcomes(payload, **context):
    """Accept explicit outcome fields only; availability depends on API payload."""
    values = payload.get("learningOutcomes", payload.get("learning_outcomes", []))
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    result = []
    for value in values:
        if isinstance(value, dict):
            value = value.get("text", value.get("description"))
        if isinstance(value, str) and statement(value):
            result.append(outcome(value, source="enrollment", **context))
    return result


def response_observed_at(store, run, source, url, *, request=None):
    """Replay retains the archived fetch time rather than its new processing time."""
    from sqlalchemy import select
    from .schema import responses

    query = select(responses.c.fetched_at).where(
        responses.c.run_id == run,
        responses.c.source == source,
        responses.c.url == url,
    )
    if request is not None:
        from scrapy.utils.request import fingerprint

        query = query.where(responses.c.fingerprint == fingerprint(request).hex())
    rows = store.db.execute(query.distinct()).fetchall()
    # Multiple different requests at the same URL can have different times.
    return rows[0][0] if len(rows) == 1 else None


def merge_outcomes(*groups):
    """Only identical text and provenance deduplicate; conflicts remain visible."""
    results, seen = [], set()
    for group in groups:
        for value in group:
            key = tuple(
                value.get(field)
                for field in (
                    "text",
                    "source",
                    "source_url",
                    "observed_at",
                    "term",
                    "catalog_year",
                )
            )
            if key not in seen:
                results.append(dict(value))
                seen.add(key)
    return results


def merge_catalog_observations(previous_url, previous, incoming_url, incoming):
    """Cross-listing pages contribute outcomes without replacing unrelated facts."""

    def base(payload):
        return {
            key: value
            for key, value in payload.items()
            if key != "official_learning_outcomes"
        }

    # A refresh of the same canonical page replaces its factual payload. Other
    # subject pages contribute outcomes while the smallest URL owns main facts.
    if incoming_url <= previous_url:
        source_url, selected = incoming_url, base(incoming)
    else:
        source_url, selected = previous_url, base(previous)
    grouped = {}
    previous_outcomes = [
        value
        for value in previous.get("official_learning_outcomes") or []
        if value.get("source_url") != incoming_url
    ]
    # Retain other pages but replace this page's entire sequence, including an
    # explicitly empty new sequence. Raw bytes keep prior snapshot evidence.
    for values in (previous_outcomes, incoming.get("official_learning_outcomes") or []):
        for value in values:
            key = tuple(
                value.get(field) or ""
                for field in (
                    "source_url",
                    "source",
                    "observed_at",
                    "term",
                    "catalog_year",
                )
            )
            grouped.setdefault(key, []).append(value)
    selected["official_learning_outcomes"] = [
        value for key in sorted(grouped) for value in grouped[key]
    ]
    return source_url, selected


def course_outcome_map(store, run):
    """Shared catalog/enrollment evidence for reconciliation and inference."""
    from sqlalchemy import select
    from .models import CourseReference
    from .schema import observations

    result, aliases = {}, {}
    for data in store.records(run, "courses").values():
        reference = CourseReference.model_validate(data["course_reference"])
        result[reference.identifier] = list(
            data.get("official_learning_outcomes") or []
        )
        for subject in reference.subjects:
            aliases.setdefault((subject, reference.course_number), set()).add(
                reference.identifier
            )
    source_urls = {
        row[0]: row[1]
        for row in store.db.execute(
            select(observations.c.entity_id, observations.c.source_url).where(
                observations.c.run_id == run, observations.c.kind == "offerings"
            )
        )
    }
    for key, data in store.records(run, "offerings").items():
        reference = CourseReference.model_validate(data["course_reference"])
        candidates = set().union(
            *(
                aliases.get((subject, reference.course_number), set())
                for subject in reference.subjects
            )
        )
        if len(candidates) != 1:
            continue
        identifier = next(iter(candidates))
        values = data.get("official_learning_outcomes")
        if values is None:
            values = enrollment_outcomes(
                data["hit"],
                source_url=data.get("hit_source_url") or source_urls[key],
                observed_at=data.get("hit_observed_at"),
                term=data["term"],
            )
        result[identifier] = merge_outcomes(result[identifier], values)
    return result
