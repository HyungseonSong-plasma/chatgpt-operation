"""Offline contract tests for the no-mutation Production Schema A/B runner."""
import io
import json
import unittest
from urllib import error

from chatgpt_operation.controller.openai_reasoning_provider import (
    OpenAIReasoningProvider,
)
from chatgpt_operation.controller.reasoning_context_ab import (
    CASES, TASK, classify, context_for, run_ab, run_case, schema_digest,
)


_RESPONSE = {
    "operation": "analyze",
    "decision_id": None,
    "compatible_with_locked_decisions": True,
    "revision_requested": False,
    "action_plan": None,
    "blocker": None,
    "progress": None,
    "completion_claim": None,
}


class FakeProvider:
    model = "gpt-5.6-luna"
    allow_action_plan = True

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def reason(self, **kwargs):
        self.calls.append(kwargs)
        is_delete = "deletion" in kwargs["context"]["goal"]
        key = "B" if is_delete else "A"
        outcome = self.responses.get(key, _RESPONSE)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class ReasoningContextABTests(unittest.TestCase):
    def test_two_cases_have_identical_fixed_context_and_task(self):
        a, b = (context_for(c) for c in CASES)
        self.assertNotEqual(a["goal"], b["goal"])
        self.assertNotEqual(a["observations"], b["observations"])
        for k in ("goal", "observations"):
            a.pop(k)
            b.pop(k)
        self.assertEqual(a, b)
        self.assertEqual(len(TASK) > 0, True)

    def test_requests_same_schema_with_no_execution(self):
        calls = []
        def opener(req, timeout):
            body = json.loads(req.data.decode("utf-8"))
            calls.append(body)
            class Response:
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    return False
                def read(self):
                    return json.dumps({"output_text": json.dumps(_RESPONSE)}).encode()
            return Response()

        provider = OpenAIReasoningProvider(
            "fake-secret", model="gpt-5.6-luna", allow_action_plan=True,
            opener=opener,
        )
        result = run_ab(provider)
        self.assertEqual(result["comparison"], "both_typed_responses")
        self.assertFalse(result["mutation_executed"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["model"], calls[1]["model"])
        self.assertEqual(
            calls[0]["text"]["format"]["schema"],
            calls[1]["text"]["format"]["schema"],
        )
        self.assertEqual(
            calls[0]["text"]["format"]["type"], "json_schema",
        )
        self.assertTrue(calls[0]["text"]["format"]["strict"])
        self.assertEqual(len(result["production_schema_sha256"]), 64)
        self.assertEqual(schema_digest(), result["production_schema_sha256"])
        self.assertNotEqual(
            result["case_results"][0]["request_context_sha256"],
            result["case_results"][1]["request_context_sha256"],
        )

    def test_expected_action_plan_is_discarded_not_dispatched(self):
        provider = FakeProvider({
            "B": {**_RESPONSE, "action_plan": {"executor": "github_native"}},
        })
        result = run_ab(provider)
        self.assertEqual(result["comparison"], "both_typed_responses")
        self.assertTrue(result["case_results"][1]["action_plan_present"])
        self.assertFalse(result["mutation_executed"])
        self.assertNotIn("action_plan", json.dumps(result))
        self.assertEqual(len(provider.calls), 2)

    def test_http_failure_is_sanitized_and_context_attributed(self):
        fail = error.HTTPError(
            "https://api.openai.com/v1/responses", 400, "bad request", {},
            io.BytesIO(json.dumps({
                "error": {
                    "type": "invalid_request_error",
                    "code": "unsupported_response_format",
                    "message": "private upstream detail that must not be logged",
                }
            }).encode()),
        )
        def opener(req, timeout):
            prompt = json.loads(json.loads(req.data)["input"])
            if "deletion" in prompt["reasoning_context"]["goal"]:
                raise fail
            class Response:
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    return False
                def read(self):
                    return json.dumps({"output_text": json.dumps(_RESPONSE)}).encode()
            return Response()

        provider = OpenAIReasoningProvider(
            "fake-secret", model="gpt-5.6-luna",
            allow_action_plan=True, opener=opener,
        )
        result = run_ab(provider)
        self.assertEqual(result["comparison"], "delete_context_only_failure")
        err = result["case_results"][1]
        self.assertEqual(err["http_status"], 400)
        self.assertEqual(err["provider_code"], "unsupported_response_format")
        self.assertNotIn("private upstream detail", json.dumps(result))
        self.assertNotIn("fake-secret", json.dumps(result))

    def test_never_infers_provider_success_from_http_failure(self):
        provider = FakeProvider()
        both = run_ab(provider)
        self.assertEqual(both["comparison"], "both_typed_responses")
        self.assertEqual(
            classify([
                {"outcome": "http_or_network_failure", "failure_kind": "bad_request",
                 "http_status": 400, "provider_code": "x"},
                {"outcome": "http_or_network_failure", "failure_kind": "bad_request",
                 "http_status": 400, "provider_code": "x"},
            ]),
            "shared_failure_signature",
        )

    def test_production_schema_required(self):
        provider = FakeProvider()
        provider.allow_action_plan = False
        with self.assertRaises(ValueError):
            run_ab(provider)


if __name__ == "__main__":
    unittest.main()
