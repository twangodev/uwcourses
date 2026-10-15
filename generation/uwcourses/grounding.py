"""Prepare a bounded review-grounding check with exact draft-claim handles."""

import copy


def grounding_request(task, value, payload):
    reviews = {r["citation_id"]: r for r in payload["reviews"]}
    claims = []
    for field in ("summary", "quick_take", "difficulty_workload", "student_experience"):
        for claim in value.get(field, []):
            claims.append(
                {
                    "claim_id": f"claim:{len(claims) + 1}",
                    "field": field,
                    "text": claim["text"],
                    "cited_reviews": [
                        {
                            "review_id": i,
                            "instructor": reviews[i].get("instructor_name"),
                            "instructor_scope": reviews[i].get("instructor_scope"),
                            "date": reviews[i].get("date"),
                            "comment": reviews[i]["comment"],
                            "difficulty_rating": reviews[i].get("difficulty_rating"),
                            "quality_rating": reviews[i].get("quality_rating"),
                        }
                        for i in claim["review_ids"]
                    ],
                }
            )
    if not claims:
        return None
    check = copy.deepcopy(task["grounding_task"])
    check["schema"]["properties"]["issues"]["items"]["properties"]["claim_id"][
        "enum"
    ] = [c["claim_id"] for c in claims]
    return check, {
        "course_id": payload["course_id"],
        "mode": payload["mode"],
        "snapshot_term": payload.get("term_name", payload["term_id"]),
        "review_evidence_scope": "past_experience_only",
        "claims": claims,
    }
