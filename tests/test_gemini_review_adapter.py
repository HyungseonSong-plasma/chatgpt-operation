"""Adversarial, credential-free conformance tests for Gemini review transport."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from chatgpt_operation.controller.gemini_review_adapter import (
    ReviewError, main, run_review, safe_failure_code, validate_packet, validate_reply,
)


DIFF = (
    "diff --git a/docs/a.md b/docs/a.md\n"
    "--- a/docs/a.md\n"
    "+++ b/docs/a.md\n"
    "@@ -1 +1 @@\n"
    "-Old evidence label\n"
    "+Unapproved draft\n"
)
HEAD = "a" * 40
BASE = "b" * 40


def packet():
    return {
        "schema_version": 1,
        "repository": "owner/repo",
        "base_sha": BASE,
        "head_sha": HEAD,
        "diff": DIFF,
        "diff_sha256": hashlib.sha256(DIFF.encode()).hexdigest(),
        "changed_paths": ["docs/a.md"],
        "criteria": ["Preserve the original evidence and do not promote the draft."],
    }


def verdict(status="PASS", findings=None):
    return {
        "verdict": status,
        "summary": "Observed bounded change only.",
        "findings": [] if findings is None else findings,
    }


def api_body(status="PASS"):
    return {
        "candidates": [{
            "finishReason": "STOP",
            "content": {"parts": [{"text": json.dumps(verdict(status))}]},
        }],
        "modelVersion": "gemini-test-model",
        "usageMetadata": {"totalTokenCount": 121, "promptTokenCount": 100},
    }


class HTTPResponse:
    def __init__(self, payload):
        self.data = json.dumps(payload).encode()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, n):
        return self.data[:n]


class GeminiReviewTests(unittest.TestCase):
    def test_api_exact_revision_and_digest_bound_not_merge_authority(self):
        observed = {}
        def opener(req, timeout):
            observed["request"] = req
            observed["timeout"] = timeout
            return HTTPResponse(api_body())
        with patch.dict(os.environ, {"GEMINI_API_KEY": "confidential"}, clear=True):
            result = run_review(packet(), backend="api", model="gemini-2.5-flash", opener=opener)
        self.assertEqual(result["status"], "REVIEW_RETURNED")
        self.assertEqual(result["head_sha"], HEAD)
        self.assertEqual(result["diff_sha256"], packet()["diff_sha256"])
        self.assertEqual(result["verdict"]["verdict"], "PASS")
        self.assertFalse(result["mutation_authorized"])
        self.assertFalse(result["merge_authorized"])
        self.assertEqual(result["semantic_acceptance"], "REVIEW_REQUIRED")
        self.assertEqual(result["provenance"]["tokens"]["totalTokenCount"], 121)
        self.assertEqual(observed["timeout"], 90)
        self.assertTrue(observed["request"].full_url.startswith(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:"
        ))
        body = json.loads(observed["request"].data)
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(body["generationConfig"]["maxOutputTokens"], 2048)
        self.assertNotIn("temperature", body["generationConfig"])
        self.assertNotIn("candidateCount", body["generationConfig"])
        self.assertNotIn("topP", body["generationConfig"])
        self.assertNotIn("topK", body["generationConfig"])
        self.assertNotIn("GITHUB_TOKEN", str(body))
        self.assertNotIn("confidential", str(result))

    def test_missing_key_fails_without_network(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ReviewError, "GEMINI_API_KEY missing"):
                run_review(packet(), backend="api", model="gemini-2.5-flash",
                           opener=lambda *args, **kwargs: self.fail("unexpected HTTP"))

    def test_bad_revision_and_digest_fail_before_call(self):
        for patch_packet in (
            {"head_sha": "main"},
            {"base_sha": ""},
            {"diff_sha256": "0" * 64},
            {"repository": "wrong/../repository"},
            {"changed_paths": ["docs/missing.md"]},
            {"changed_paths": ["../docs/a.md"]},
            {"criteria": []},
            {"schema_version": True},
        ):
            p = packet()
            p.update(patch_packet)
            with self.subTest(patch_packet=patch_packet), self.assertRaises(ReviewError):
                validate_packet(p)

    def test_model_injection_and_timeout_rejected_before_transport(self):
        with self.assertRaises(ReviewError):
            run_review(packet(), backend="api", model="gemini-x/../../evil")
        with self.assertRaises(ReviewError):
            run_review(packet(), backend="api", model="gemini-2.5-flash", timeout=0)
        with self.assertRaises(ReviewError):
            run_review(packet(), backend="unknown", model="gemini-2.5-flash")

    def test_oversized_diff_rejected(self):
        p = packet()
        p["diff"] += "+" + "x" * 200_000 + "\n"
        p["diff_sha256"] = hashlib.sha256(p["diff"].encode()).hexdigest()
        with self.assertRaisesRegex(ReviewError, "diff exceeds limit"):
            validate_packet(p)

    def test_evidence_quote_required_and_path_restricted(self):
        f = {
            "severity": "MAJOR", "path": "docs/a.md", "line": 4,
            "evidence": "+Unapproved draft", "explanation": "Changes review authority.",
        }
        self.assertEqual(validate_reply(verdict("REQUEST_CHANGES", [f]), packet())["verdict"],
                         "REQUEST_CHANGES")
        for bad in (
            {**f, "path": "secrets.txt"},
            {**f, "evidence": "invisible undisclosed fact"},
            {**f, "line": True},
            {**f, "severity": "FAKE"},
        ):
            with self.subTest(bad=bad), self.assertRaises(ReviewError):
                validate_reply(verdict("REQUEST_CHANGES", [bad]), packet())
        with self.assertRaisesRegex(ReviewError, "PASS conflicts"):
            validate_reply(verdict("PASS", [f]), packet())
        with self.assertRaisesRegex(ReviewError, "lack evidence"):
            validate_reply(verdict("REQUEST_CHANGES"), packet())

    def test_dropped_or_malformed_model_response_fails_closed(self):
        cases = [
            {"candidates": []},
            {"candidates": [{**api_body()["candidates"][0], "finishReason": "MAX_TOKENS"}]},
            {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "not json"}]}}]},
            {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": '"PASS"'}]}}]},
            {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": '{"verdict":"PASS"}'}]}}]},
        ]
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test"}, clear=True):
            for data in cases:
                with self.subTest(data=data), self.assertRaises(ReviewError):
                    run_review(packet(), backend="api", model="gemini-2.5-flash",
                               opener=lambda req, timeout: HTTPResponse(data))

    def test_api_http_error_is_classified_without_body_or_token(self):
        def failed(req, timeout):
            raise HTTPError(req.full_url, 429, "some-secret", {}, io.BytesIO(b"token=very-secret"))
        with patch.dict(os.environ, {"GEMINI_API_KEY": "very-secret"}, clear=True):
            with self.assertRaises(ReviewError) as ctx:
                run_review(packet(), backend="api", model="gemini-2.5-flash", opener=failed)
        self.assertIn("429", str(ctx.exception))
        self.assertNotIn("secret", str(ctx.exception))

    def test_safe_failure_codes_never_include_sensitive_provider_text(self):
        examples = (
            ("Gemini API HTTP status 400", "API_HTTP_400"),
            ("Gemini API HTTP status 403", "API_HTTP_403"),
            ("Gemini API HTTP status 429", "API_HTTP_429"),
            ("Gemini API transport failure: URLError", "API_TRANSPORT_ERROR"),
            ("GEMINI_API_KEY missing", "API_KEY_MISSING"),
            ("Gemini response did not finish normally", "GENERATION_INCOMPLETE"),
            ("Gemini returned no single text response", "MODEL_CONTENT_INVALID"),
            ("model response is not JSON", "MODEL_JSON_INVALID"),
            ("invalid Gemini review response fields", "REVIEW_SCHEMA_INVALID"),
            ("unknown token=very-secret", "UNKNOWN_FAILURE"),
            ("Gemini API HTTP status 403 secret=very-secret", "UNKNOWN_FAILURE"),
        )
        for failure, expected in examples:
            with self.subTest(failure=failure):
                code = safe_failure_code(ReviewError(failure))
                self.assertEqual(code, expected)
                self.assertNotIn("secret", code)

    def test_adapter_persists_only_sanitized_failure_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "packet.json"
            output = Path(tmp) / "result.json"
            p.write_text(json.dumps(packet()), encoding="utf-8")
            with patch("chatgpt_operation.controller.gemini_review_adapter.run_review",
                       side_effect=ReviewError("Gemini API HTTP status 429")):
                rc = main([
                    "--input", str(p), "--output", str(output),
                    "--backend", "api", "--model", "gemini-3.8-flash",
                ])
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(rc, 2)
            self.assertEqual(result["status"], "UNKNOWN")
            self.assertEqual(result["failure_code"], "API_HTTP_429")
            self.assertFalse(result["merge_authorized"])
            self.assertFalse(result["mutation_authorized"])

    def test_cli_is_opt_in_and_does_not_receive_github_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ReviewError, "attested sandbox"):
                run_review(packet(), backend="cli", model="gemini-2.5-flash",
                           runner=lambda *args, **kw: self.fail("untrusted CLI should not run"))
        observations = {}
        def runner(args, **kwargs):
            observations["args"] = args
            observations["env"] = kwargs["env"]
            observations["cwd"] = kwargs["cwd"]
            observations["input"] = kwargs["input"]
            return subprocess.CompletedProcess(args, 0, json.dumps({
                "response": json.dumps(verdict()), "stats": {},
            }), "")
        with patch.dict(os.environ, {
            "SAMUEL_GEMINI_CLI_SANDBOX": "1",
            "GITHUB_TOKEN": "must-not-pass",
            "GEMINI_API_KEY": "gemini-only",
            "PATH": "/usr/bin",
        }, clear=True):
            result = run_review(packet(), backend="cli", model="gemini-2.5-flash", runner=runner)
        self.assertEqual(result["status"], "REVIEW_RETURNED")
        self.assertEqual(observations["env"]["GEMINI_API_KEY"], "gemini-only")
        self.assertNotIn("GITHUB_TOKEN", observations["env"])
        self.assertEqual(observations["env"]["HOME"], observations["cwd"])
        self.assertIn("--approval-mode", observations["args"])
        self.assertNotIn("must-not-pass", str(observations))
        self.assertIn("UNTRUSTED SOURCE DATA", observations["input"])

    def test_cli_nonzero_and_timeout_never_promote_success(self):
        with patch.dict(os.environ, {"SAMUEL_GEMINI_CLI_SANDBOX": "1"}, clear=True):
            with self.assertRaisesRegex(ReviewError, "nonzero"):
                run_review(packet(), backend="cli", model="gemini-2.5-flash",
                           runner=lambda args, **kw: subprocess.CompletedProcess(args, 53, "", "private"))
            def timeout(args, **kwargs):
                raise subprocess.TimeoutExpired(args, 90)
            with self.assertRaisesRegex(ReviewError, "TimeoutExpired"):
                run_review(packet(), backend="cli", model="gemini-2.5-flash", runner=timeout)

    def test_cli_program_writes_unknown_on_missing_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "input.json"
            o = Path(tmp) / "output.json"
            p.write_text(json.dumps(packet()), encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                code = main(["--input", str(p), "--output", str(o),
                             "--backend", "api", "--model", "gemini-2.5-flash"])
            self.assertEqual(code, 2)
            result = json.loads(o.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "UNKNOWN")
            self.assertFalse(result["merge_authorized"])


if __name__ == "__main__":
    unittest.main()
