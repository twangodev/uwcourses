"""Independent instructor summaries, composed into a cited student course preview."""

import copy
import json
import re

from sqlalchemy import select
from .schema import results

from .models import digest
from .student_context import grade_sentence
from .course_context import sample_reviews


def without_archive_refs(value):
    """Recognize old fingerprints when only archival citation pointers were added."""
    if isinstance(value, dict):
        return {
            k: without_archive_refs(v)
            for k, v in value.items()
            if k not in {"source_record", "alternative_source_records"}
        }
    if isinstance(value, list):
        return [without_archive_refs(v) for v in value]
    return value


def profile_identity(profile):
    """Inference semantics, independent of client scheduling and transport."""
    return digest(
        {
            k: v
            for k, v in profile.items()
            if k not in {"base_url", "concurrency", "request_timeout_seconds"}
        }
    )


def scope_prompt(prompt, mode):
    """Give the writer only the instructions matching its restricted schema."""
    heading = "Return only this request's fields:\n"
    if heading in prompt:
        before, rest = prompt.split(heading, 1)
        modes, after = rest.split("\nDo not describe", 1)
        instruction = re.search(rf"(?ms)^- {re.escape(mode)}: (.*?)(?=^- |\Z)", modes)
        if instruction is None:
            raise ValueError(f"Missing student-summary instructions for {mode}")
        prompt = (
            before + heading + instruction[1].strip() + "\n\nDo not describe" + after
        )
    if mode == "history":
        prompt = prompt.replace(
            "Prioritize current instructors.",
            "Discuss only the supplied historical reviews. The current roster is context, not review evidence.",
        )
    return prompt


def summary_seeds(jobs, ids, run, *, allow_partial=False):
    seeds = {}
    for job in sorted(
        (jobs.status(i) for i in ids), key=lambda j: (j["created_at"], j["job_id"])
    ):
        if (job["status"] != "complete" and not allow_partial) or job[
            "source_run"
        ] != run:
            raise ValueError(
                "Student summary reuse requires completed jobs from the same snapshot"
            )
        job_profile = json.loads(job["spec_json"])["profile"]
        for row in jobs.db.execute(
            select(results.c.course_id, results.c.output_json).where(
                results.c.job_id == job["job_id"], results.c.status == "complete"
            ),
        ):
            original = json.loads(row["output_json"])
            profile = dict(job_profile)
            timeout = original.get("provenance", {}).get("request_timeout_seconds")
            if timeout is not None:
                profile["request_timeout_seconds"] = timeout
            seeds[row["course_id"]] = {
                "job_id": job["job_id"],
                "profile": profile,
                "failed_subtasks": [
                    t
                    for t in original.get("provenance", {}).get("subtasks", [])
                    if t.get("error")
                ],
                "output": {
                    k: v
                    for k, v in original.items()
                    if k in {"sections", "model", "model_revision", "task_version"}
                },
            }
    return seeds


def describes_review_availability(text):
    return bool(
        re.search(
            r"\bno reviewed history\b|\bno (?:course-specific |student )?reviews (?:are )?(?:available|provided)\b",
            text.casefold(),
        )
    )


def contains_inline_review_handle(text):
    return bool(re.search(r"\breview:\d+\b", text, re.I))


def validate_claims(value, payload):
    reviews = {r["citation_id"]: r for r in payload["reviews"]}
    # Hard rejection ceilings allow modest room beyond the prompt's concise targets.
    # Do not regenerate grounded claims solely for exceeding those softer targets.
    limits = {
        "summary": 80,
        "quick_take": 55,
        "difficulty_workload": 45,
        "student_experience": 45,
    }
    seen = set()
    for field, claims in value.items():
        if field not in {
            "summary",
            "quick_take",
            "difficulty_workload",
            "student_experience",
        }:
            continue
        if sum(len(c["text"].split()) for c in claims) > limits[field]:
            raise ValueError(
                f"Shorten {field} to at most {limits[field]} words; preserve the supporting citations"
            )
        for claim in claims:
            normalized = " ".join(claim["text"].casefold().split())
            if normalized in seen:
                raise ValueError(
                    "Do not repeat the same claim across fields; give each field a distinct purpose"
                )
            seen.add(normalized)
            if contains_inline_review_handle(normalized):
                raise ValueError(
                    "Remove inline review handles from prose; keep the supporting handles in review_ids only."
                )
            if describes_review_availability(normalized):
                raise ValueError(
                    "Do not describe review availability in a cited claim; runtime supplies availability separately. Summarize the supplied reviews instead."
                )
            # Variation describes disagreement, not population-wide consensus.
            consensus_text = re.sub(
                r"\b(?:vary|varies|varied|differ|differs|differed) widely\b",
                "",
                normalized,
            )
            if re.search(
                r"\b(widely|universally|unanimously)\b|\btop choice\b|\bstudents generally (?:prefer|agree)\b",
                consensus_text,
            ):
                raise ValueError(
                    "Sampled reviews do not establish popularity or consensus. Describe what the cited reviewers say without ranking instructors or claiming widespread agreement."
                )
            ids = claim["review_ids"]
            if (
                not ids
                or len(set(ids)) != len(ids)
                or any(i not in reviews for i in ids)
            ):
                raise ValueError(
                    "Cite distinct citation_id handles only, not source IDs. Allowed handles: "
                    + ", ".join(reviews)
                )
            if re.search(r"[\u4e00-\u9fff]", claim["text"]) or not re.search(
                r"[.!?][\"'’”)]?$", claim["text"].strip()
            ):
                raise ValueError(
                    "Write complete English sentences with ending punctuation, without truncation or stray non-English words"
                )
            years = set(re.findall(r"\b(?:19|20)\d{2}\b", claim["text"]))
            cited_years = {reviews[i].get("date", "")[:4] for i in ids}
            if not years <= cited_years:
                raise ValueError(
                    "A calendar year in a claim must come from its cited review dates"
                )
            if re.search(r"\bGPA\b|\bA\s*/\s*AB\b", claim["text"], re.I):
                raise ValueError(
                    "Do not generate grade statistics; runtime inserts computed grade sentences"
                )
    mode = payload["mode"]
    if mode == "overview":
        if value.get("summary"):
            raise ValueError("Overview requires quick_take claims, with summary empty")
    else:
        if any(
            value.get(k, [])
            for k in ("quick_take", "difficulty_workload", "student_experience")
        ):
            raise ValueError(
                "Return this scope in summary only; leave other arrays empty"
            )
    if (
        mode == "professor"
        and value.get("summary")
        and payload["instructor_name"]
        not in " ".join(c["text"] for c in value["summary"])
    ):
        raise ValueError("Name the supplied current instructor exactly in the summary")


def generate_student(profile, task, payload, generate=None):
    from .agents import generate_generic, ORCHESTRATOR, serialize_messages
    from .jobs import WORKER_VERSION
    from pydantic_ai import capture_run_messages

    generate = generate or generate_generic
    source = payload["student_context"]
    prior = (
        payload["summary_seed"]["output"]
        .get("sections", {})
        .get("student_summary", {})
        .get("value")
        or {}
    )
    same_source = prior.get("context_hash") == digest(source)
    if prior and not same_source:
        same_source = prior.get("context_hash") == digest(without_archive_refs(source))
    same_profile = prior.get("profile_hash") in {
        digest(profile),
        profile_identity(profile),
    }
    old_profile = payload["summary_seed"].get("profile")
    if old_profile and prior.get("profile_hash") == digest(old_profile):
        same_profile = profile_identity(old_profile) == profile_identity(profile)
    if not same_source or prior.get("task_hash") != digest(task) or not same_profile:
        prior = {}
    reused_scopes = []
    traces, conversations, errors = [], [], []
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def run(mode, reviews, person=None):
        if not reviews:
            return None
        failed = any(
            e["mode"] == mode
            and e.get("instructor_uid")
            == (person["instructor_uid"] if person else None)
            for e in prior.get("errors", [])
        )
        if prior and not failed:
            empty = {
                k: []
                for k in (
                    "summary",
                    "quick_take",
                    "difficulty_workload",
                    "student_experience",
                )
            }
            if mode == "professor":
                previous = next(
                    (
                        p
                        for p in prior["current_instructors"]
                        if p["instructor_uid"] == person["instructor_uid"]
                        and p["review_status"] in {"supported", "insufficient_evidence"}
                    ),
                    None,
                )
                if previous:
                    empty["summary"] = [
                        copy.deepcopy(c)
                        for c in previous["summary"]
                        if c["citations"][0]["type"] == "review"
                    ]
                else:
                    empty = None
            elif mode == "history":
                empty["summary"] = copy.deepcopy(prior["historical_context"])
            else:
                for k in ("quick_take", "difficulty_workload", "student_experience"):
                    empty[k] = [
                        copy.deepcopy(c)
                        for c in prior[k]
                        if c["citations"][0]["type"] == "review"
                    ]
            if empty is not None and not any(
                describes_review_availability(claim["text"])
                or contains_inline_review_handle(claim["text"])
                for claims in empty.values()
                for claim in claims
            ):
                reused_scopes.append(
                    {
                        "mode": mode,
                        "instructor_uid": person["instructor_uid"] if person else None,
                    }
                )
                return empty
        shown = [{**r, "citation_id": f"review:{i + 1}"} for i, r in enumerate(reviews)]
        evidence = {r["citation_id"]: r for r in shown}
        request = {
            "course_id": source["course_id"],
            "mode": mode,
            "term_id": source["term_id"],
            "term_name": source["term_name"],
            "instructor_name": person["name"] if person else None,
            "reviews": [
                {
                    k: v
                    for k, v in r.items()
                    if k
                    not in {
                        "id",
                        "source_review_id",
                        "instructor_id",
                        "source_url",
                        "course_id",
                    }
                }
                for r in shown
            ],
            "current_instructors": [p["name"] for p in source["current_instructors"]],
            "teaching_history": [
                {
                    "name": p["name"],
                    "terms": [t["term_name"] or t["term_id"] for t in p["terms"]],
                }
                for p in source.get("teaching_history", [])
            ],
        }
        previous_failure = next(
            (
                t
                for t in payload["summary_seed"].get("failed_subtasks", [])
                if t["mode"] == mode
                and t.get("instructor_uid")
                == (person["instructor_uid"] if person else None)
            ),
            None,
        )
        if prior and previous_failure:
            request["_history"] = previous_failure.get("conversation", [])
            checks = previous_failure.get("grounding_checks", [])
            if checks:
                last_check = checks[-1]
                rejected = {
                    c["claim_id"]: c["text"] for c in last_check["input"]["claims"]
                }
                request["repair_feedback"] = [
                    {"claim": rejected[issue["claim_id"]], "reason": issue["reason"]}
                    for issue in last_check["output"]["issues"]
                ]
            request["_compact_history"] = (
                "maximum context length" in previous_failure.get("error", "")
            )
        thinking = bool(profile.get("thinking")) or bool(
            prior
            and previous_failure
            and previous_failure.get("error", "").startswith("UnexpectedModelBehavior:")
        )
        if (
            prior
            and previous_failure
            and "Model token limit" in previous_failure.get("error", "")
            and previous_failure.get("inference", {}).get("max_output_tokens", 0)
            >= 16384
        ):
            # Repeated reasoning exhaustion needs a direct draft, not another
            # larger reasoning loop. The independent grounding check still thinks.
            thinking = False
            request["_compact_history"] = True
        output_limit = 8192 if thinking else 4096
        if (
            thinking
            and prior
            and previous_failure
            and "Model token limit" in previous_failure.get("error", "")
        ):
            output_limit = 16384
        local_profile = {
            **profile,
            "thinking": thinking,
            "max_output_tokens": min(profile["max_output_tokens"], output_limit),
        }
        inference = {
            "thinking": thinking,
            "max_output_tokens": local_profile["max_output_tokens"],
        }
        try:
            with capture_run_messages() as messages:
                scoped_task = copy.deepcopy(task)
                scoped_task["prompt"] = scope_prompt(scoped_task["prompt"], mode)
                fields = (
                    ("quick_take", "difficulty_workload", "student_experience")
                    if mode == "overview"
                    else ("summary",)
                )
                scoped_task["schema"]["properties"] = {
                    k: scoped_task["schema"]["properties"][k] for k in fields
                }
                scoped_task["schema"]["required"] = list(fields)
                if mode != "professor":
                    for field in fields:
                        scoped_task["schema"]["properties"][field]["maxItems"] = 1
                for field in fields:
                    ids = scoped_task["schema"]["properties"][field]["items"][
                        "properties"
                    ]["review_ids"]
                    ids["items"]["enum"] = list(evidence)
                    ids["maxItems"] = min(ids["maxItems"], len(evidence))
                result, cost = generate(local_profile, scoped_task, request)
            validate_claims(result, request)
            for field in (
                "summary",
                "quick_take",
                "difficulty_workload",
                "student_experience",
            ):
                result.setdefault(field, [])
            traces.append(
                {
                    "mode": mode,
                    "instructor_uid": person["instructor_uid"] if person else None,
                    "output": copy.deepcopy(result),
                    "inference": inference,
                }
            )
            conversations.extend(result.get("provenance", {}).get("conversation", []))
            for k in usage:
                usage[k] += cost.get(k, 0)
            for field in (
                "summary",
                "quick_take",
                "difficulty_workload",
                "student_experience",
            ):
                for claim in result[field]:
                    handles = claim.pop("review_ids")
                    claim["citations"] = [
                        {
                            "type": "review",
                            "run_id": payload["source_run"],
                            "review_id": evidence[i]["id"],
                            "source_review_id": evidence[i]["source_review_id"],
                            "source_instructor_id": evidence[i]["instructor_id"],
                            "instructor_name": evidence[i].get("instructor_name"),
                            "review_date": evidence[i]["date"],
                            "source_url": evidence[i]["source_url"],
                        }
                        for i in handles
                    ]
                    if mode == "history" or all(
                        evidence[i].get("instructor_scope") == "historical"
                        for i in handles
                    ):
                        names = ", ".join(
                            sorted(
                                {
                                    evidence[i]["instructor_name"]
                                    for i in handles
                                    if evidence[i].get("instructor_name")
                                }
                            )
                        )
                        if "historical" not in claim["text"].casefold():
                            label = (
                                f"Historical reviews of {names}"
                                if len(names) < 80
                                else "Historical reviews"
                            )
                            claim["text"] = label + ": " + claim["text"]
            return {
                k: result[k]
                for k in (
                    "summary",
                    "quick_take",
                    "difficulty_workload",
                    "student_experience",
                )
            }
        except Exception as exc:
            trace = serialize_messages(messages)
            conversations.extend(trace)
            error = {
                "mode": mode,
                "instructor_uid": person["instructor_uid"] if person else None,
                "error": f"{type(exc).__name__}: {exc}",
            }
            traces.append(
                {
                    **error,
                    "inference": inference,
                    "conversation": trace,
                    "grounding_checks": getattr(exc, "grounding_checks", []),
                }
            )
            errors.append(error)
            return None

    current = []
    current_reviews = []
    for person in source["current_instructors"]:
        result = run("professor", person["reviews"], person)
        grade = grade_sentence(person["grade_records"])
        claims = result["summary"] if result else []
        if not person["reviews"]:
            review_status, message = (
                "no_course_reviews",
                "No course-specific reviews available",
            )
        elif result is None:
            review_status, message = "generation_failed", "Summary generation failed"
        elif not claims:
            review_status, message = (
                "insufficient_evidence",
                "Available reviews do not provide enough detail",
            )
        else:
            review_status, message = "supported", None
        current.append(
            {
                "instructor_uid": person["instructor_uid"],
                "name": person["name"],
                "rmp_instructor_id": person["rmp_instructor_id"],
                "review_status": review_status,
                "message": message,
                "summary": claims + ([grade] if grade else []),
            }
        )
        current_reviews.extend(
            {**r, "instructor_scope": "current"} for r in person["reviews"]
        )
    historical_reviews = [
        {**r, "instructor_scope": "historical"} for r in source["historical_reviews"]
    ]
    history = run("history", historical_reviews)
    overview_reviews = (
        sample_reviews(current_reviews, 30) if current_reviews else historical_reviews
    )
    overview = run("overview", overview_reviews)
    grade = grade_sentence(source["grade_records"])
    overview = overview or {
        "quick_take": [],
        "difficulty_workload": [],
        "student_experience": [],
    }
    value = {
        "version": 2,
        "context_hash": digest(source),
        "task_hash": digest(task),
        "profile_hash": profile_identity(profile),
        "course_id": source["course_id"],
        "term_id": source["term_id"],
        "term_name": source["term_name"],
        "offered": source["offered"],
        "quick_take": overview["quick_take"] + ([grade] if grade else []),
        "difficulty_workload": overview["difficulty_workload"],
        "student_experience": overview["student_experience"],
        "current_instructors": current,
        "historical_context": history["summary"] if history else [],
        "teaching_history": [
            {
                "text": p["name"]
                + " is recorded teaching in "
                + ", ".join(t["term_name"] or t["term_id"] for t in p["terms"])
                + ". Recorded history may be incomplete and does not establish a future schedule.",
                "citations": [c for t in p["terms"] for c in t["citations"]],
            }
            for p in source.get("teaching_history", [])
            if p["terms"]
        ],
        "message": None if overview_reviews else "No course-specific reviews available",
        "errors": errors,
    }
    seed = payload["summary_seed"]
    previous = seed["output"]
    sections = copy.deepcopy(previous["sections"])
    overrides = {}
    if source.get("has_description") is False:
        sections["search_profile"] = {
            "status": "insufficient_evidence",
            "value": None,
            "error": "The catalog description is empty; use the source title instead of inferred search metadata.",
        }
        overrides["search_profile"] = {
            "source": "catalog",
            "reason": "empty_description",
        }
    sections["student_summary"] = {
        "status": "invalid" if errors else "valid",
        "value": value,
        "error": json.dumps(errors) if errors else None,
    }
    return {
        "model": profile["model"],
        "model_revision": profile["revision"],
        "task_version": task["version"],
        "sections": sections,
        "provenance": {
            "worker_version": WORKER_VERSION,
            "orchestrator": ORCHESTRATOR,
            "input_hash": digest(payload),
            "task_hash": digest(task),
            "section_origins": {
                k: {
                    "job_id": seed["job_id"],
                    "model": previous.get("model"),
                    "model_revision": previous.get("model_revision"),
                    "task_version": previous.get("task_version"),
                    "section_hash": digest(v),
                }
                for k, v in previous["sections"].items()
                if k != "student_summary"
            },
            "subtasks": traces,
            "section_overrides": overrides,
            "reused_scopes": reused_scopes,
            "conversation": conversations,
        },
    }, usage
