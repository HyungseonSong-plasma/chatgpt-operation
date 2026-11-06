"""Regression contract for agent-neutral Samuel mutation branch namespaces."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from chatgpt_operation.repository.mutation import (
    ManifestError,
    PolicyError,
    authorize_manifest,
    parse_manifest,
    parse_policy,
)


REPO = "HyungseonSong-plasma/chatgpt-operation"
POLICY_FILE = Path("automation/samuel/repository-mutation-policy.json")
SOURCE_SHA = "a" * 40


def create_branch_manifest(name: str):
    return parse_manifest({
        "schema_version": 1,
        "repository": REPO,
        "resource": "branch",
        "action": "create",
        "target": {"name": name},
        "expected": {"absent": True},
        "desired": {"sha": SOURCE_SHA},
    })


def update_file_manifest(branch: str, path: str = "docs/README.md"):
    return parse_manifest({
        "schema_version": 1,
        "repository": REPO,
        "resource": "file",
        "action": "update",
        "target": {"path": path, "branch": branch},
        "expected": {"sha": SOURCE_SHA},
        "desired": {"content": "safe text"},
        "commit_message": "test policy",
    })


class AgentBranchNamespacePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
        cls.policy = parse_policy(cls.source)

    def test_exact_transitional_allowlist(self):
        self.assertEqual(self.policy.repository, REPO)
        self.assertEqual(self.policy.branch_allow, ("agent/*", "samuel/*", "issue-*"))
        self.assertEqual(self.policy.branch_deny, ("main",))

    def test_new_agent_names_are_allowed_for_branch_creation_and_file_update(self):
        for name in ("agent/251-doc-qa", "agent/246-dea-evaluation", "agent/team/subtask"):
            with self.subTest(name=name):
                authorize_manifest(create_branch_manifest(name), policy=self.policy, repository=REPO)
                authorize_manifest(update_file_manifest(name), policy=self.policy, repository=REPO)

    def test_legacy_samuel_and_issue_branches_still_work(self):
        for name in ("samuel/document-status-qa-251", "samuel/dea-v01-readonly-replay-246", "issue-251-fix"):
            with self.subTest(name=name):
                authorize_manifest(create_branch_manifest(name), policy=self.policy, repository=REPO)
                authorize_manifest(update_file_manifest(name), policy=self.policy, repository=REPO)

    def test_unapproved_prefixes_and_main_are_denied_for_create_and_update(self):
        for name in ("feat/new-feature", "fix/quick-change", "david/new-task", "main"):
            with self.subTest(name=name):
                for manifest in (create_branch_manifest(name), update_file_manifest(name)):
                    with self.assertRaises(PolicyError):
                        authorize_manifest(manifest, policy=self.policy, repository=REPO)

    def test_invalid_branch_syntax_is_rejected_by_manifest_parser(self):
        for name in ("agent/", "agent//nested", "agent/../main", "/agent/test"):
            with self.subTest(name=name), self.assertRaises(ManifestError):
                create_branch_manifest(name)

    def test_privileged_policy_file_remains_explicitly_denied(self):
        path = "automation/samuel/repository-mutation-policy.json"
        self.assertIn(path, self.policy.file_deny)
        with self.assertRaisesRegex(PolicyError, "file path denied"):
            authorize_manifest(
                update_file_manifest("agent/251-doc-qa", path),
                policy=self.policy, repository=REPO,
            )

    def test_main_deny_and_workflow_write_restriction_unchanged(self):
        """Repository-native writes remain impossible even with a scoped path policy.

        Issue #254 permits a separately authorized external *Draft PR* route
        only after a trusted pre-write gate is deployed. It does NOT grant
        repository-native Actions any workflow-file write authority.
        """
        self.assertEqual(self.policy.branch_deny, ("main",))
        workflow_allows = [
            p for p in self.policy.file_allow
            if p.startswith(".github/workflows/")
        ]
        self.assertIn(
            workflow_allows,
            ([], [".github/workflows/dea-evidence-producer.yml"]),
        )
        if ".github/workflows/**" not in self.policy.file_deny:
            # Any new exception must be EXACTLY the DEA path; never a
            # workflow wildcard or the Samuel execution workflows.
            self.assertEqual(
                workflow_allows,
                [".github/workflows/dea-evidence-producer.yml"],
            )
        for path in (
            ".github/workflows/ci.yml",
            ".github/workflows/samuel-native-github.yml",
            ".github/workflows/dea-evidence-producer.yml",
        ):
            with self.subTest(path=path):
                with self.assertRaisesRegex(
                    PolicyError, "workflow file mutation"
                ):
                    authorize_manifest(
                        update_file_manifest("agent/251-doc-qa", path),
                        policy=self.policy, repository=REPO,
                    )


if __name__ == "__main__":
    unittest.main()
