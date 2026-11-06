"""Regression checks for the pre-provider branch-name gate."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from chatgpt_operation.repository.branch_preflight import main, require_allowed_branch
from chatgpt_operation.repository.mutation import PolicyError


class BranchPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "policy.json"
        self.policy = {
            "schema_version": 1,
            "repository": "owner/samuel",
            "mutation": {
                "allow": {"file": ["create", "update", "delete"], "branch": ["create"]},
                "file_paths": {"allow": ["src/**", "tests/**", "skills/**"], "deny": []},
                "branch_names": {"allow": ["samuel/*", "issue-*"], "deny": ["main"]},
            },
            "validation_gate": {"mode": "named_workflows", "workflows": ["CI"], "ignore_current_run": True},
        }
        self.write_policy()

    def write_policy(self) -> None:
        self.path.write_text(json.dumps(self.policy), encoding="utf-8")

    def check(self, branch: str, repository: str = "owner/samuel") -> str:
        return require_allowed_branch(repository=repository, branch=branch, policy_path=self.path)

    def test_allowed_samuel_branch(self):
        self.assertEqual(self.check("samuel/docs-qa-251"), "samuel/docs-qa-251")

    def test_allowed_issue_branch(self):
        self.assertEqual(self.check("issue-251-branch-policy"), "issue-251-branch-policy")

    def test_feat_branch_denied_before_provider(self):
        with self.assertRaisesRegex(PolicyError, "branch name denied"):
            self.check("feat/document-consistency-badges-v01-20261105")

    def test_default_branch_denied(self):
        with self.assertRaises(PolicyError):
            self.check("main")

    def test_invalid_branch_syntax_denied(self):
        for branch in ("samuel/../main", "/samuel/docs", "samuel//docs", "samuel/docs/"):
            with self.subTest(branch=branch), self.assertRaises(PolicyError):
                self.check(branch)

    def test_repository_mismatch_denied(self):
        with self.assertRaisesRegex(PolicyError, "repository binding"):
            self.check("samuel/docs", repository="owner/other")

    def test_missing_policy_fails_closed(self):
        self.path.unlink()
        with self.assertRaisesRegex(PolicyError, "unavailable"):
            self.check("samuel/docs")

    def test_malformed_policy_fails_closed(self):
        self.path.write_text("{not-json", encoding="utf-8")
        with self.assertRaises(PolicyError):
            self.check("samuel/docs")

    def test_policy_changes_are_not_ignored(self):
        self.policy["mutation"]["branch_names"]["deny"].append("samuel/docs-*")
        self.write_policy()
        with self.assertRaises(PolicyError):
            self.check("samuel/docs-qa-251")
        self.assertEqual(self.check("samuel/other"), "samuel/other")

    def test_cli_denies_without_provider_calls(self):
        output = StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            exit_code = main(["--repository", "owner/samuel", "--branch", "feat/forbidden", "--policy", str(self.path)])
        self.assertEqual(exit_code, 2)
        self.assertIn("DENIED", output.getvalue())

    def test_cli_accepts_authorized_branch(self):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(["--repository", "owner/samuel", "--branch", "samuel/allowed", "--policy", str(self.path)])
        self.assertEqual(exit_code, 0)
        self.assertIn("ALLOWED", output.getvalue())


if __name__ == "__main__":
    unittest.main()
