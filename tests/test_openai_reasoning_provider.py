import io
import json
import os
import unittest
from unittest.mock import patch

from chatgpt_operation.controller.openai_reasoning_provider import (
    DEFAULT_MODEL, OpenAIReasoningProvider,
)
from chatgpt_operation.controller.reasoning_provider import ProviderUnavailable


class Response:
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return json.dumps(self.payload).encode()


class OpenAIReasoningProviderTests(unittest.TestCase):
    def test_missing_key_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ProviderUnavailable):
                OpenAIReasoningProvider.from_env()

    def test_default_model_is_luna(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}, clear=True):
            self.assertEqual(OpenAIReasoningProvider.from_env().model, DEFAULT_MODEL)

    def test_returns_json_object_only(self):
        raw = {
            "operation": "analyze",
            "decision_id": "github_execution_authority",
            "compatible_with_locked_decisions": True,
            "revision_requested": False,
            "action_plan": None,
        }
        seen = {}
        def opener(req, timeout):
            seen["authorization"] = req.headers["Authorization"]
            seen["url"] = req.full_url
            seen["body"] = json.loads(req.data.decode())
            return Response({"output_text": json.dumps(raw)})
        p = OpenAIReasoningProvider("secret", opener=opener)
        self.assertEqual(p.reason(task="x", context={}, attempt=1, validation_error=None), raw)
        self.assertEqual(seen["authorization"], "Bearer secret")
        self.assertTrue(seen["url"].endswith("/responses"))
        fmt = seen["body"]["text"]["format"]
        self.assertEqual(fmt["type"], "json_schema")
        self.assertTrue(fmt["strict"])
        schema = fmt["schema"]
        self.assertEqual(set(schema["required"]), set(schema["properties"]))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["action_plan"]["type"], "null")

    def test_non_json_fails_closed(self):
        p = OpenAIReasoningProvider(
            "secret", opener=lambda req, timeout: Response({"output_text": "not-json"})
        )
        with self.assertRaises(ProviderUnavailable):
            p.reason(task="x", context={}, attempt=1, validation_error=None)


if __name__ == "__main__":
    unittest.main()


class ShadowStructuredOutputContractTests(unittest.TestCase):
    def test_shadow_schema_forbids_executable_action_plan(self):
        from chatgpt_operation.controller.openai_reasoning_provider import ISSUE_REASONING_SCHEMA
        self.assertEqual(ISSUE_REASONING_SCHEMA["properties"]["action_plan"], {"type": "null"})
