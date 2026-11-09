"""Prove the GitHub-run CLI cannot select work or emit mutation requests."""
from __future__ import annotations

import contextlib
import io
import json
import os
from unittest import TestCase
from unittest.mock import patch

from chatgpt_operation.controller import scoped_wake_native as native

from test_scoped_wake_native import HEAD, REPO, NativeFake, scope


class FakeTransport(NativeFake):
    instances = []

    def __init__(self, repository, token):
        if token != "dummy-test-token":
            raise AssertionError("fake credential mismatch")
        self.repository = repository
        super().__init__(config=scope())
        self.instances.append(self)


class ScopedNativeEntrypointTests(TestCase):
    def env(self):
        return {
            "GITHUB_REPOSITORY": REPO,
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_SHA": HEAD,
            "GITHUB_RUN_ID": "8787",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_TOKEN": "dummy-test-token",
        }

    def run_cli(self, environ):
        FakeTransport.instances.clear()
        log = io.StringIO()
        with (
            patch.dict(os.environ, environ, clear=True),
            patch(
                "chatgpt_operation.github.actions_runtime.GitHubActionsTransport",
                FakeTransport,
            ),
            contextlib.redirect_stdout(log),
        ):
            code = native.main([])
        return code, log.getvalue()

    def test_native_canonical_run_previews_only(self):
        result, log = self.run_cli(self.env())
        self.assertEqual(result, 0)
        self.assertIn("SCOPED_BOOTSTRAP=SCOPE_CANDIDATE", log)
        output = json.loads(log.strip().splitlines()[-1])
        self.assertEqual(output["work_id"], "issue:281")
        self.assertFalse(output["dispatch_authorized"])
        self.assertIsNone(output["execution_command"])
        self.assertTrue(FakeTransport.instances[0].calls)

    def test_external_work_id_cannot_be_submitted(self):
        with (
            patch.dict(os.environ, self.env(), clear=True),
            self.assertRaises(SystemExit) as caught,
        ):
            native.main(["--work-id", "issue:256"])
        self.assertEqual(caught.exception.code, 2)

    def test_issue_event_is_blocked_before_native_read(self):
        env = self.env()
        env["GITHUB_EVENT_NAME"] = "issues"
        result, log = self.run_cli(env)
        self.assertEqual(result, 2)
        self.assertIn("BLOCKED_SCOPE", log)
        self.assertFalse(FakeTransport.instances)

    def test_non_main_ref_is_blocked_before_native_read(self):
        env = self.env()
        env["GITHUB_REF"] = "refs/heads/samuel/feature"
        result, _ = self.run_cli(env)
        self.assertEqual(result, 2)
        self.assertFalse(FakeTransport.instances)

    def test_missing_token_is_blocked_before_native_read(self):
        env = self.env()
        env.pop("GITHUB_TOKEN")
        result, _ = self.run_cli(env)
        self.assertEqual(result, 2)
        self.assertFalse(FakeTransport.instances)

    def test_invalid_run_id_is_blocked_before_native_read(self):
        env = self.env()
        env["GITHUB_RUN_ID"] = "not-number"
        result, _ = self.run_cli(env)
        self.assertEqual(result, 2)
        self.assertFalse(FakeTransport.instances)

    def test_unexpected_main_source_is_denied(self):
        env = self.env()
        env["GITHUB_SHA"] = "b" * 40
        result, log = self.run_cli(env)
        self.assertEqual(result, 2)
        self.assertIn("scope source differs", log)
