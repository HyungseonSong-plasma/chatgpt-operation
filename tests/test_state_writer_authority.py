"""Qualification for exclusive managed Issue #44 writer and #220 compatibility."""
from __future__ import annotations

import copy
import unittest
from pathlib import Path

from chatgpt_operation.controller.state_writer_authority import (
    REPOSITORY, StateWriterAuthorityError, require_bootstrap_state_writer,
)
from chatgpt_operation.controller.scoped_issue_write import (
    ScopedIssueWriteError, needs_source_comment_ownership_lookup,
    require_source_review_ledger_write,
)


def env():
    return {
        "GITHUB_ACTIONS": "true",
        "GITHUB_WORKFLOW": "Samuel Bootstrap",
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_JOB": "wake",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_RUN_ID": "12345",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SHA": "a" * 40,
    }


def run():
    return {
        "id": 12345,
        "run_attempt": 1,
        "repository": {"full_name": REPOSITORY},
        "path": ".github/workflows/samuel-bootstrap.yml",
        "event": "workflow_dispatch",
        "head_sha": "a" * 40,
        "head_branch": "main",
        "status": "in_progress",
    }


class Reader:
    def __init__(self, value):
        self.value = value
        self.calls = []

    def get(self, path, *, query=None):
        self.calls.append(path)
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class AuthorityTests(unittest.TestCase):
    def test_current_authentic_bootstrap_run_may_write_only_managed_ledger(self):
        reader = Reader(run())
        require_bootstrap_state_writer(
            repository=REPOSITORY, issue_number=44,
            environment=env(), transport=reader,
        )
        self.assertEqual(reader.calls, ["/actions/runs/12345"])

    def test_labeled_issue_wake_may_write_when_live_run_attests_origin(self):
        environment = env()
        environment["GITHUB_EVENT_NAME"] = "issues"
        observed = run()
        observed["event"] = "issues"
        require_bootstrap_state_writer(
            repository=REPOSITORY, issue_number=44,
            environment=environment, transport=Reader(observed),
        )

    def test_forged_environment_or_untrusted_job_is_refused_before_get(self):
        for field, value in (
            ("GITHUB_WORKFLOW", "Samuel Native GitHub Executor"),
            ("GITHUB_REF", "refs/heads/feature"),
            ("GITHUB_JOB", "execute"),
            ("GITHUB_ACTIONS", "false"),
            ("GITHUB_REPOSITORY", "other/repo"),
            ("GITHUB_RUN_ID", "0"),
            ("GITHUB_RUN_ATTEMPT", "abc"),
            ("GITHUB_SHA", "bad"),
        ):
            with self.subTest(field=field):
                environment = env()
                environment[field] = value
                reader = Reader(run())
                with self.assertRaisesRegex(
                    StateWriterAuthorityError, "only current mainline",
                ):
                    require_bootstrap_state_writer(
                        repository=REPOSITORY, issue_number=44,
                        environment=environment, transport=reader,
                    )
                self.assertEqual(reader.calls, [])

    def test_authenticated_github_run_metadata_cannot_be_substituted(self):
        cases = (
            ("id", 12346), ("run_attempt", 2),
            ("repository", {"full_name": "other/repo"}),
            ("path", ".github/workflows/samuel-native-github.yml"),
            ("event", "pull_request"), ("head_sha", "b" * 40),
            ("head_branch", "feature"), ("status", "completed"),
        )
        for field, value in cases:
            with self.subTest(field=field):
                observed = run()
                observed[field] = value
                with self.assertRaisesRegex(
                    StateWriterAuthorityError, "not the trusted Bootstrap",
                ):
                    require_bootstrap_state_writer(
                        repository=REPOSITORY, issue_number=44,
                        environment=env(), transport=Reader(observed),
                    )

    def test_failed_authenticated_lookup_fails_closed(self):
        with self.assertRaisesRegex(
            StateWriterAuthorityError, "run lookup failed",
        ):
            require_bootstrap_state_writer(
                repository=REPOSITORY, issue_number=44,
                environment=env(), transport=Reader(RuntimeError("API denied")),
            )

    def test_other_issues_not_subject_to_issue44_bootstrap_gate(self):
        reader = Reader(None)
        require_bootstrap_state_writer(
            repository=REPOSITORY, issue_number=220,
            environment={}, transport=reader,
        )
        self.assertEqual(reader.calls, [])


class WorkflowPrivilegeInventoryTests(unittest.TestCase):
    def test_existing_issues_write_workflows_are_explicitly_allowlisted(self):
        expected = {
            "samuel-bootstrap.yml",
            "samuel-native-github.yml",
            "samuel-codeqa-foreign-cycle.yml",
            "samuel-chatgpt-proposal-ingress.yml",
        }
        observed = set()
        for path in sorted(Path(".github/workflows").glob("*.yml")):
            content = path.read_text(encoding="utf-8")
            if "issues: write" in content.splitlines():
                observed.add(path.name)
            if path.name != "samuel-bootstrap.yml":
                self.assertNotIn("controller persist-state", content)
        self.assertEqual(observed, expected)

    def test_raw_rest_issue_writers_use_scope_guard_or_bootstrap(self):
        foreign = Path(".github/scripts/samuel_codeqa_foreign_cycle.py").read_text(
            encoding="utf-8"
        )
        ingress = Path(".github/scripts/samuel_chatgpt_proposal_ingress.py").read_text(
            encoding="utf-8"
        )
        shared = Path(".github/scripts/codeqa_governed_write.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("from codeqa_governed_write import API", foreign)
        self.assertIn("from codeqa_governed_write import API", ingress)
        self.assertIn("require_source_review_ledger_write(", shared)
        self.assertIn("needs_source_comment_ownership_lookup(", shared)


class ScopedSourceIssueWriteTests(unittest.TestCase):
    PREFIX = f"/repos/{REPOSITORY}/issues/"

    def test_issue220_comment_create_remains_supported(self):
        require_source_review_ledger_write(
            "POST", self.PREFIX + "220/comments",
        )

    def test_issue44_write_and_other_source_issue_mutations_denied(self):
        cases = (
            ("POST", self.PREFIX + "44/comments"),
            ("PATCH", self.PREFIX + "44"),
            ("POST", self.PREFIX + "267/comments"),
            ("DELETE", self.PREFIX + "220"),
        )
        for method, path in cases:
            with self.subTest(method=method, path=path):
                with self.assertRaisesRegex(
                    ScopedIssueWriteError, "limited to Issue #220",
                ):
                    require_source_review_ledger_write(method, path)

    def test_comment_id_patch_only_when_live_comment_belongs_to_220(self):
        path = self.PREFIX + "comments/6737051665"
        self.assertTrue(needs_source_comment_ownership_lookup("PATCH", path))
        with self.assertRaisesRegex(ScopedIssueWriteError, "verified Issue #220"):
            require_source_review_ledger_write("PATCH", path)
        with self.assertRaisesRegex(ScopedIssueWriteError, "verified Issue #220"):
            require_source_review_ledger_write(
                "PATCH", path,
                current_comment={
                    "id": 6737051665,
                    "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/44",
                },
            )
        require_source_review_ledger_write(
            "PATCH", path,
            current_comment={
                "id": 6737051665,
                "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/220",
            },
        )

    def test_source_get_and_unrelated_target_repo_mutation_remain_available(self):
        require_source_review_ledger_write(
            "GET", self.PREFIX + "44/comments",
        )
        require_source_review_ledger_write(
            "POST", "/repos/HyungseonSong-plasma/codeQA/issues/92/comments",
        )


if __name__ == "__main__":
    unittest.main()
