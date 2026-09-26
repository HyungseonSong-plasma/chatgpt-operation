import unittest

from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.controller.execution import ExecutionStatus
from chatgpt_operation.github.execution_kernel import (
    ExecutionKernel,
    ExecutionKernelError,
    ExecutionProvider,
    GitHubCapability,
)


def merge_plan():
    return ActionPlan.from_dict({
        "schema_version": 1,
        "research_id": "samuel-55",
        "stage": "execute",
        "executor": "github_native",
        "payload": {
            "action": "merge_pr",
            "repository": "HyungseonSong-plasma/chatgpt-operation",
            "target": {"number": 55},
            "preconditions": {
                "head_sha": "2976871b",
                "mergeable": True,
                "ci": "success",
            },
            "desired_postcondition": {"merged": True},
        },
        "expected_observation": "PR merged",
    })


class ExecutionKernelTests(unittest.TestCase):
    def test_merge_provider_executes_and_verifies_postcondition(self):
        states = iter([
            {"merged": False, "head_sha": "2976871b", "mergeable": True, "ci": "success"},
            {"merged": True, "head_sha": "2976871b"},
        ])
        mutations = []
        provider = ExecutionProvider(
            name="github-connector",
            capabilities=frozenset({GitHubCapability.MERGE_PR}),
            read_state=lambda action, target: next(states),
            mutate=lambda action, target: mutations.append((action, target)) or {"merged": True},
        )
        receipt = ExecutionKernel([provider]).execute(merge_plan())
        self.assertEqual(receipt.result.status, ExecutionStatus.PASS)
        self.assertTrue(receipt.attempted)
        self.assertTrue(receipt.complete)
        self.assertEqual(len(mutations), 1)

    def test_missing_provider_fails_closed_without_invented_authority_reason(self):
        with self.assertRaisesRegex(
            ExecutionKernelError,
            "no registered execution provider for GITHUB_PR_MERGE",
        ):
            ExecutionKernel([]).execute(merge_plan())

    def test_stale_precondition_never_mutates(self):
        provider = ExecutionProvider(
            name="github-connector",
            capabilities=frozenset({GitHubCapability.MERGE_PR}),
            read_state=lambda action, target: {
                "merged": False,
                "head_sha": "changed",
                "mergeable": True,
                "ci": "success",
            },
            mutate=lambda action, target: self.fail("must not mutate stale state"),
        )
        receipt = ExecutionKernel([provider]).execute(merge_plan())
        self.assertEqual(receipt.result.status, ExecutionStatus.REJECTED)
        self.assertFalse(receipt.attempted)
        self.assertFalse(receipt.complete)

    def test_noop_is_complete_without_mutation(self):
        provider = ExecutionProvider(
            name="github-connector",
            capabilities=frozenset({GitHubCapability.MERGE_PR}),
            read_state=lambda action, target: {"merged": True},
            mutate=lambda action, target: self.fail("must not mutate completed state"),
        )
        receipt = ExecutionKernel([provider]).execute(merge_plan())
        self.assertEqual(receipt.result.status, ExecutionStatus.NOOP)
        self.assertFalse(receipt.attempted)
        self.assertTrue(receipt.complete)


if __name__ == "__main__":
    unittest.main()
