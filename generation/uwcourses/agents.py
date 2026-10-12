"""PydanticAI conversations; the pipeline owns checkpoints and domain validation."""

import asyncio
import copy
import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from importlib.metadata import version

import jsonschema
from openai import AsyncOpenAI
from pydantic_ai import (
    Agent,
    ModelMessagesTypeAdapter,
    ModelRetry,
    NativeOutput,
    RunContext,
    StructuredDict,
    ToolOutput,
    TextOutput,
    capture_run_messages,
)
from pydantic_ai.exceptions import (
    ModelAPIError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.vllm import VLLMProvider
from pydantic_ai.usage import RunUsage, UsageLimits

from .course_context import CourseLookup
from .profiles import DEFAULT_REQUEST_TIMEOUT_SECONDS
from .models import canonical, digest
from .unified import SECTIONS, compare_parsers, validate_section, review_handles

ORCHESTRATOR = {"name": "pydantic-ai", "version": version("pydantic-ai-slim")}
_TOOL_REQUESTS = ContextVar("coursemap_tool_requests", default=None)


@contextmanager
def capture_tool_definitions():
    """Isolate actual provider request schemas, including nested model runs."""
    requests = []
    token = _TOOL_REQUESTS.set(requests)
    try:
        yield requests
    finally:
        _TOOL_REQUESTS.reset(token)


def recorded_tool_provenance(requests):
    if not requests:
        # Injected non-OpenAI models and validation-only runs did not observe wire tools.
        return {}
    definitions = requests[0]["tools"]
    return {
        "tool_requests": copy.deepcopy(requests),
        # Never present one schema as constant when the request definitions changed.
        "tools": copy.deepcopy(definitions)
        if all(request["tools"] == definitions for request in requests)
        else None,
    }


def indexed_outcome_view(view):
    """Explicit citation indexes for the model; source records stay unchanged."""
    if "official_learning_outcomes" in view:
        view["official_learning_outcomes"] = [
            {**outcome, "outcome_index": index}
            for index, outcome in enumerate(view["official_learning_outcomes"])
        ]
    return view


def evidence_view(root, needed, related=False):
    if related:
        keys = {"course_id", "course_reference", "title"}
        if "search_profile" in needed:
            keys.update({"description", "official_learning_outcomes", "source_url"})
        return indexed_outcome_view({k: v for k, v in root.items() if k in keys})
    keys = {"course_id", "course_reference", "title"}
    if "search_profile" in needed:
        keys.update(
            {
                "description",
                "official_learning_outcomes",
                "requirements_text",
                "linked_courses",
                "source_url",
            }
        )
    if "requirements" in needed:
        keys.update({"requirements_text", "linked_courses"})
    if "student_experience" in needed:
        keys.update({"reviews", "review_selection"})
    result = {k: v for k, v in root.items() if k in keys}
    if "student_experience" in needed and "reviews" in root:
        result["reviews"] = [
            {**review, "citation_id": handle}
            for (handle, _), review in zip(
                review_handles(root).items(), root["reviews"], strict=True
            )
        ]
    if "requirements" in needed:
        from .requirements import shared_subject_references

        result["source_reference_spans"] = shared_subject_references(root)
    return indexed_outcome_view(result)


def output_budget(profile, messages, task, schema, repair=False):
    # Conservative estimate, including tool schema/system overhead; server limits
    # remain authoritative and the existing overflow recovery is retained.
    raw = (
        canonical(serialize_messages(messages))
        + native_prompt(task)
        + canonical(schema)
    )
    estimated_input = len(raw.encode("utf-8")) // 2 + 2048
    remaining = profile.get("context_length", 32768) - estimated_input
    return max(
        256,
        min(profile.get("max_output_tokens", 6144), 8192, remaining),
    )


def validation_feedback(exc):
    if not isinstance(exc, jsonschema.ValidationError):
        return str(exc)
    path = ".".join(str(part) for part in exc.absolute_path) or "<section>"
    message = exc.message
    if len(message) > 1000:
        expected = repr(exc.validator_value)[:500]
        message = (
            f"Failed {exc.validator} constraint {expected}; received {type(exc.instance).__name__}. "
            "Return a value matching the schema at this path. Do not encode objects as JSON strings."
        )
    return f"{path}: {message}"


NATIVE_INSTRUCTIONS = (
    "Use get_course for bounded, read-only lookups when needed. "
    "Submit the three sections with submit_sections. On validation feedback, return null "
    "for accepted or deferred sections and repair only sections_needed. "
    "Pass each section as a native JSON object or null, never a JSON-encoded string; "
    "search_profile contains only its own fields, with summary as a {text, evidence} object, "
    "and must not contain another section or section wrapper. "
    "Follow the supplied output schema."
)


def native_prompt(task):
    prompt = task["prompt"]
    if prompt.startswith(NATIVE_INSTRUCTIONS):
        return prompt
    if prompt.startswith("Your first turn is a lookup plan only:"):
        prompt = prompt.split("\n", 1)[1]
    return NATIVE_INSTRUCTIONS + "\n\n" + prompt


def serialize_messages(messages):
    data = json.loads(ModelMessagesTypeAdapter.dump_json(messages))
    for message in data:
        message.pop("provider_url", None)
    return data


class PinnedModel(OpenAIChatModel):
    def _get_tool_choice(self, model_settings, model_request_parameters):
        # This pinned PydanticAI hook returns the exact post-profile OpenAI mapping
        # subsequently passed to completions.create; do not prepare schemas twice.
        tools, choice = super()._get_tool_choice(
            model_settings, model_request_parameters
        )
        requests = _TOOL_REQUESTS.get()
        if requests is not None:
            requests.append(
                {
                    "request_index": len(requests),
                    "tools": copy.deepcopy(tools),
                    "output_mode": model_request_parameters.output_mode,
                }
            )
        return tools, choice

    async def request(self, messages, model_settings, model_request_parameters):
        response = await super().request(
            messages, model_settings, model_request_parameters
        )
        if response.model_name != self.model_name:
            raise ValueError("Inference server returned a different pinned model")
        return response


async def _conversation(profile, task, payload, context, model=None):
    from .jobs import WORKER_VERSION, generation_schema

    reused = payload.get("reuse_seed") if not payload.get("repair_seed") else None
    seed = payload.get("repair_seed") or reused
    previous = seed["output"] if seed else None
    root = {k: v for k, v in payload.items() if k not in {"repair_seed", "reuse_seed"}}
    if context.fingerprint(root["course_id"]) != digest(root):
        raise ValueError("Source context changed")
    lookup = CourseLookup(context, root["course_id"], **task.get("tool_limits", {}))
    sections = copy.deepcopy(previous["sections"]) if previous else {}
    deterministic_sections = []
    locked = [
        name
        for name in SECTIONS
        if name in sections and sections[name]["status"] != "invalid"
    ]
    if previous:
        for key, stamp in (
            previous.get("provenance", {}).get("dependencies", {}).items()
        ):
            if context.fingerprint(key) != stamp:
                raise ValueError("Repair dependency changed")
        for call in previous.get("provenance", {}).get("tool_calls", []):
            if call.get("tool") == "get_course":
                lookup.get_course(call["course_id"], call["from_course"])
    attempts, repaired = [], set()
    revalidated_candidates = []
    if previous:
        for name, section in list(sections.items()):
            if section["status"] != "invalid" or section.get("candidate") is None:
                continue
            try:
                accepted = validate_section(
                    name, section["candidate"], task, root, lookup
                )
                if name == "requirements":
                    compare_parsers(accepted, root["original_requirements"])
            except (ValueError, KeyError, TypeError, jsonschema.ValidationError):
                continue
            sections[name] = accepted
            repaired.add(name)
            revalidated_candidates.append(name)
    ast_attempts = 0
    turns = task.get("repair_turns", 3) if seed else 3
    if not 1 <= turns <= 4:
        raise ValueError("Repair turns must be between 1 and 4")
    repair_limit = task.get("ast_repair_attempts", 2)
    if repair_limit not in (0, 1, 2):
        raise ValueError("ast_repair_attempts must be 0, 1, or 2")
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": list(SECTIONS),
        "properties": {
            name: {
                "anyOf": [
                    generation_schema(task["schema"]["properties"][name]),
                    {"type": "null"},
                ]
            }
            for name in SECTIONS
        },
    }
    feedback = {
        "sections_needed": [
            name
            for name in SECTIONS
            if sections.get(name, {}).get("status", "invalid") == "invalid"
        ],
        "locked_sections": [
            name
            for name in SECTIONS
            if sections.get(name, {}).get("status", "invalid") != "invalid"
        ],
        "validation_errors": {
            name: s.get("error")
            for name, s in sections.items()
            if s["status"] == "invalid"
        },
    }
    needed = {
        name
        for name in SECTIONS
        if sections.get(name, {}).get("status", "invalid") == "invalid"
    }
    if "requirements" in needed:
        feedback["target_course_id"] = root["course_id"]
        feedback["direct_requirements_text"] = root["requirements_text"]
        feedback["requirement_scope"] = (
            "Parse only this target course's direct requirements. Never substitute a prerequisite course's requirements."
        )
    source_view = evidence_view(root, needed)
    initial = canonical(
        {
            "course": source_view,
            "lookup_evidence": {
                k: evidence_view(v, needed, related=True)
                for k, v in lookup.evidence.items()
                if k != root["course_id"]
            },
        }
    )
    history = None
    if seed:
        history = [
            ModelRequest(parts=[UserPromptPart(initial)]),
            ModelResponse(
                parts=[
                    TextPart(
                        canonical(
                            {
                                name: sections[name].get("candidate")
                                if name not in locked
                                else None
                                for name in SECTIONS
                            }
                        )
                    )
                ],
                model_name=f"{profile['model']}@{profile['revision']}",
            ),
        ]
        # Repair against a fresh, focused exchange. Prior traces remain in the parent job.
        initial = canonical(feedback)
    usage = RunUsage()
    request_failure = None
    recovery_events = []
    tool_requests = []
    direct_recovery = bool(
        previous
        and (
            previous.get("provenance", {}).get("recovery_events")
            or previous.get("provenance", {}).get("direct_recovery")
        )
    )
    request_thinking = bool(seed or profile.get("thinking"))

    def settings(ctx: RunContext):
        nonlocal request_thinking
        thinking = not direct_recovery and bool(
            (seed and not reused)
            or profile.get("thinking")
            or repair_limit
            and sections.get("requirements", {}).get("status") == "invalid"
        )
        request_thinking = thinking
        result = {
            "temperature": profile.get("temperature", 0.6),
            "top_p": profile.get("top_p", 0.95),
            "presence_penalty": profile.get("presence_penalty", 0),
            "max_tokens": output_budget(
                profile, ctx.messages, task, schema, repair=bool(seed and not reused)
            ),
            "parallel_tool_calls": False,
            "extra_body": {
                "top_k": profile.get("top_k", 20),
                "chat_template_kwargs": {"enable_thinking": thinking},
            },
        }
        if direct_recovery or (
            seed
            and (
                sections.get("search_profile", {}).get("status") != "invalid"
                or attempts
            )
        ):
            # A named tool choice also works when vLLM downgrades the generic
            # required-tool choice to auto. ASTs use only root source evidence.
            result["tool_choice"] = ["submit_sections"]
        return result

    async def run(selected_model):
        def parse_text_submission(text: str) -> dict:
            try:
                value = json.loads(text)
                if not isinstance(value, dict) or set(value) - set(SECTIONS):
                    raise ValueError(
                        "Return only the three course sections as a JSON object"
                    )
                return value
            except (ValueError, TypeError) as exc:
                raise ModelRetry(str(exc)) from exc

        agent = Agent(
            selected_model,
            output_type=[
                ToolOutput(
                    StructuredDict(schema, name="CourseSections"),
                    name="submit_sections",
                    strict=True,
                ),
                TextOutput(parse_text_submission),
            ],
            system_prompt=native_prompt(task),
            model_settings=settings,
            retries={"output": turns - 1, "tools": 1},
        )

        @agent.tool_plain
        def get_course(course_id: str, from_course: str) -> dict:
            """Read a related course from this frozen snapshot; from_course must already be provided."""
            found = lookup.get_course(course_id, from_course)
            return (
                evidence_view(found, needed, related=True)
                if found and "course_reference" in found
                else found
            )

        @agent.output_validator
        def validate(ctx: RunContext, value: dict) -> dict:
            nonlocal ast_attempts
            responses = [
                message
                for message in ctx.messages
                if isinstance(message, ModelResponse)
            ]
            if responses and responses[-1].finish_reason == "length":
                attempts.append(
                    {
                        "thinking": request_thinking,
                        "error": "Truncated response",
                    }
                )
                raise ModelRetry(
                    "Your answer was truncated. Return a shorter complete JSON object; do not omit source conditions."
                )
            errors = {}
            for name in SECTIONS:
                if name in sections and (
                    sections[name]["status"] != "invalid"
                    or not seed
                    and name == "requirements"
                    and ast_attempts >= 1 + repair_limit
                ):
                    continue
                if name == "requirements":
                    ast_attempts += 1
                candidate = value.get(name)
                if candidate is None:
                    if name == "student_experience" and not root["reviews"]:
                        sections[name] = {
                            "status": "insufficient_evidence",
                            "value": {"status": "insufficient_evidence", "themes": []},
                            "error": None,
                        }
                        continue
                    reason = "Model did not return this required section"
                    sections.setdefault(name, {"status": "invalid", "value": None})[
                        "error"
                    ] = reason
                    errors[name] = reason
                    continue
                try:
                    sections[name] = validate_section(
                        name, candidate, task, root, lookup
                    )
                    if name == "requirements":
                        compare_parsers(sections[name], root["original_requirements"])
                    if seed:
                        repaired.add(name)
                except (
                    ValueError,
                    KeyError,
                    TypeError,
                    jsonschema.ValidationError,
                ) as exc:
                    reason = validation_feedback(exc)
                    errors[name] = reason[:6000]
                    sections[name] = {
                        "status": "invalid",
                        "value": None,
                        "candidate": candidate,
                        "error": errors[name],
                    }
            needed = [
                name
                for name in SECTIONS
                if sections.get(name, {}).get("status") == "invalid"
                and not (
                    not seed
                    and name == "requirements"
                    and ast_attempts >= 1 + repair_limit
                )
            ]
            attempts.append(
                {
                    "turn": len(attempts),
                    "thinking": request_thinking,
                    "errors": errors,
                }
            )
            if needed:
                raise ModelRetry(
                    canonical(
                        {
                            "sections_needed": needed,
                            "locked_sections": [
                                name for name in SECTIONS if name not in needed
                            ],
                            "validation_errors": {
                                name: sections[name]["error"] for name in needed
                            },
                            "instruction": "Correct the previous answer using the supplied evidence. Other sections must be null.",
                        }
                    )
                )
            return value

        nonlocal request_failure, direct_recovery, tool_requests
        current_history, prompt = history, initial
        all_messages = []
        for recovery in range(2):
            with (
                capture_run_messages() as messages,
                capture_tool_definitions() as tool_requests,
            ):
                try:
                    await agent.run(
                        prompt,
                        message_history=current_history,
                        usage=usage,
                        usage_limits=UsageLimits(
                            request_limit=turns + lookup.max_calls + 1,
                            tool_calls_limit=lookup.max_calls + 1,
                        ),
                    )
                    all_messages = list(messages)
                    break
                except (
                    UnexpectedModelBehavior,
                    UsageLimitExceeded,
                    ModelAPIError,
                ) as exc:
                    all_messages = list(messages)
                    if (
                        recovery == 0
                        and isinstance(exc, ModelAPIError)
                        and getattr(exc, "status_code", None) == 400
                        and "maximum context length" in str(exc)
                    ):
                        recovery_events.append(
                            {
                                "reason": str(exc),
                                "conversation": serialize_messages(messages),
                                "thinking": False,
                                "context_compacted": True,
                                **recorded_tool_provenance(tool_requests),
                            }
                        )
                        direct_recovery = True
                        current_history = None
                        prompt = canonical(
                            {
                                "course": source_view,
                                "lookup_evidence": {
                                    k: evidence_view(v, needed, related=True)
                                    for k, v in lookup.evidence.items()
                                    if k != root["course_id"]
                                },
                                "instruction": "The previous conversation exceeded the context window. Correct the latest candidates using this source evidence. Accepted sections must be null.",
                                "sections_needed": [
                                    n
                                    for n in SECTIONS
                                    if sections.get(n, {}).get("status", "invalid")
                                    == "invalid"
                                ],
                                "rejected_sections": {
                                    n: s
                                    for n, s in sections.items()
                                    if s["status"] == "invalid"
                                },
                            }
                        )
                        continue
                    if (
                        recovery == 0
                        and isinstance(exc, UnexpectedModelBehavior)
                        and "exceeded before any response was generated" in str(exc)
                        and "Model token limit" in str(exc)
                    ):
                        recovery_events.append(
                            {
                                "reason": str(exc),
                                "conversation": serialize_messages(messages),
                                "thinking": False,
                                **recorded_tool_provenance(tool_requests),
                            }
                        )
                        direct_recovery = True
                        # Keep the native exchange, but don't feed thousands of
                        # unfinished reasoning tokens back into the context.
                        current_history = copy.deepcopy(messages)
                        for message in current_history:
                            if isinstance(message, ModelResponse):
                                message.parts = [
                                    p
                                    for p in message.parts
                                    if p.part_kind != "thinking"
                                ]
                                if not message.parts:
                                    message.parts = [
                                        TextPart(
                                            "[Reasoning truncated before an answer was submitted.]"
                                        )
                                    ]
                        prompt = canonical(
                            {
                                "instruction": "Your previous reasoning exhausted the token budget. Submit a concise corrected answer now using submit_sections. Do not continue the analysis. Accepted sections must be null.",
                                "sections_needed": [
                                    n
                                    for n in SECTIONS
                                    if sections.get(n, {}).get("status", "invalid")
                                    == "invalid"
                                ],
                                "validation_errors": {
                                    n: s.get("error")
                                    for n, s in sections.items()
                                    if s["status"] == "invalid"
                                },
                            }
                        )
                        continue
                    request_failure = str(exc)[:1500]
                    break
        return serialize_messages(all_messages)

    validation_only = bool(
        previous
        and all(
            sections.get(n, {}).get("status", "invalid") != "invalid" for n in SECTIONS
        )
    )
    if validation_only:
        messages = copy.deepcopy(previous.get("provenance", {}).get("conversation", []))
    elif model is not None:
        messages = await run(model)
    else:
        async with AsyncOpenAI(
            base_url=profile["base_url"],
            api_key=os.environ.get("COURSEMAP_INFERENCE_API_KEY", "local"),
            max_retries=2,
            timeout=profile.get(
                "request_timeout_seconds", DEFAULT_REQUEST_TIMEOUT_SECONDS
            ),
        ) as client:
            messages = await run(
                PinnedModel(
                    f"{profile['model']}@{profile['revision']}",
                    provider=VLLMProvider(openai_client=client),
                )
            )
    for name in SECTIONS:
        if name not in sections:
            sections[name] = {
                "status": "insufficient_evidence"
                if name == "student_experience" and not root["reviews"]
                else "invalid",
                "value": {"status": "insufficient_evidence", "themes": []}
                if name == "student_experience" and not root["reviews"]
                else None,
                "error": None
                if name == "student_experience" and not root["reviews"]
                else request_failure or "No accepted output",
            }
    provenance = {
        "worker_version": WORKER_VERSION,
        "validation_only": validation_only,
        "deterministic_sections": deterministic_sections,
        "revalidated_candidates": revalidated_candidates,
        "orchestrator": ORCHESTRATOR,
        "input_hash": digest(root),
        "task_hash": digest(task),
        "dependencies": lookup.dependencies,
        "tool_calls": lookup.trace,
        "attempts": attempts,
        "recovery_events": recovery_events,
        "direct_recovery": direct_recovery,
        "conversation": messages,
        "request_error": request_failure,
        "generation_settings": {
            k: profile[k]
            for k in (
                "temperature",
                "top_p",
                "top_k",
                "presence_penalty",
                "thinking",
                "max_output_tokens",
                "context_length",
                "engine",
                "engine_version",
            )
            if k in profile
        },
        "review_coverage": {"attributable_reviews": len(root["reviews"])},
        **(
            {
                key: copy.deepcopy(previous["provenance"][key])
                for key in ("tools", "tool_requests")
                if key in previous.get("provenance", {})
            }
            if validation_only
            else recorded_tool_provenance(tool_requests)
        ),
    }
    if seed:
        provenance.update(
            repair_version=2,
            repair_parent_job=seed["job_id"],
            repair_parent_output_hash=digest(previous),
            retained_sections=locked,
            repaired_sections=sorted(repaired),
            section_origins={
                name: (
                    (reused or {}).get("section_origins", {})
                    if reused
                    else previous.get("provenance", {}).get("section_origins", {})
                ).get(
                    name,
                    {
                        "job_id": seed["job_id"],
                        "output_hash": digest(previous),
                        "model": previous.get("model"),
                        "model_revision": previous.get("model_revision"),
                    },
                )
                for name in locked
            },
        )
        provenance["repair_context_compacted"] = True
        provenance["generation_settings"]["thinking"] = request_thinking
        if reused:
            provenance["reuse_source_job"] = reused["job_id"]
    result = {
        "course_id": root["course_id"],
        "model": profile["model"],
        "model_revision": profile["revision"],
        "model_id": f"{profile['model']}@{profile['revision']}",
        "task_version": task["version"],
        "sections": sections,
        "source_requirements": root["original_requirements"],
        "course_history": root["history"],
        "provenance": provenance,
    }
    return result, {
        "prompt_tokens": usage.input_tokens,
        "completion_tokens": usage.output_tokens,
        "total_tokens": usage.input_tokens + usage.output_tokens,
        "requests": usage.requests,
        "tool_calls": usage.tool_calls,
    }


def generate_unified(profile, task, payload, context, model=None):
    return asyncio.run(_conversation(profile, task, payload, context, model))


def generate_repair(profile, task, payload, context, model=None):
    return generate_unified(profile, task, payload, context, model)


async def _generic(profile, task, payload, model=None):
    from .jobs import WORKER_VERSION, generation_schema
    from .requirements import restore_quotes, validate_graph

    async def run(selected_model):
        grounding_checks = []
        grounding_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        agent = Agent(
            selected_model,
            output_type=NativeOutput(
                StructuredDict(generation_schema(task["schema"]), name=task["name"]),
                strict=True,
            ),
            system_prompt=task["prompt"],
            retries=2,
            model_settings={
                "temperature": profile.get("temperature", 0),
                "max_tokens": profile["max_output_tokens"],
                "extra_body": {
                    "chat_template_kwargs": {
                        "enable_thinking": profile.get("thinking", False)
                    }
                },
            },
        )

        @agent.output_validator
        async def validate(ctx: RunContext, value: dict) -> dict:
            try:
                if any(
                    isinstance(m, ModelResponse) and m.finish_reason == "length"
                    for m in ctx.messages[-1:]
                ):
                    raise ValueError("Model output was truncated or incomplete")
                jsonschema.Draft202012Validator(task["schema"]).validate(value)
                for field in task.get("evidence_fields", []):
                    for item in value[field]:
                        if item["evidence"] not in (payload.get("description") or ""):
                            raise ValueError(
                                "Evidence quote is absent from the source description"
                            )
                if task.get("validator") == "student_claims_v1":
                    from .student_summary import validate_claims

                    validate_claims(value, payload)
                if task.get("validator") == "requirements_graph_v1":
                    restore_quotes(value, payload)
                    validate_graph(value, payload)
                if task.get("grounding_task"):
                    from .grounding import grounding_request

                    request = grounding_request(task, value, payload)
                    if request:
                        check_task, check_payload = request
                        check_settings = {
                            "thinking": check_task.get("thinking", False),
                            "max_output_tokens": check_task.get(
                                "max_output_tokens", 2048
                            ),
                        }
                        try:
                            with capture_run_messages() as check_messages:
                                checked, cost = await _generic(
                                    {**profile, **check_settings},
                                    check_task,
                                    check_payload,
                                    model=selected_model,
                                )
                        except Exception as exc:
                            grounding_checks.append(
                                {
                                    "input": check_payload,
                                    "error": str(exc),
                                    "conversation": serialize_messages(check_messages),
                                    "inference": check_settings,
                                    **recorded_tool_provenance(
                                        getattr(exc, "tool_requests", [])
                                    ),
                                }
                            )
                            raise
                        grounding_checks.append(
                            {
                                "input": check_payload,
                                "output": checked,
                                "usage": cost,
                                "inference": check_settings,
                            }
                        )
                        for key in grounding_usage:
                            grounding_usage[key] += cost.get(key, 0)
                        if checked["issues"]:
                            claims = {
                                c["claim_id"]: c["text"]
                                for c in check_payload["claims"]
                            }
                            feedback = [
                                {"claim": claims[i["claim_id"]], "reason": i["reason"]}
                                for i in checked["issues"]
                            ]
                            raise ValueError(
                                "Revise these unsupported claims using their cited reviews, correct their citations, or omit them: "
                                + canonical(feedback)
                            )
            except (ValueError, KeyError, TypeError, jsonschema.ValidationError) as exc:
                raise ModelRetry(str(exc)[:6000]) from exc
            return value

        request = {
            k: v
            for k, v in payload.items()
            if k not in {"_history", "_compact_history"}
        }
        history = (
            ModelMessagesTypeAdapter.validate_python(copy.deepcopy(payload["_history"]))
            if payload.get("_history")
            else None
        )
        if history and payload.get("_compact_history"):
            # Retain the latest native drafts and feedback, but send source
            # evidence once. Original messages remain in the parent job trace.
            drafts = [
                i
                for i, m in enumerate(history)
                if isinstance(m, ModelResponse)
                and any(p.part_kind == "text" for p in m.parts)
            ]
            compact = []
            for message in history[
                (drafts[-2] if len(drafts) > 1 else drafts[-1])
                if drafts
                else len(history) :
            ]:
                message.parts = [
                    p for p in message.parts if p.part_kind in {"text", "retry-prompt"}
                ]
                if message.parts:
                    compact.append(message)
            history = compact or None
        # PydanticAI keeps historical system prompts when resuming. Apply the
        # current scoped instructions without losing drafts or retry feedback.
        for message in history or []:
            if isinstance(message, ModelRequest):
                for part in message.parts:
                    if part.part_kind == "system-prompt":
                        part.content = task["prompt"]
        try:
            with capture_tool_definitions() as tool_requests:
                result = await agent.run(
                    canonical(request),
                    message_history=history,
                    usage_limits=UsageLimits(request_limit=3),
                )
        except Exception as exc:
            exc.grounding_checks = grounding_checks
            exc.tool_requests = tool_requests
            raise
        output = result.output
        output.setdefault("provenance", {}).update(
            worker_version=WORKER_VERSION,
            orchestrator=ORCHESTRATOR,
            conversation=serialize_messages(result.all_messages()),
            input_hash=digest(payload),
            task_hash=digest(task),
            grounding_checks=grounding_checks,
            history_compacted=bool(payload.get("_compact_history")),
            **recorded_tool_provenance(tool_requests),
        )
        usage = result.usage
        return output, {
            "prompt_tokens": usage.input_tokens + grounding_usage["prompt_tokens"],
            "completion_tokens": usage.output_tokens
            + grounding_usage["completion_tokens"],
            "total_tokens": usage.input_tokens
            + usage.output_tokens
            + grounding_usage["total_tokens"],
        }

    if model is not None:
        return await run(model)
    async with AsyncOpenAI(
        base_url=profile["base_url"],
        api_key=os.environ.get("COURSEMAP_INFERENCE_API_KEY", "local"),
        max_retries=2,
        timeout=profile.get("request_timeout_seconds", DEFAULT_REQUEST_TIMEOUT_SECONDS),
    ) as client:
        return await run(
            PinnedModel(
                f"{profile['model']}@{profile['revision']}",
                provider=VLLMProvider(openai_client=client),
            )
        )


def generate_generic(profile, task, payload, model=None):
    return asyncio.run(_generic(profile, task, payload, model))
