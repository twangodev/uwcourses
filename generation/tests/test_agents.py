"""PydanticAI owns tools, retries and message history; validators own acceptance."""

import copy
import asyncio
import json
import unittest
from pathlib import Path

from pydantic_ai import ModelMessagesTypeAdapter
from pydantic_ai.messages import (
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage
from pydantic_ai.providers.openai import OpenAIProvider
from openai import AsyncOpenAI
import httpx2

import test_unified
from uwcourses.agents import (
    generate_unified,
    generate_repair,
    generate_generic,
    evidence_view,
    PinnedModel,
    capture_tool_definitions,
    recorded_tool_provenance,
)
from uwcourses.unified import validate_section


class AgentTests(unittest.TestCase):
    def pinned_model(self, answers):
        wire_requests = []
        replies = iter(answers)

        def handle(request):
            body = json.loads(request.content)
            wire_requests.append(body)
            answer = next(replies)
            if isinstance(answer, tuple):
                status, error = answer
                return httpx2.Response(
                    status,
                    json={"error": {"message": error, "type": "invalid_request_error"}},
                )
            message = {"role": "assistant", "content": json.dumps(answer)}
            finish_reason = "stop"
            if body.get("tools"):
                message = {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": f"call-{len(wire_requests)}",
                            "type": "function",
                            "function": {
                                "name": "submit_sections",
                                "arguments": json.dumps(answer),
                            },
                        }
                    ],
                }
                finish_reason = "tool_calls"
            return httpx2.Response(
                200,
                json={
                    "id": "mock-completion",
                    "object": "chat.completion",
                    "created": 0,
                    "model": body["model"],
                    "choices": [
                        {"index": 0, "message": message, "finish_reason": finish_reason}
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                },
            )

        client = AsyncOpenAI(
            api_key="test",
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
        )
        self.addCleanup(lambda: asyncio.run(client.close()))
        model = PinnedModel(
            "test-pinned", provider=OpenAIProvider(openai_client=client)
        )
        return model, wire_requests

    def test_runtime_tools_match_actual_openai_function_and_output_definitions(self):
        f = self.fixture
        model, wire = self.pinned_model(
            [
                {
                    "search_profile": f.search,
                    "requirements": f.requirements,
                    "student_experience": f.experience,
                }
            ]
        )
        output, _ = generate_unified(f.profile, self.task, f.root, f.context, model)
        self.assertEqual(output["provenance"]["tools"], wire[0]["tools"])
        self.assertEqual(
            {tool["function"]["name"] for tool in wire[0]["tools"]},
            {"get_course", "submit_sections"},
        )
        self.assertEqual(
            output["provenance"]["tool_requests"][0]["tools"], wire[0]["tools"]
        )
        json.dumps(output["provenance"])

    def test_recovery_preserves_actual_tools_for_both_conversations(self):
        f = self.fixture
        model, wire = self.pinned_model(
            [
                (400, "maximum context length exceeded"),
                {
                    "requirements": f.requirements,
                    "search_profile": None,
                    "student_experience": None,
                },
            ]
        )
        output, _ = generate_repair(f.profile, self.task, self.seed, f.context, model)
        self.assertEqual(len(wire), 2)
        self.assertEqual(
            output["provenance"]["recovery_events"][0]["tools"], wire[0]["tools"]
        )
        self.assertEqual(output["provenance"]["tools"], wire[1]["tools"])
        self.assertEqual(len(output["provenance"]["tool_requests"]), 1)

    def test_native_json_output_records_observed_empty_tools_without_inventing_function(
        self,
    ):
        model, wire = self.pinned_model([{"answer": "yes"}])
        task = {
            "name": "plain",
            "version": 1,
            "prompt": "Return an answer.",
            "schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
                "additionalProperties": False,
            },
        }
        output, _ = generate_generic({"max_output_tokens": 256}, task, {}, model)
        self.assertNotIn("tools", wire[0])
        self.assertEqual(output["provenance"]["tools"], [])
        self.assertEqual(
            output["provenance"]["tool_requests"][0]["output_mode"], "native"
        )

    def test_nested_tool_capture_is_isolated_and_varying_schemas_are_not_combined(self):
        with capture_tool_definitions() as outer:
            outer.append(
                {"tools": [{"type": "function", "function": {"name": "outer"}}]}
            )
            with capture_tool_definitions() as inner:
                inner.append({"tools": []})
            self.assertEqual(len(outer), 1)
        self.assertEqual(recorded_tool_provenance(inner)["tools"], [])
        outer.append({"tools": []})
        recorded = recorded_tool_provenance(outer)
        self.assertIsNone(recorded["tools"])
        self.assertEqual(len(recorded["tool_requests"]), 2)
        self.assertEqual(recorded_tool_provenance([]), {})

    def test_model_prompt_labels_outcome_indexes_without_changing_source(self):
        f = self.fixture
        f.outcome_evidence()
        f.root["official_learning_outcomes"] = [
            {
                **f.root["official_learning_outcomes"][0],
                "text": f"Official statement {index}.",
            }
            for index in range(7)
        ]
        original = copy.deepcopy(f.root)
        fingerprint = f.context.fingerprint(f.root["course_id"])
        related = evidence_view(f.root, {"search_profile"}, related=True)
        self.assertEqual(
            [value["outcome_index"] for value in related["official_learning_outcomes"]],
            list(range(7)),
        )

        def model(messages, info):
            rendered = ModelMessagesTypeAdapter.dump_json(messages).decode()
            self.assertIn(
                "native JSON object or null, never a JSON-encoded string", rendered
            )
            self.assertIn("summary as a {text, evidence} object", rendered)
            prompts = [
                json.loads(part.content)
                for message in messages
                for part in message.parts
                if isinstance(part, UserPromptPart)
            ]
            evidence = prompts[0]["course"]["official_learning_outcomes"]
            self.assertEqual(
                [value["outcome_index"] for value in evidence], list(range(7))
            )
            self.assertEqual(evidence[-1]["text"], "Official statement 6.")
            self.assertEqual(
                evidence[-1]["source_url"],
                original["official_learning_outcomes"][-1]["source_url"],
            )
            return self.response(
                {
                    "search_profile": f.search,
                    "requirements": f.requirements,
                    "student_experience": f.experience,
                }
            )

        result, _ = generate_unified(
            f.profile, self.task, f.root, f.context, FunctionModel(model)
        )
        self.assertEqual(result["sections"]["search_profile"]["status"], "valid")
        self.assertEqual(f.root, original)
        self.assertEqual(f.context.fingerprint(f.root["course_id"]), fingerprint)
        self.assertNotIn("outcome_index", f.root["official_learning_outcomes"][0])
        self.assertNotIn("tools", result["provenance"])

    def setUp(self):
        f = self.fixture = test_unified.UnifiedTests()
        f.setUp()
        self.task = {**f.task, "ast_repair_attempts": 0, "repair_turns": 3}
        self.previous = {
            "course_id": f.root["course_id"],
            "model": "test",
            "model_revision": "a" * 40,
            "sections": {
                "search_profile": validate_section(
                    "search_profile", f.search, f.task, f.root, f.lookup
                ),
                "requirements": {
                    "status": "invalid",
                    "candidate": {**f.requirements, "root": "missing"},
                    "value": None,
                    "error": "Missing root node",
                },
                "student_experience": {
                    "status": "insufficient_evidence",
                    "value": f.experience,
                },
            },
            "provenance": {"worker_version": 10, "dependencies": {}, "tool_calls": []},
        }
        self.seed = {
            **f.root,
            "repair_seed": {"job_id": "parent", "output": self.previous},
        }

    def response(self, value, **kwargs):
        return ModelResponse(
            parts=[ToolCallPart("submit_sections", value)],
            usage=RequestUsage(input_tokens=10, output_tokens=5),
            **kwargs,
        )

    def test_valid_saved_candidate_is_revalidated_without_inference(self):
        f = self.fixture
        self.previous["sections"]["requirements"]["candidate"] = f.requirements

        def model(*args):
            self.fail("A valid saved candidate should not require another model call")

        output, usage = generate_repair(
            f.profile, self.task, self.seed, f.context, FunctionModel(model)
        )
        self.assertEqual(output["sections"]["requirements"]["status"], "valid")
        self.assertTrue(output["provenance"]["validation_only"])
        self.assertEqual(
            output["provenance"]["revalidated_candidates"], ["requirements"]
        )
        self.assertEqual(usage["requests"], 0)
        self.assertEqual(output["provenance"]["conversation"], [])
        self.assertNotIn("tools", output["provenance"])

    def test_native_repair_uses_model_retry_and_locks_accepted_sections(self):
        f = self.fixture
        calls = []
        original = copy.deepcopy(self.previous)

        def model(messages, info):
            calls.append(copy.deepcopy(messages))
            self.assertEqual(info.model_settings["tool_choice"], ["submit_sections"])
            if len(calls) > 1:
                self.assertTrue(
                    any(
                        isinstance(part, RetryPromptPart)
                        for m in messages
                        for part in m.parts
                    )
                )
                self.assertIn(
                    "missing-again",
                    ModelMessagesTypeAdapter.dump_json(messages).decode(),
                )
            return self.response(
                {
                    "search_profile": {"bad": "ignore"},
                    "requirements": {**f.requirements, "root": "missing-again"}
                    if len(calls) == 1
                    else f.requirements,
                    "student_experience": None,
                }
            )

        output, usage = generate_repair(
            f.profile, self.task, self.seed, f.context, FunctionModel(model)
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(output["sections"]["requirements"]["status"], "valid")
        self.assertEqual(
            output["sections"]["search_profile"], original["sections"]["search_profile"]
        )
        self.assertEqual(self.previous, original)
        self.assertEqual(usage["completion_tokens"], 10)
        self.assertEqual(output["provenance"]["repair_parent_job"], "parent")
        self.assertEqual(output["provenance"]["orchestrator"]["name"], "pydantic-ai")
        self.assertTrue(output["provenance"]["generation_settings"]["thinking"])
        ModelMessagesTypeAdapter.validate_python(output["provenance"]["conversation"])

    def test_exhausted_native_repair_keeps_last_rejection_and_history(self):
        f = self.fixture
        calls = []

        def model(*args):
            calls.append(1)
            return self.response(
                {"requirements": {**f.requirements, "root": "still-missing"}}
            )

        output, _ = generate_repair(
            f.profile, self.task, self.seed, f.context, FunctionModel(model)
        )
        self.assertEqual(len(calls), 3)
        self.assertEqual(output["sections"]["requirements"]["status"], "invalid")
        self.assertEqual(
            output["sections"]["requirements"]["candidate"]["root"], "still-missing"
        )
        self.assertIsNotNone(output["provenance"]["request_error"])
        self.assertGreater(len(output["provenance"]["conversation"]), 4)

    def test_bulk_defers_ast_and_repairs_search_without_replacing_accepted_data(self):
        f = self.fixture
        calls = []

        def model(*args):
            calls.append(1)
            search = copy.deepcopy(f.search)
            if len(calls) == 1:
                search["summary"]["evidence"][0]["quote"] = "fabricated quote"
            return self.response(
                {
                    "search_profile": search,
                    "requirements": {**f.requirements, "root": "missing"},
                    "student_experience": f.experience,
                }
            )

        output, _ = generate_unified(
            f.profile, self.task, f.root, f.context, FunctionModel(model)
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(output["sections"]["search_profile"]["status"], "valid")
        self.assertEqual(output["sections"]["requirements"]["status"], "invalid")
        self.assertFalse(any(a["thinking"] for a in output["provenance"]["attempts"]))

    def test_inline_ast_retry_budget_is_respected(self):
        f = self.fixture
        calls = []

        def model(*args):
            calls.append(1)
            return self.response(
                {
                    "search_profile": f.search,
                    "requirements": {**f.requirements, "root": "missing"},
                    "student_experience": f.experience,
                }
            )

        output, _ = generate_unified(
            f.profile,
            {**self.task, "ast_repair_attempts": 1},
            f.root,
            f.context,
            FunctionModel(model),
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(output["sections"]["requirements"]["status"], "invalid")

    def test_native_tool_call_uses_bounded_snapshot_lookup(self):
        f = self.fixture
        calls = []

        def model(messages, info):
            calls.append(1)
            self.assertEqual(info.function_tools[0].name, "get_course")
            if len(calls) == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            "get_course",
                            {"course_id": "COMPSCI 200", "from_course": "COMPSCI 300"},
                        )
                    ]
                )
            self.assertTrue(
                any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts)
            )
            return self.response(
                {
                    "search_profile": f.search,
                    "requirements": f.requirements,
                    "student_experience": f.experience,
                }
            )

        output, _ = generate_unified(
            f.profile, self.task, f.root, f.context, FunctionModel(model)
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            output["provenance"]["dependencies"]["COMPSCI 200"],
            f.context.fingerprint("COMPSCI 200"),
        )
        self.assertEqual(output["sections"]["search_profile"]["status"], "valid")

    def test_native_lookup_preserves_missing_and_already_provided_status(self):
        f = self.fixture
        for identifier, expected in [
            (
                "MISSING 999",
                {
                    "course_id": "MISSING 999",
                    "error": "Course not found in this snapshot",
                },
            ),
            ("COMPSCI 300", {"course_id": "COMPSCI 300", "already_provided": True}),
        ]:
            with self.subTest(identifier=identifier):
                calls = []

                def model(messages, info):
                    calls.append(1)
                    if len(calls) == 1:
                        return ModelResponse(
                            parts=[
                                ToolCallPart(
                                    "get_course",
                                    {
                                        "course_id": identifier,
                                        "from_course": "COMPSCI 300",
                                    },
                                )
                            ]
                        )
                    returned = [
                        p.content
                        for m in messages
                        for p in m.parts
                        if isinstance(p, ToolReturnPart)
                    ]
                    self.assertEqual(returned[-1], expected)
                    return self.response(
                        {
                            "search_profile": f.search,
                            "requirements": f.requirements,
                            "student_experience": f.experience,
                        }
                    )

                generate_unified(
                    f.profile, self.task, f.root, f.context, FunctionModel(model)
                )
                self.assertEqual(len(calls), 2)

    def test_thinking_only_truncation_recovers_without_thinking(self):
        f = self.fixture
        calls = []

        def model(messages, info):
            calls.append(info.model_settings)
            if len(calls) == 1:
                return ModelResponse(
                    parts=[ThinkingPart("repeated analysis " * 20)],
                    finish_reason="length",
                )
            self.assertFalse(
                info.model_settings["extra_body"]["chat_template_kwargs"][
                    "enable_thinking"
                ]
            )
            self.assertFalse(
                any(isinstance(p, ThinkingPart) for m in messages for p in m.parts)
            )
            self.assertIn(
                "exhausted the token budget",
                ModelMessagesTypeAdapter.dump_json(messages).decode(),
            )
            return self.response(
                {
                    "requirements": f.requirements,
                    "search_profile": None,
                    "student_experience": None,
                }
            )

        output, _ = generate_repair(
            f.profile, self.task, self.seed, f.context, FunctionModel(model)
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(output["sections"]["requirements"]["status"], "valid")
        self.assertIsNone(output["provenance"]["request_error"])
        self.assertEqual(len(output["provenance"]["recovery_events"]), 1)
        self.assertEqual(
            output["sections"]["search_profile"],
            self.previous["sections"]["search_profile"],
        )

    def test_schema_feedback_does_not_echo_large_malformed_candidate(self):
        f = self.fixture
        malformed = "malformed-json-object " * 2000
        calls = []

        def model(messages, info):
            calls.append(messages)
            if len(calls) == 1:
                return ModelResponse(
                    parts=[
                        TextPart(
                            json.dumps(
                                {
                                    "requirements": malformed,
                                    "search_profile": None,
                                    "student_experience": None,
                                }
                            )
                        )
                    ]
                )
            feedback = [
                p for m in messages for p in m.parts if isinstance(p, RetryPromptPart)
            ][-1]
            content = str(feedback.content)
            self.assertLess(len(content), 2000)
            self.assertIn("object", content)
            self.assertIn("received str", content)
            self.assertNotIn(malformed, content)
            return self.response(
                {
                    "requirements": f.requirements,
                    "search_profile": None,
                    "student_experience": None,
                }
            )

        output, _ = generate_repair(
            f.profile, self.task, self.seed, f.context, FunctionModel(model)
        )
        self.assertEqual(output["sections"]["requirements"]["status"], "valid")
        self.assertIn(malformed, json.dumps(output["provenance"]["conversation"]))
        self.assertEqual(len(calls), 2)

    def test_context_overflow_compacts_history_and_preserves_trace(self):
        from pydantic_ai.exceptions import ModelHTTPError
        from uwcourses.agents import serialize_messages

        f = self.fixture
        calls = []

        def model(messages, info):
            calls.append(messages)
            if len(calls) == 1:
                raise ModelHTTPError(
                    status_code=400,
                    model_name="test",
                    body={
                        "message": "This model's maximum context length is 32768 tokens"
                    },
                )
            text = ModelMessagesTypeAdapter.dump_json(messages).decode()
            self.assertIn("rejected_sections", text)
            self.assertIn(f.root["course_id"], text)
            self.assertFalse(
                info.model_settings["extra_body"]["chat_template_kwargs"][
                    "enable_thinking"
                ]
            )
            return self.response(
                {
                    "requirements": f.requirements,
                    "search_profile": None,
                    "student_experience": None,
                }
            )

        output, _ = generate_repair(
            f.profile, self.task, self.seed, f.context, FunctionModel(model)
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(output["sections"]["requirements"]["status"], "valid")
        event = output["provenance"]["recovery_events"][0]
        self.assertTrue(event["context_compacted"])
        self.assertFalse(output["provenance"]["generation_settings"]["thinking"])
        self.assertEqual(
            event["conversation"],
            serialize_messages(calls[0]),
        )
        self.assertEqual(
            output["sections"]["search_profile"],
            self.previous["sections"]["search_profile"],
        )

    def test_chained_repair_retains_previous_direct_recovery_mode(self):
        f = self.fixture
        self.previous["provenance"]["recovery_events"] = [{"thinking": False}]

        def model(messages, info):
            self.assertFalse(
                info.model_settings["extra_body"]["chat_template_kwargs"][
                    "enable_thinking"
                ]
            )
            self.assertEqual(info.model_settings["tool_choice"], ["submit_sections"])
            return self.response({"requirements": f.requirements})

        output, _ = generate_repair(
            f.profile, self.task, self.seed, f.context, FunctionModel(model)
        )
        self.assertEqual(output["sections"]["requirements"]["status"], "valid")

    def test_plain_json_submission_still_gets_domain_validation_and_retry(self):
        f = self.fixture
        calls = []

        def model(*args):
            calls.append(1)
            value = {
                "requirements": {**f.requirements, "status": "parsed"}
                if len(calls) == 1
                else f.requirements
            }
            return ModelResponse(parts=[TextPart(json.dumps(value))])

        output, _ = generate_repair(
            f.profile, self.task, self.seed, f.context, FunctionModel(model)
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(output["sections"]["requirements"]["status"], "valid")
        self.assertEqual(len(output["provenance"]["attempts"]), 2)

    def test_thinking_truncation_recovery_is_bounded(self):
        f = self.fixture
        calls = []

        def model(*args):
            calls.append(1)
            return ModelResponse(
                parts=[ThinkingPart("unfinished")], finish_reason="length"
            )

        output, _ = generate_repair(
            f.profile, self.task, self.seed, f.context, FunctionModel(model)
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(output["sections"]["requirements"]["status"], "invalid")
        self.assertIn("Model token limit", output["provenance"]["request_error"])

    def test_truncated_balanced_json_is_not_accepted(self):
        f = self.fixture

        def model(*args):
            return self.response(
                {
                    "search_profile": f.search,
                    "requirements": f.requirements,
                    "student_experience": f.experience,
                },
                finish_reason="length",
            )

        output, _ = generate_unified(
            f.profile, self.task, f.root, f.context, FunctionModel(model)
        )
        self.assertEqual(output["sections"]["search_profile"]["status"], "invalid")
        self.assertTrue(output["provenance"]["request_error"])

    def test_chained_repair_compacts_prior_native_conversation(self):
        f = self.fixture

        def reject(*args):
            return self.response(
                {"requirements": {**f.requirements, "root": "unresolved"}}
            )

        previous, _ = generate_repair(
            f.profile, self.task, self.seed, f.context, FunctionModel(reject)
        )
        payload = {
            **f.root,
            "repair_seed": {"job_id": "second-parent", "output": previous},
        }

        def accept(messages, info):
            self.assertLess(len(messages), len(previous["provenance"]["conversation"]))
            self.assertIn(
                "unresolved", ModelMessagesTypeAdapter.dump_json(messages).decode()
            )
            return self.response({"requirements": f.requirements})

        output, _ = generate_repair(
            f.profile, self.task, payload, f.context, FunctionModel(accept)
        )
        self.assertEqual(output["sections"]["requirements"]["status"], "valid")
        self.assertEqual(output["provenance"]["repair_parent_job"], "second-parent")

    def test_generic_agent_rejects_truncation_bad_json_and_false_evidence(self):
        from pydantic_ai.exceptions import UnexpectedModelBehavior

        task = {
            "name": "generic",
            "prompt": "Extract quoted topics",
            "schema": {"type": "object"},
            "evidence_fields": ["topics"],
        }
        for finish, content in [
            ("length", "{}"),
            ("stop", "not json"),
            ("stop", '{"topics":[{"evidence":"invented"}]}'),
        ]:
            with self.subTest(finish=finish, content=content):
                calls = []

                def model(*args):
                    calls.append(1)
                    return ModelResponse(
                        parts=[TextPart(content)], finish_reason=finish
                    )

                with self.assertRaises(UnexpectedModelBehavior):
                    generate_generic(
                        {"max_output_tokens": 1024},
                        task,
                        {"description": "Actual source"},
                        FunctionModel(model),
                    )
                self.assertEqual(len(calls), 3)

    def test_resumed_generic_conversation_uses_current_prompt(self):
        from pydantic_ai import ModelMessagesTypeAdapter
        from pydantic_ai.messages import ModelRequest, SystemPromptPart, UserPromptPart

        history = ModelMessagesTypeAdapter.dump_python(
            [
                ModelRequest(
                    parts=[
                        SystemPromptPart("Old conflicting instructions"),
                        UserPromptPart("Original evidence"),
                    ]
                ),
                ModelResponse(parts=[TextPart('{"answer": "old draft"}')]),
                ModelRequest(
                    parts=[UserPromptPart("Correct the instructor attribution")]
                ),
            ],
            mode="json",
        )
        original = json.dumps(history, sort_keys=True)
        task = {
            "name": "resumed_summary",
            "prompt": "Only return the requested historical summary.",
            "schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        }

        def model(messages, info):
            parts = [p for m in messages for p in m.parts]
            self.assertEqual(
                [p.content for p in parts if p.part_kind == "system-prompt"],
                [task["prompt"]],
            )
            self.assertTrue(
                any(
                    getattr(p, "content", None) == "Correct the instructor attribution"
                    for p in parts
                )
            )
            self.assertTrue(
                any(
                    getattr(p, "content", None) == '{"answer": "old draft"}'
                    for p in parts
                )
            )
            return ModelResponse(
                parts=[TextPart('{"answer": "corrected"}')], finish_reason="stop"
            )

        out, _ = generate_generic(
            {"max_output_tokens": 1024},
            task,
            {"_history": history},
            FunctionModel(model),
        )
        self.assertEqual(out["answer"], "corrected")
        self.assertEqual(json.dumps(history, sort_keys=True), original)

    def test_context_repair_sends_evidence_once_and_preserves_feedback(self):
        from pydantic_ai import ModelMessagesTypeAdapter
        from pydantic_ai.messages import ModelRequest, RetryPromptPart, UserPromptPart

        history = ModelMessagesTypeAdapter.dump_python(
            [
                ModelRequest(parts=[UserPromptPart("Repeated old evidence" * 1000)]),
                ModelResponse(parts=[TextPart('{"answer": "old draft"}')]),
                ModelRequest(
                    parts=[
                        RetryPromptPart("Correct the instructor attribution"),
                        UserPromptPart("Repeated old evidence" * 1000),
                    ]
                ),
            ],
            mode="json",
        )
        original = json.dumps(history, sort_keys=True)
        task = {
            "name": "context_repair",
            "prompt": "Use the current evidence.",
            "schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        }

        def model(messages, info):
            serialized = ModelMessagesTypeAdapter.dump_json(messages).decode()
            self.assertNotIn("Repeated old evidence", serialized)
            self.assertEqual(serialized.count("Current source evidence"), 1)
            self.assertIn("Correct the instructor attribution", serialized)
            self.assertIn("old draft", serialized)
            return ModelResponse(
                parts=[TextPart('{"answer": "corrected"}')], finish_reason="stop"
            )

        out, _ = generate_generic(
            {"max_output_tokens": 1024},
            task,
            {
                "_history": history,
                "_compact_history": True,
                "evidence": "Current source evidence",
            },
            FunctionModel(model),
        )
        self.assertTrue(out["provenance"]["history_compacted"])
        self.assertEqual(json.dumps(history, sort_keys=True), original)

    def test_grounding_feedback_repairs_draft_and_keeps_both_traces(self):
        from uwcourses.tasks import load_task

        task = load_task(
            Path(__file__).resolve().parents[2] / "inference/tasks/student_summary.json"
        )
        payload = {
            "course_id": "MUSIC 101",
            "term_id": "1272",
            "term_name": "Fall 2026",
            "mode": "overview",
            "current_instructors": [],
            "reviews": [
                {
                    "citation_id": "review:1",
                    "instructor_name": "Example",
                    "date": "2025-01-01",
                    "comment": "The final essay is easy, but the exam is hard.",
                    "difficulty_rating": 5,
                    "quality_rating": 4,
                }
            ],
        }

        def draft(text):
            return {
                "summary": [],
                "quick_take": [{"text": text, "review_ids": ["review:1"]}],
                "difficulty_workload": [],
                "student_experience": [],
            }

        answers = [
            draft("The final exam is easy."),
            {
                "issues": [
                    {
                        "claim_id": "claim:1",
                        "reason": "The review calls the essay easy, not the exam.",
                    }
                ]
            },
            draft("The reviewer found the final essay easy and the exam hard."),
            {"issues": []},
        ]
        calls = []

        def model(messages, info):
            calls.append(messages)
            return ModelResponse(
                parts=[TextPart(json.dumps(answers[len(calls) - 1]))],
                finish_reason="stop",
            )

        out, usage = generate_generic(
            {"max_output_tokens": 1024}, task, payload, FunctionModel(model)
        )
        self.assertEqual(len(calls), 4)
        self.assertIn("essay easy", out["quick_take"][0]["text"])
        checks = out["provenance"]["grounding_checks"]
        cited = checks[-1]["input"]["claims"][0]["cited_reviews"][0]
        self.assertEqual(cited["difficulty_rating"], 5)
        self.assertEqual(cited["quality_rating"], 4)
        self.assertEqual(len(checks), 2)
        self.assertEqual(
            checks[0]["inference"], {"thinking": True, "max_output_tokens": 8192}
        )
        self.assertTrue(checks[0]["output"]["provenance"]["conversation"])
        self.assertEqual(checks[1]["output"]["issues"], [])
        self.assertGreaterEqual(
            usage["total_tokens"], sum(c["usage"]["total_tokens"] for c in checks)
        )
        pinned, wire = self.pinned_model(answers)
        recorded, _ = generate_generic(
            {"max_output_tokens": 1024}, task, payload, pinned
        )
        self.assertEqual(len(wire), 4)
        self.assertEqual(recorded["provenance"]["tools"], [])
        self.assertEqual(len(recorded["provenance"]["tool_requests"]), 2)
        for check in recorded["provenance"]["grounding_checks"]:
            self.assertEqual(check["output"]["provenance"]["tools"], [])
            self.assertEqual(len(check["output"]["provenance"]["tool_requests"]), 1)
        from pydantic_ai.exceptions import UnexpectedModelBehavior

        repeated = []

        def never_repairs(messages, info):
            answer = answers[len(repeated) % 2]
            repeated.append(1)
            return ModelResponse(
                parts=[TextPart(json.dumps(answer))], finish_reason="stop"
            )

        with self.assertRaises(UnexpectedModelBehavior) as failed:
            generate_generic(
                {"max_output_tokens": 1024}, task, payload, FunctionModel(never_repairs)
            )
        self.assertEqual(len(repeated), 6)
        self.assertEqual(len(failed.exception.grounding_checks), 3)
        self.assertTrue(
            failed.exception.grounding_checks[-1]["output"]["provenance"][
                "conversation"
            ]
        )

    def test_changed_source_blocks_repair_before_inference(self):
        f = self.fixture
        f.context.courses["COMPSCI 300"] = {**f.root, "description": "Changed"}
        with self.assertRaisesRegex(ValueError, "Source context"):
            generate_repair(f.profile, self.task, self.seed, f.context)
