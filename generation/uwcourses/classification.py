"""Offline, evidence-preserving activity classification and held-out evaluation.

Scores are proposals. Only independently labeled held-out data can enable a
category; this module never publishes course tags or edits the source archive.
"""

import hashlib
import json
import math
from pathlib import Path
import re
import time

TAXONOMY_VERSION = "course-activities-v1"
MODEL = "convaiinnovations/laya"
LABELS = {
    "programming": "Writing, modifying, or debugging computer programs.",
    "data-analysis": "Analyzing or interpreting datasets using statistical or computational methods.",
    "mathematical-reasoning": "Constructing mathematical arguments, proofs, or deriving mathematical results.",
    "writing": "Producing written arguments, reports, essays, or other substantial written work.",
    "lab-work": "Performing laboratory experiments or working with laboratory instruments.",
    "presentations": "Delivering oral presentations or presenting work to an audience.",
}


def read_jsonl(path):
    return [
        json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()
    ]


def write_jsonl(path, rows):
    with Path(path).open("x") as output:
        for row in rows:
            output.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")


def _probability(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise ValueError("Probabilities must be finite numbers in [0, 1]")
    return float(value)


def validate_inputs(rows):
    """Reject alias leakage, duplicate decisions, and missing evidence."""
    aliases, decisions = {}, set()
    for row in rows:
        for key in (
            "course_id",
            "passage",
            "source_id",
            "source_url",
            "quote",
            "label",
            "split",
        ):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"Missing {key}")
        if row["label"] not in LABELS or row["split"] not in {
            "train",
            "calibration",
            "eval",
        }:
            raise ValueError("Unknown label or split")
        if row["quote"] not in row["passage"]:
            raise ValueError("Evidence quote must occur exactly in source passage")
        if len(row["passage"]) > 1800:
            raise ValueError("Use a short source passage (maximum 1800 characters)")
        if "gold" not in row or (
            row["gold"] is not None and type(row["gold"]) is not bool
        ):
            raise ValueError(
                "gold must be manually labeled true, false, or null (unknown)"
            )
        identity = row.get("course_identity", row["course_id"])
        if not isinstance(identity, str) or not identity:
            raise ValueError("Invalid course_identity")
        names = row.get("aliases", [])
        if not isinstance(names, list) or not all(
            isinstance(name, str) and name for name in names
        ):
            raise ValueError("aliases must contain course identifiers")
        # One canonical identity and all known aliases belong to one split.
        for name in [identity, row["course_id"], *names]:
            previous = aliases.setdefault(name, (identity, row["split"]))
            if previous != (identity, row["split"]):
                raise ValueError(
                    f"Course or alias leaks across identities/splits: {name}"
                )
        key = (identity, row["source_id"], row["passage"], row["label"])
        if key in decisions:
            raise ValueError("Duplicate classification decision")
        decisions.add(key)
    return rows


def questions(label, reverse=False):
    criteria = {
        "yes": "The passage explicitly supports this activity: " + LABELS[label],
        "no": "The passage explicitly describes other activities without supporting this activity.",
        "unknown": "The passage is too vague, unrelated, or lacks evidence to decide.",
    }
    return {
        label: {
            "type": "choice",
            "instructions": "Classify only the supplied official passage. Do not assume activities from the course title or field.",
            "criteria": dict(reversed(list(criteria.items()))) if reverse else criteria,
        }
    }


def predict(rows, revision, device=None, agent=None):
    """Run pinned Laya locally; dependency/model loading is explicitly opt-in."""
    validate_inputs(rows)
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("revision must be an immutable 40-character Hub commit SHA")
    if agent is None:
        try:
            import laya
        except ImportError as error:
            raise ValueError(
                "Install the optional runtime with uv pip install 'laya==0.3.20' before classifier-predict"
            ) from error
        # The pinned 0.3.20 SDK accepts local paths but no revision keyword.
        # Resolve only the English root artifacts at the requested immutable SHA.
        from huggingface_hub import snapshot_download

        snapshot = snapshot_download(
            repo_id=MODEL,
            revision=revision,
            allow_patterns=[
                "rl_agent_config.json",
                "model.safetensors",
                "tokenizer/*",
                "encoder/*",
            ],
        )
        agent = laya.load(snapshot, device=device)
    predictions = []
    for row in rows:
        # Conservative token budget: reserve the full question head and separators.
        # Refuse truncation rather than evaluating evidence the model did not see.
        if hasattr(agent, "tok") and hasattr(agent, "cfg"):
            state = row["passage"].replace(agent.tok.mask_token, " ")
            tokens = agent.tok(state, add_special_tokens=False)["input_ids"]
            budget = (
                agent.cfg.get("max_len", 512) - agent.cfg.get("head_max_len", 192) - 8
            )
            if len(tokens) > budget:
                raise ValueError(
                    "Passage exceeds Laya token budget; split it into shorter official evidence passages"
                )
        start = time.perf_counter()
        normal = agent.predict(row["passage"], questions(row["label"]))
        reversed_result = agent.predict(
            row["passage"], questions(row["label"], reverse=True)
        )
        probabilities = normal["answers"][row["label"]]["probabilities"]
        reversed_probabilities = reversed_result["answers"][row["label"]][
            "probabilities"
        ]
        for scores in (probabilities, reversed_probabilities):
            if (
                set(scores) != {"yes", "no", "unknown"}
                or abs(sum(_probability(v) for v in scores.values()) - 1) > 0.002
            ):
                raise ValueError("Invalid Laya response probabilities")
        predictions.append(
            {
                **row,
                "model_id": MODEL,
                "model_revision": revision,
                "taxonomy_version": TAXONOMY_VERSION,
                "probabilities": probabilities,
                "reversed_probabilities": reversed_probabilities,
                "elapsed_seconds": time.perf_counter() - start,
                "runtime_device": str(getattr(agent, "device", "injected-test-agent")),
            }
        )
    return predictions


def _accepted(row, threshold):
    probabilities = row["probabilities"]
    return probabilities["yes"] >= threshold and probabilities["yes"] > max(
        probabilities["no"], probabilities["unknown"]
    )


def _metrics(rows, threshold):
    accepted = [r for r in rows if _accepted(r, threshold)]
    true_positive = sum(r["gold"] is True for r in accepted)
    positives = sum(r["gold"] is True for r in rows)
    known = [r for r in rows if r["gold"] is not None]
    ece = 0.0
    for index in range(10):
        bucket = [
            r for r in known if min(9, int(r["probabilities"]["yes"] * 10)) == index
        ]
        if bucket:
            confidence = sum(r["probabilities"]["yes"] for r in bucket) / len(bucket)
            accuracy = sum(r["gold"] is True for r in bucket) / len(bucket)
            ece += len(bucket) / len(known) * abs(confidence - accuracy)
    return {
        "decisions": len(rows),
        "accepted": len(accepted),
        "precision": true_positive / len(accepted) if accepted else None,
        "recall": true_positive / positives if positives else None,
        "accepted_coverage": len(accepted) / len(rows) if rows else 0,
        "ece": ece if known else None,
    }


def evaluate(rows):
    validate_inputs(rows)
    revisions = set()
    for row in rows:
        if row.get("reviewed") is not True:
            raise ValueError(
                "Evaluation requires independently manually reviewed labels (reviewed: true)"
            )
        if row.get("taxonomy_version") != TAXONOMY_VERSION:
            raise ValueError("Taxonomy version mismatch")
        revision = row.get("model_revision", "")
        if not re.fullmatch(r"[a-f0-9]{40}", revision) or not row.get("model_id"):
            raise ValueError("Predictions require model ID and immutable revision")
        revisions.add((row["model_id"], revision))
        for field in ("probabilities", "reversed_probabilities"):
            scores = row.get(field, {})
            if (
                set(scores) != {"yes", "no", "unknown"}
                or abs(sum(_probability(v) for v in scores.values()) - 1) > 0.002
            ):
                raise ValueError(f"Invalid {field}")
        elapsed = row.get("elapsed_seconds")
        if elapsed is not None and (
            isinstance(elapsed, bool)
            or not isinstance(elapsed, (int, float))
            or not math.isfinite(elapsed)
            or elapsed <= 0
        ):
            raise ValueError("elapsed_seconds must be positive and finite")
    if len(revisions) != 1:
        raise ValueError("Evaluate one immutable model revision at a time")
    categories = {}
    for label in LABELS:
        calibration = [
            r for r in rows if r["label"] == label and r["split"] == "calibration"
        ]
        heldout = [r for r in rows if r["label"] == label and r["split"] == "eval"]
        # Threshold selection only touches calibration. Prefer highest accepted coverage.
        candidates = sorted(
            {
                r["probabilities"]["yes"]
                for r in calibration
                if r["probabilities"]["yes"] >= 0.5
            }
        )
        threshold = next(
            (
                t
                for t in candidates
                if (m := _metrics(calibration, t))["accepted"] >= 20
                and m["precision"] >= 0.97
            ),
            None,
        )
        metrics = _metrics(heldout, threshold if threshold is not None else 1.01)
        diagnostics = {
            "unknown_cases": sum(r["gold"] is None for r in heldout),
            "unrelated_cases": sum(
                r.get("case_kind") == "unrelated" and r["gold"] is not True
                for r in heldout
            ),
            "order_reversal_cases": len(heldout),
            "max_order_probability_delta": max(
                (
                    abs(r["probabilities"]["yes"] - r["reversed_probabilities"]["yes"])
                    for r in heldout
                ),
                default=None,
            ),
        }
        enabled = (
            threshold is not None
            and metrics["accepted"] >= 100
            and metrics["precision"] >= 0.97
            and diagnostics["unknown_cases"] >= 10
            and diagnostics["unrelated_cases"] >= 10
            and diagnostics["max_order_probability_delta"] <= 0.05
        )
        categories[label] = {
            **metrics,
            "threshold": threshold,
            "diagnostics": diagnostics,
            "enabled": enabled,
            "fallback": "qwen" if not enabled else None,
        }
    duration = sum(r.get("elapsed_seconds", 0) for r in rows)
    model_id, revision = next(iter(revisions))
    digest = hashlib.sha256(
        json.dumps(rows, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "model_id": model_id,
        "model_revision": revision,
        "evaluation_sha256": digest,
        "categories": categories,
        "policy": "Per category: calibration >=20 accepted at >=97% precision; held-out >=100 accepted at >=97%; >=10 unknown and >=10 unrelated cases; reversal delta <=0.05. No automatic publication.",
        "decisions_per_second": len(rows) / duration
        if duration and all(r.get("elapsed_seconds") for r in rows)
        else None,
        "timing_includes_order_reversal": True,
    }
