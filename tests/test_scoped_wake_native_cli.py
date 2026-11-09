"""Prove the GitHub-run CLI cannot select work or emit mutation requests."""
from __future__ import annotations

import contextlib
import io
import json
import os
from unittest import TestCase
from unittest.mock import patch

from chatgpt_operation.controller import scoped_wake_native as native

from chatgpt_operation.controller.issue_ingestion import encode_admission_ledger
import base64
import copy

HEAD = "a" * 40
REPO = "HyungseonSong-plasma/chatgpt-operation"
POLICY_PATH = "automation/samuel/agent-child-scoped-preview-281.json"


class FakeTransport:
    """Independent API-port fixture for both unit and function test runners."""

    instances = []

    def __init__(self, repository, token):
        if token != "dummy-test-token":
            raise AssertionError("fake credential mismatch")
        self.repository = repository
        self.calls = []
        self.instances.append(self)

    def get(self, path, *, query=None):
        self.calls.append((path, query))
        if path == "/actions/runs/8787":
            return {
                "id": 8787, "run_attempt": 1, "event": "workflow_dispatch",
                "path": ".github/workflows/samuel-bootstrap.yml",
                "head_branch": "main", "head_sha": HEAD,
                "status": "in_progress", "conclusion": None,
                "repository": {"full_name": REPO},
            }
        if path == "/branches/main":
            return {"commit": {"sha": HEAD}}
        if path == "/contents/" + POLICY_PATH:
            if query != {"ref": HEAD}:
                raise AssertionError("scope file not exact HEAD")
            policy = {
                "schema_version": 1, "repository": REPO,
                "workflow": "samuel-bootstrap.yml", "ref": "main",
                "work_id": "issue:281", "mode": "preview_only",
                "enabled": True,
            }
            return {
                "type": "file", "path": POLICY_PATH,
                "encoding": "base64",
                "content": base64.b64encode(
                    json.dumps(policy).encode("utf-8")
                ).decode("ascii"),
            }
        if path == "/issues":
            return [{
                "id": 5281, "number": 281, "state": "open",
                "title": "Samuel task 281", "body": "Approved implementation 281",
                "labels": [{"name": "samuel"}],
                "html_url": f"https://github.com/{REPO}/issues/281",
            }]
        if path == "/issues/44/comments":
            admitted = {
                "work_id": "issue:281", "issue_number": 281,
                "status": "admitted", "title": "Samuel task 281",
                "body": "Approved implementation 281",
                "html_url": f"https://github.com/{REPO}/issues/281",
            }
            return [{
                "id": 110,
                "body": encode_admission_ledger({"issue:281": admitted}),
            }]
        raise AssertionError("unexpected native GET " + path)


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
