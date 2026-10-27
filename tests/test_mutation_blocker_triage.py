"""Adversarial tests for fail-closed mutation blocker recovery (#236)."""
import unittest
from chatgpt_operation.repository.blocker_triage import (
    BlockerObservation, BlockerSource, RecoveryAction, classify_blocker,
    decide_mutation_continuation, logical_intent_id,
)

REPO = "HyungseonSong-plasma/codeQA"
BRANCH = "feat/93-scoped-parser-integration-20261026"
WORK = "codeQA-93-D1-D2-D4-integration"
PATHS = ("src/codeqa/adapters/cpp_parser_evidence.py", "tests/test_cpp_parser_evidence.py")
IDENTITY = logical_intent_id(repository=REPO, branch=BRANCH, work_id=WORK, paths=PATHS)


def obs(source, provider="github-connector", *, http_status=None, evidence="issue-93-receipt", intent=IDENTITY):
    return BlockerObservation(source, intent, provider, evidence, http_status)


class MutationBlockerTriageTests(unittest.TestCase):
    def test_identity_is_semantic_and_independent_of_api_and_path_order(self):
        self.assertEqual(IDENTITY, logical_intent_id(
            repository=REPO, branch=BRANCH, work_id=WORK, paths=reversed(PATHS)))
        self.assertEqual(len(IDENTITY), 64)

    def test_same_work_cannot_escape_denial_by_changing_branch_or_file_set(self):
        changed = logical_intent_id(
            repository=REPO, branch="feat/93-another-branch",
            work_id=WORK,
            paths=("docs/renamed-evidence.md", "src/codeqa/adapters/rust_parser_evidence.py"),
        )
        self.assertEqual(changed, IDENTITY)
        self.assertNotEqual(
            logical_intent_id(repository=REPO, branch=BRANCH,
                              work_id="genuinely-different-issued-work-id", paths=PATHS),
            IDENTITY,
        )
        blocked = decide_mutation_continuation(
            [obs(BlockerSource.TOOL_SAFETY)], logical_intent_id=changed,
            provider="git-tree")
        self.assertEqual(blocked.action, RecoveryAction.ESCALATE_NO_WRITE)

    def test_safety_denial_blocks_different_provider_and_git_tree(self):
        safety = obs(BlockerSource.TOOL_SAFETY, "contents-api")
        self.assertEqual(classify_blocker(safety).category, "EXTERNAL_SAFETY_DENIAL")
        for alternative in ("git-tree", "repository-native", "git-push", "contents-api"):
            with self.subTest(alternative=alternative):
                verdict = decide_mutation_continuation([safety], logical_intent_id=IDENTITY,
                                                       provider=alternative)
                self.assertEqual(verdict.action, RecoveryAction.ESCALATE_NO_WRITE)
                self.assertEqual(verdict.category, "EXTERNAL_SAFETY_DENIAL")

    def test_old_denial_cannot_be_downgraded_by_later_500(self):
        history = [obs(BlockerSource.REPOSITORY_POLICY),
                   obs(BlockerSource.GITHUB_HTTP, "repository-native", http_status=500)]
        result = decide_mutation_continuation(history, logical_intent_id=IDENTITY,
                                              provider="repository-native")
        self.assertEqual(result.category, "OWNER_POLICY_DENIAL")
        self.assertEqual(result.action, RecoveryAction.ESCALATE_NO_WRITE)

    def test_access_denial_cannot_be_laundered_by_later_transient_failure(self):
        prior = obs(BlockerSource.GITHUB_HTTP, "connector", http_status=403)
        later = obs(BlockerSource.GITHUB_HTTP, "connector", http_status=503)
        outcome = decide_mutation_continuation([prior, later],
                                                logical_intent_id=IDENTITY,
                                                provider="connector")
        self.assertEqual(outcome.category, "ACCESS_OR_RESOURCE_UNDETERMINED")
        self.assertEqual(outcome.action, RecoveryAction.ESCALATE_NO_WRITE)

    def test_403_and_404_do_not_prove_token_scope_or_absence(self):
        for status in (401, 403, 404):
            with self.subTest(status=status):
                v = classify_blocker(obs(BlockerSource.GITHUB_HTTP, http_status=status))
                self.assertEqual(v.category, "ACCESS_OR_RESOURCE_UNDETERMINED")
                self.assertEqual(v.action, RecoveryAction.ESCALATE_NO_WRITE)

    def test_stale_sha_requires_replan_not_force(self):
        for observation in (obs(BlockerSource.STALE_IDENTITY),
                            obs(BlockerSource.GITHUB_HTTP, http_status=412)):
            self.assertEqual(classify_blocker(observation).action,
                             RecoveryAction.READ_ONLY_REPLAN)

    def test_workflow_ci_review_need_specific_revalidation(self):
        for source in (BlockerSource.WORKFLOW_GOVERNANCE, BlockerSource.CI,
                       BlockerSource.REVIEW):
            self.assertEqual(classify_blocker(obs(source)).action,
                             RecoveryAction.REPAIR_AND_REVALIDATE)

    def test_transient_retry_cannot_change_provider(self):
        o = obs(BlockerSource.GITHUB_HTTP, "connector", http_status=503)
        self.assertEqual(decide_mutation_continuation([o], logical_intent_id=IDENTITY,
                         provider="connector").action, RecoveryAction.RETRY_SAME_PROVIDER)
        self.assertEqual(decide_mutation_continuation([o], logical_intent_id=IDENTITY,
                         provider="native").action, RecoveryAction.ESCALATE_NO_WRITE)

    def test_unobserved_tool_reason_stays_unknown(self):
        self.assertEqual(classify_blocker(obs(BlockerSource.UNKNOWN)).category,
                         "UNKNOWN_BLOCKER")
        self.assertEqual(classify_blocker(obs(BlockerSource.PROVIDER_TRANSPORT)).action,
                         RecoveryAction.ESCALATE_NO_WRITE)
        self.assertEqual(decide_mutation_continuation([], logical_intent_id=IDENTITY,
                         provider="native").category, "NO_BLOCKER_RECORD_NOT_AUTHORIZATION")

    def test_invalid_evidence_and_http_source_are_rejected(self):
        with self.assertRaises(ValueError):
            obs(BlockerSource.GITHUB_HTTP)
        with self.assertRaises(ValueError):
            obs(BlockerSource.TOOL_SAFETY, http_status=403)
        with self.assertRaises(ValueError):
            BlockerObservation("not-an-enum", IDENTITY, "api", "receipt")
        with self.assertRaises(ValueError):
            obs(BlockerSource.UNKNOWN, evidence="")

    def test_path_scopes_cannot_be_ambiguous(self):
        for paths in (["../x"], ["src//x"], ["src\\x"], ["a", "a"], [], "src/x"):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                logical_intent_id(repository=REPO, branch=BRANCH, work_id=WORK, paths=paths)


if __name__ == "__main__":
    unittest.main()
