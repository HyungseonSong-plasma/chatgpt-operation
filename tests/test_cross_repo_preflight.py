"""#220 cross-repository scope and dispatch policy adversarial conformance."""
import copy
import unittest

from chatgpt_operation.controller.cross_repo_preflight import (
    compile_codeqa_preflight, CrossRepoPreflightError,
)


def issue(repo, number):
    return {"number": number, "state": "open",
            "url": f"https://api.github.com/repos/{repo}/issues/{number}"}


class CrossRepoPreflightTests(unittest.TestCase):
    def setUp(self):
        self.policy = {
            "schema_version": 1,
            "policy_id": "samuel-codeqa-issue92-readonly-preflight-v1",
            "source_repository": "HyungseonSong-plasma/chatgpt-operation",
            "source_issue": 220,
            "target_repository": "HyungseonSong-plasma/codeQA",
            "target_issue": 92,
            "work_id": "github:HyungseonSong-plasma/codeQA:issue:92",
            "workflow": "samuel-crossrepo-preflight.yml",
            "ref": "main", "approved_actors": ["HyungseonSong-plasma"],
            "operations": ["READ_ONLY_PREFLIGHT_DISPATCH"],
            "target_issue_write": False, "target_pr_create": False,
            "target_merge": False,
            "authorization": "EXPLICIT_USER_TASK_DIRECTED_READONLY_PREFLIGHT",
            "credential_name": "SAMUEL_CODEQA_DISPATCH_TOKEN",
            "credential_scope": "target_actions_write_only",
            "owner_controlled_secret": True,
        }
        self.args = {
            "source_issue": issue("HyungseonSong-plasma/chatgpt-operation", 220),
            "target_issue": issue("HyungseonSong-plasma/codeQA", 92),
            "observed_source_sha": "a" * 40,
            "observed_target_sha": "b" * 40,
            "expected_source_sha": "a" * 40,
            "expected_target_sha": "b" * 40,
            "actor": "HyungseonSong-plasma",
            "source_run_id": "100",
        }

    def plan(self):
        return compile_codeqa_preflight(self.policy, **self.args)

    def test_valid_explicit_read_only_source_target_binding(self):
        result = self.plan()
        self.assertEqual(result.status, "READY_FOR_READ_ONLY_DISPATCH")
        self.assertEqual(result.mutation_scope, "NONE")
        self.assertEqual(result.target_issue, 92)
        self.assertIn("codeQA:issue:92", result.work_id)
        self.assertEqual(len(result.preflight_identity), 64)

    def test_wrong_repo_and_ambiguous_work_id_blocked(self):
        for key, val in (("target_repository", "HyungseonSong-plasma/chatgpt-operation"),
                         ("work_id", "issue:92"), ("target_issue", 220),
                         ("target_workflow", "test.yml")):
            changed = copy.deepcopy(self.policy)
            changed["workflow" if key == "target_workflow" else key] = val
            with self.subTest(key=key), self.assertRaises(CrossRepoPreflightError):
                compile_codeqa_preflight(changed, **self.args)

    def test_no_implicit_write_or_merge_authorization(self):
        for key, val in (("target_issue_write", True), ("target_pr_create", True),
                         ("target_merge", True),
                         ("operations", ["READ_ONLY_PREFLIGHT_DISPATCH", "CREATE_PR"]),
                         ("credential_scope", "contents_write")):
            changed = copy.deepcopy(self.policy)
            changed[key] = val
            with self.subTest(key=key), self.assertRaises(CrossRepoPreflightError):
                compile_codeqa_preflight(changed, **self.args)

    def test_source_issue_and_target_issue_are_independently_pinned(self):
        for field in ("source_issue", "target_issue"):
            changed = copy.deepcopy(self.args)
            changed[field]["state"] = "closed"
            with self.subTest(field=field), self.assertRaises(CrossRepoPreflightError):
                compile_codeqa_preflight(self.policy, **changed)
            changed = copy.deepcopy(self.args)
            changed[field]["url"] = "https://api.github.com/repos/wrong/repo/issues/92"
            with self.subTest(field=field + ":url"), self.assertRaises(CrossRepoPreflightError):
                compile_codeqa_preflight(self.policy, **changed)

    def test_sha_changes_and_unapproved_actor_blocked(self):
        for key, val in (
            ("expected_source_sha", "c" * 40),
            ("expected_target_sha", "d" * 40),
            ("observed_target_sha", ""),
            ("actor", "unapproved-ci-bot"),
            ("source_run_id", "0"),
        ):
            changed = dict(self.args)
            changed[key] = val
            with self.subTest(key=key), self.assertRaises(CrossRepoPreflightError):
                compile_codeqa_preflight(self.policy, **changed)

    def test_deterministic_no_mutation_plan(self):
        self.assertEqual(self.plan(), self.plan())


if __name__ == "__main__":
    unittest.main()
