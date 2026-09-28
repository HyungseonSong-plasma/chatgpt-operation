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


    def test_production_mode_returns_nested_structured_action_plan(self):
        plan = {
            "schema_version":1,
            "research_id":"issue:44",
            "stage":"implement",
            "executor":"github_native",
            "payload":{
                "action":"close_issue",
                "repository":"o/r",
                "target":{"number":43},
                "preconditions":{"issue_state":"open"},
                "desired_postcondition":{"issue_state":"closed"},
            },
            "expected_observation":"issue is closed",
            "decision_risk":None,
        }
        raw = {
            "operation":"analyze",
            "decision_id":"github_execution_authority",
            "compatible_with_locked_decisions":True,
            "revision_requested":False,
            "action_plan":plan,
        }
        seen={}
        def opener(req, timeout):
            seen["body"]=json.loads(req.data.decode())
            return Response({"output_text":json.dumps(raw)})
        provider=OpenAIReasoningProvider(
            "secret",opener=opener,allow_action_plan=True
        )
        result=provider.reason(
            task="next",context={},attempt=1,validation_error=None
        )
        self.assertEqual(result["action_plan"],plan)
        schema=seen["body"]["text"]["format"]["schema"]
        self.assertIn("action_plan",schema["properties"])
        self.assertNotIn("action_plan_json",schema["properties"])
        action_schema=schema["properties"]["action_plan"]
        variants=action_schema["anyOf"]
        self.assertEqual(variants[0],{"type":"null"})
        executable=variants[1:]
        self.assertGreaterEqual(len(executable),9)
        executors={
            item["properties"]["executor"]["enum"][0]
            for item in executable
        }
        self.assertEqual(
            executors,
            {"repository_mutation","github_native"},
        )
        for item in executable:
            self.assertFalse(item["additionalProperties"])
            self.assertEqual(
                item["properties"]["executor"]["enum"],
                [item["properties"]["executor"]["enum"][0]],
            )

    def test_production_mode_preserves_multiline_workflow_content_without_double_encoding(self):
        content=(
            "name: Samuel Weekly Maintenance\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "  schedule:\n"
            "    - cron: '0 8 * * 1-5'\n"
            "jobs:\n"
            "  collect:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: echo \"weekday collection\"\n"
        )
        plan={
            "schema_version":1,
            "research_id":"issue:24",
            "stage":"implement",
            "executor":"repository_mutation",
            "payload":{
                "schema_version":1,
                "repository":"HyungseonSong-plasma/chatgpt-operation",
                "resource":"file",
                "action":"create",
                "target":{
                    "path":".github/workflows/samuel-paul-weekly-maintenance.yml",
                    "branch":"samuel/issues-24-43-weekly-maintenance-v2",
                },
                "expected":{"absent":True},
                "desired":{"content":content},
                "commit_message":"Add scheduled weekly maintenance",
            },
            "expected_observation":"scheduled workflow exists",
            "decision_risk":None,
        }
        raw={
            "operation":"analyze",
            "decision_id":"github_execution_authority",
            "compatible_with_locked_decisions":True,
            "revision_requested":False,
            "action_plan":plan,
        }
        provider=OpenAIReasoningProvider(
            "secret",
            opener=lambda req,timeout:Response({"output_text":json.dumps(raw)}),
            allow_action_plan=True,
        )
        result=provider.reason(
            task="next",context={},attempt=1,validation_error=None
        )
        self.assertEqual(
            result["action_plan"]["payload"]["desired"]["content"],
            content,
        )

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
