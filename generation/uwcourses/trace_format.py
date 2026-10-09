"""Lossless archive plus a documented HF conversation projection.

Json features intentionally retain arbitrary tool arguments without an inferred
Arrow struct. Consumers using datasets>=4.7 receive native dictionaries; plain
Arrow consumers see the JSON extension's string storage.
"""

import copy
import json

from datasets import Features, Json, List, Value

from .models import canonical, digest

FORMAT = "hf-role-content-v1"
MESSAGE_FEATURE = {
    "role": Value("string"),
    "content": Value("string"),
    "thinking": Value("string"),
    "name": Value("string"),
    "tool_call_id": Value("string"),
    "tool_calls": List(Json()),
    "source_parts": List(Json()),
    "source_message_index": Value("int64"),
    "feedback": Value("bool"),
}
CONVERSATION_FIELDS = {
    "messages": List(MESSAGE_FEATURE),
    "tools": List(Json()),
    "conversation_format": Value("string"),
    "conversation_status": Value("string"),
    "conversation_issues": List(Json()),
    "tools_status": Value("string"),
}
TRACE_ADDED_FEATURES = {
    "trace_id": Value("string"),
    **CONVERSATION_FIELDS,
    "has_any_conversation": Value("bool"),
    "conversation_count": Value("int64"),
}
CONVERSATION_FEATURES = Features(
    {
        "conversation_id": Value("string"),
        "trace_id": Value("string"),
        "job_id": Value("string"),
        "run_id": Value("string"),
        "course_id": Value("string"),
        "output_id": Value("string"),
        "source_path": Value("string"),
        "source_hash": Value("string"),
        "parent_source_path": Value("string"),
        **CONVERSATION_FIELDS,
    }
)


def trace_features(existing_features):
    if not isinstance(existing_features, Features):
        existing_features = Features.from_arrow_schema(existing_features)
    return Features({**existing_features, **TRACE_ADDED_FEATURES})


def trace_id(row):
    return digest(
        {key: row.get(key) for key in ("job_id", "run_id", "course_id", "output_id")}
    )


def _text(value):
    return value if isinstance(value, str) else canonical(value)


def _issue(issues, code, path):
    issues.append({"code": code, "source_path": path})


def normalize_conversation(conversation, *, source_path="", tools=None):
    """Project recorded messages only. Raw typed parts remain available per message."""
    result = {
        "messages": [],
        "tools": copy.deepcopy(tools),
        "conversation_format": FORMAT,
        "conversation_status": "converted",
        "conversation_issues": [],
        "tools_status": "recorded" if tools is not None else "not_recorded",
    }
    messages, issues = result["messages"], result["conversation_issues"]
    recorded_call_ids = set()
    if tools is not None and not isinstance(tools, list):
        result["tools"] = None
        result["tools_status"] = "unsupported"
        _issue(issues, "tools_not_list", source_path)
    if not isinstance(conversation, list):
        result["conversation_status"] = "unsupported"
        _issue(issues, "conversation_not_list", source_path)
        return result
    if not conversation:
        result["conversation_status"] = "empty"
        return result
    for index, native in enumerate(conversation):
        path = f"{source_path}/{index}"
        if isinstance(native, dict) and isinstance(native.get("role"), str):
            # Older repair histories already used role/content dictionaries.
            msg = {
                "role": native["role"],
                "content": _text(native.get("content", "")),
                "thinking": native.get("thinking", native.get("reasoning_content")),
                "name": native.get("name"),
                "tool_call_id": native.get("tool_call_id"),
                "tool_calls": [],
                "source_parts": [copy.deepcopy(native)],
                "source_message_index": index,
                "feedback": False,
            }
            for call in native.get("tool_calls") or []:
                if isinstance(call.get("id"), str):
                    recorded_call_ids.add(call["id"])
                converted = copy.deepcopy(call)
                function = converted.get("function", {})
                args = function.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        _issue(issues, "invalid_tool_arguments_json", path)
                        continue
                if not isinstance(args, dict):
                    _issue(issues, "unsupported_tool_call", path)
                    continue
                function["arguments"] = args
                msg["tool_calls"].append(converted)
            if (
                msg["role"] == "tool"
                and msg.get("tool_call_id")
                and msg["tool_call_id"] not in recorded_call_ids
            ):
                _issue(issues, "unmatched_tool_result", path)
            messages.append(msg)
            continue
        if not isinstance(native, dict) or not isinstance(native.get("parts"), list):
            _issue(issues, "unsupported_message", path)
            continue
        parts = native["parts"]
        if native.get("instructions"):
            _issue(issues, "instructions_retained_only_in_raw_trace", path)
        if native.get("kind") == "response":
            msg = {
                "role": "assistant",
                "content": "",
                "thinking": None,
                "tool_calls": [],
                "source_parts": copy.deepcopy(parts),
                "source_message_index": index,
                "feedback": False,
            }
            text, thinking = [], []
            for position, part in enumerate(parts):
                if not isinstance(part, dict):
                    _issue(issues, "unsupported_part", f"{path}/parts/{position}")
                    continue
                kind = part.get("part_kind")
                if kind == "text":
                    text.append(_text(part.get("content", "")))
                elif kind == "thinking":
                    thinking.append(_text(part.get("content", "")))
                elif kind == "tool-call":
                    if isinstance(part.get("tool_call_id"), str):
                        recorded_call_ids.add(part["tool_call_id"])
                    args = part.get("args")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except ValueError:
                            _issue(
                                issues,
                                "invalid_tool_arguments_json",
                                f"{path}/parts/{position}",
                            )
                            continue
                    if not isinstance(args, dict) or not isinstance(
                        part.get("tool_name"), str
                    ):
                        _issue(
                            issues, "unsupported_tool_call", f"{path}/parts/{position}"
                        )
                        continue
                    msg["tool_calls"].append(
                        {
                            "id": part.get("tool_call_id"),
                            "type": "function",
                            "function": {
                                "name": part["tool_name"],
                                "arguments": copy.deepcopy(args),
                            },
                        }
                    )
                else:
                    _issue(
                        issues, "unsupported_response_part", f"{path}/parts/{position}"
                    )
            msg["content"] = "".join(text)
            msg["thinking"] = "".join(thinking) if thinking else None
            messages.append(msg)
        elif native.get("kind") == "request":
            for position, part in enumerate(parts):
                if not isinstance(part, dict):
                    _issue(issues, "unsupported_part", f"{path}/parts/{position}")
                    continue
                kind = part.get("part_kind")
                if kind in {"system-prompt", "user-prompt"}:
                    role = "system" if kind == "system-prompt" else "user"
                elif kind == "tool-return":
                    role = "tool"
                elif kind == "retry-prompt":
                    role = (
                        "tool"
                        if part.get("tool_name") and part.get("tool_call_id")
                        else "user"
                    )
                else:
                    _issue(
                        issues, "unsupported_request_part", f"{path}/parts/{position}"
                    )
                    continue
                if (
                    role == "tool"
                    and part.get("tool_call_id")
                    and part["tool_call_id"] not in recorded_call_ids
                ):
                    _issue(
                        issues,
                        "unmatched_tool_feedback"
                        if kind == "retry-prompt"
                        else "unmatched_tool_result",
                        f"{path}/parts/{position}",
                    )
                messages.append(
                    {
                        "role": role,
                        "content": _text(part.get("content", "")),
                        "name": part.get("tool_name") if role == "tool" else None,
                        "tool_call_id": part.get("tool_call_id")
                        if role == "tool"
                        else None,
                        "source_parts": [copy.deepcopy(part)],
                        "source_message_index": index,
                        "feedback": kind == "retry-prompt",
                    }
                )
        else:
            _issue(issues, "unsupported_message_kind", path)
    if issues:
        result["conversation_status"] = "partial" if messages else "unsupported"
    return result


def _pointer(key):
    return str(key).replace("~", "~0").replace("/", "~1")


def recorded_conversations(value, path=""):
    """Discover native histories at any depth, including repair/recovery branches."""
    if isinstance(value, dict):
        for key in sorted(value):
            child = value[key]
            child_path = path + "/" + _pointer(key)
            if key == "conversation" or key.endswith("_conversation"):
                if isinstance(child, list) and child:
                    yield child_path, child, value.get("tools")
            else:
                yield from recorded_conversations(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from recorded_conversations(child, path + f"/{index}")


def normalize_trace(row):
    """Return an augmented parent and separate recorded conversation rows."""
    original = dict(row)
    output = json.loads(row["output_json"])
    identity = trace_id(row)
    branches = []
    for path, conversation, tools in recorded_conversations(output):
        branches.append(
            {
                "conversation_id": digest({"trace_id": identity, "source_path": path}),
                "trace_id": identity,
                **{
                    key: row.get(key)
                    for key in ("job_id", "run_id", "course_id", "output_id")
                },
                "source_path": path,
                "source_hash": digest(conversation),
                "parent_source_path": path.rsplit("/", 1)[0],
                **normalize_conversation(conversation, source_path=path, tools=tools),
            }
        )
    provenance = output.get("provenance", {})
    primary = normalize_conversation(
        provenance.get("conversation", []),
        source_path="/provenance/conversation",
        tools=provenance.get("tools"),
    )
    if "conversation" not in provenance:
        primary["conversation_status"] = "missing"
    original.update(
        trace_id=identity,
        **primary,
        has_any_conversation=bool(branches),
        conversation_count=len(branches),
    )
    return original, branches
