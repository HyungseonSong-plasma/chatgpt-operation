import unittest

from chatgpt_operation.controller.action_plan import ExecutorKind
from chatgpt_operation.controller.authority import (
    AuthorityEvidence, AuthorityOutcome, classify_execution_authority,
)
from chatgpt_operation.github.native_executor import NativeGitHubAction


class ExecutionAuthorityTests(unittest.TestCase):
    def evidence(self, **changes):
        values=dict(
            executor=ExecutorKind.GITHUB_NATIVE,
            action=NativeGitHubAction.MERGE_PR,
            executor_implemented=True,
            runtime_available=True,
            permission_denial_status=None,
        )
        values.update(changes)
        return AuthorityEvidence(**values)

    def test_connector_refusal_is_not_execution_authority_evidence(self):
        decision=classify_execution_authority(self.evidence())
        self.assertEqual(decision.outcome, AuthorityOutcome.ROUTE_TO_EXECUTOR)
        self.assertIn("merge_pr", decision.reason)

    def test_verified_native_403_is_a_real_authority_blocker(self):
        decision=classify_execution_authority(self.evidence(permission_denial_status=403))
        self.assertEqual(decision.outcome, AuthorityOutcome.BLOCKED)
        self.assertIn("HTTP 403", decision.reason)

    def test_missing_runtime_is_a_real_authority_blocker(self):
        decision=classify_execution_authority(self.evidence(runtime_available=False))
        self.assertEqual(decision.outcome, AuthorityOutcome.BLOCKED)


if __name__ == "__main__":
    unittest.main()
