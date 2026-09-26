import unittest

from chatgpt_operation.controller.action_plan import ExecutorKind
from chatgpt_operation.controller.execution import (
    ExecutionResult,
    ExecutionStatus,
    transition_from_execution,
)
from chatgpt_operation.controller.research import (
    ResearchStage,
    ResearchState,
    ResearchStateError,
)


ACTION_ID = "a" * 64


def state_at_decide():
    return ResearchState(
        research_id="samuel-evidence",
        objective="prove evidence-gated completion",
        stage=ResearchStage.DECIDE,
    )


def result(status, retryable=False):
    return ExecutionResult(
        research_id="samuel-evidence",
        action_id=ACTION_ID,
        executor=ExecutorKind.GITHUB_NATIVE,
        status=status,
        observation="typed executor evidence",
        retryable=retryable,
        details={"provider": "github-connector"},
    )


class EvidenceGatedStateTests(unittest.TestCase):
    def test_reasoning_cannot_promote_state_to_complete(self):
        state = state_at_decide()
        with self.assertRaisesRegex(
            ResearchStateError,
            "COMPLETE is evidence-gated",
        ):
            state.transition(ResearchStage.COMPLETE)
        self.assertEqual(state.stage, ResearchStage.DECIDE)

    def test_pass_execution_evidence_can_complete(self):
        state = state_at_decide()
        changed = transition_from_execution(
            state,
            result(ExecutionStatus.PASS),
            ResearchStage.COMPLETE,
        )
        self.assertTrue(changed)
        self.assertEqual(state.stage, ResearchStage.COMPLETE)
        self.assertIn(ACTION_ID, state.execution_results)

    def test_noop_execution_evidence_can_complete(self):
        state = state_at_decide()
        transition_from_execution(
            state,
            result(ExecutionStatus.NOOP),
            ResearchStage.COMPLETE,
        )
        self.assertEqual(state.stage, ResearchStage.COMPLETE)

    def test_failed_execution_cannot_complete(self):
        state = state_at_decide()
        with self.assertRaisesRegex(
            ResearchStateError,
            "COMPLETE requires PASS/NOOP execution evidence",
        ):
            transition_from_execution(
                state,
                result(ExecutionStatus.FAILED, retryable=True),
                ResearchStage.COMPLETE,
            )
        self.assertEqual(state.stage, ResearchStage.DECIDE)
        self.assertIn(ACTION_ID, state.execution_results)

    def test_rejected_execution_cannot_complete(self):
        state = state_at_decide()
        with self.assertRaisesRegex(
            ResearchStateError,
            "COMPLETE requires PASS/NOOP execution evidence",
        ):
            transition_from_execution(
                state,
                result(ExecutionStatus.REJECTED),
                ResearchStage.COMPLETE,
            )
        self.assertEqual(state.stage, ResearchStage.DECIDE)


if __name__ == "__main__":
    unittest.main()
