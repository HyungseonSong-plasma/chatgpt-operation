import unittest

from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.controller.research import ResearchState, ResearchStage, ResearchStateError
from chatgpt_operation.controller.execution import ExecutionStatus, open_diagnostic_recovery
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
        receipt = ExecutionKernel([provider], state=ResearchState("samuel-55", "kernel test", stage=ResearchStage.EXECUTE)).execute(merge_plan())
        self.assertEqual(receipt.result.status, ExecutionStatus.PASS)
        self.assertTrue(receipt.attempted)
        self.assertTrue(receipt.complete)
        self.assertEqual(len(mutations), 1)

    def test_missing_provider_fails_closed_without_invented_authority_reason(self):
        with self.assertRaisesRegex(
            ExecutionKernelError,
            "no registered execution provider for GITHUB_PR_MERGE",
        ):
            ExecutionKernel([], state=ResearchState("samuel-55", "kernel test", stage=ResearchStage.EXECUTE)).execute(merge_plan())

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
        receipt = ExecutionKernel([provider], state=ResearchState("samuel-55", "kernel test", stage=ResearchStage.EXECUTE)).execute(merge_plan())
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
        receipt = ExecutionKernel([provider], state=ResearchState("samuel-55", "kernel test", stage=ResearchStage.EXECUTE)).execute(merge_plan())
        self.assertEqual(receipt.result.status, ExecutionStatus.NOOP)
        self.assertFalse(receipt.attempted)
        self.assertTrue(receipt.complete)


    def test_provider_failure_falls_back_and_preserves_evidence(self):
        primary = ExecutionProvider(
            name="github-connector",
            capabilities=frozenset({GitHubCapability.MERGE_PR}),
            read_state=lambda action, target: {
                "merged": False, "head_sha": "2976871b",
                "mergeable": True, "ci": "success",
            },
            mutate=lambda action, target: (_ for _ in ()).throw(
                RuntimeError("blocked by provider safety check")
            ),
        )
        states = iter([
            {"merged": False, "head_sha": "2976871b", "mergeable": True, "ci": "success"},
            {"merged": True, "head_sha": "2976871b"},
        ])
        fallback = ExecutionProvider(
            name="github-rest",
            capabilities=frozenset({GitHubCapability.MERGE_PR}),
            read_state=lambda action, target: next(states),
            mutate=lambda action, target: {"merged": True},
        )
        receipt = ExecutionKernel([primary, fallback], state=ResearchState("samuel-55", "kernel test", stage=ResearchStage.EXECUTE)).execute(merge_plan())
        self.assertEqual(receipt.provider, "github-rest")
        self.assertTrue(receipt.complete)
        self.assertEqual(len(receipt.provider_failures), 1)
        self.assertEqual(receipt.provider_failures[0].provider, "github-connector")
        self.assertTrue(receipt.provider_failures[0].attempted)

    def test_all_provider_failures_are_required_before_kernel_blocker(self):
        def failed(name):
            return ExecutionProvider(
                name=name,
                capabilities=frozenset({GitHubCapability.MERGE_PR}),
                read_state=lambda action, target: {
                    "merged": False, "head_sha": "2976871b",
                    "mergeable": True, "ci": "success",
                },
                mutate=lambda action, target: (_ for _ in ()).throw(
                    RuntimeError(f"{name} rejected mutation")
                ),
            )
        with self.assertRaisesRegex(
            ExecutionKernelError,
            "all registered providers failed for GITHUB_PR_MERGE",
        ) as caught:
            ExecutionKernel([failed("connector"), failed("rest")], state=ResearchState("samuel-55", "kernel test", stage=ResearchStage.EXECUTE)).execute(merge_plan())
        self.assertIn("connector:RuntimeError", str(caught.exception))
        self.assertIn("rest:RuntimeError", str(caught.exception))


    def test_open_diagnostic_recovery_blocks_kernel_before_provider_read(self):
        state = ResearchState("samuel-55", "kernel test", stage=ResearchStage.EXECUTE)
        plan = merge_plan()
        failed = __import__("chatgpt_operation.controller.execution", fromlist=["ExecutionResult"]).ExecutionResult.from_dict({
            "schema_version": 1,
            "research_id": "samuel-55",
            "action_id": plan.idempotency_key,
            "executor": "github_native",
            "status": "failed",
            "observation": "same provider failure",
            "retryable": True,
            "details": {"provider": "github-connector", "error_type": "RuntimeError"},
        })
        open_diagnostic_recovery(
            state,
            failed,
            fingerprint=(plan.idempotency_key, "failed", "github-connector", "RuntimeError", ""),
        )
        provider = ExecutionProvider(
            name="github-connector",
            capabilities=frozenset({GitHubCapability.MERGE_PR}),
            read_state=lambda action, target: self.fail("provider must not be touched during open diagnosis"),
            mutate=lambda action, target: self.fail("provider must not be touched during open diagnosis"),
        )
        with self.assertRaisesRegex(ResearchStateError, "suspended pending diagnostic recovery"):
            ExecutionKernel([provider], state=state).execute(plan)

if __name__ == "__main__":
    unittest.main()
