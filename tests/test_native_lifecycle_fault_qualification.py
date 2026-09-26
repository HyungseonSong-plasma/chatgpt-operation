"""Qualification of Samuel lifecycle recovery using the real native executor boundary."""
import unittest

from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.controller.execution import record_execution_result
from chatgpt_operation.controller.invariants import ContinuationKind, continuation_from_execution
from chatgpt_operation.controller.lifecycle_scenario import LifecycleScenario
from chatgpt_operation.controller.research import ResearchState
from chatgpt_operation.github.native_executor import execute_native_github


def plan():
    return ActionPlan.from_dict({
        "schema_version": 1,
        "research_id": "native-fault-qualification",
        "stage": "execute",
        "executor": "github_native",
        "payload": {
            "action": "comment_issue",
            "repository": "owner/repo",
            "target": {"issue_number": 44, "marker": "<!-- samuel-qualification -->", "body": "qualified"},
            "preconditions": {"marker_present": False},
            "desired_postcondition": {"marker_present": True},
        },
        "expected_observation": "qualification marker is visible",
    })


class NativeLifecycleFaultQualificationTests(unittest.TestCase):
    def test_real_native_executor_failure_is_checkpointed_and_resume_is_bounded(self):
        state = ResearchState("native-fault-qualification", "qualify Samuel recovery")
        scenario = LifecycleScenario(state)
        scenario.establish_hypothesis("controller can preserve science across a final write blocker")
        scenario.design_experiment("inject native GitHub mutation postcondition failure")
        scenario.record_test("scientific work completed before final mutation")

        current = {"marker_present": False}
        calls = []

        def read_state(_action, _payload):
            return dict(current)

        def blocked_mutate(_action, _payload):
            calls.append("blocked")
            return {"accepted": True}  # write appears accepted but readback never changes

        failed = execute_native_github(plan(), read_state=read_state, mutate=blocked_mutate)
        self.assertEqual(failed.status.value, "failed")
        self.assertTrue(failed.retryable)
        self.assertTrue(record_execution_result(state, failed))
        continuation = continuation_from_execution(failed)
        self.assertEqual(continuation.kind, ContinuationKind.RETRY)

        # Scientific checkpoint survives the native executor failure.
        self.assertEqual(scenario.evidence.events, ["hypothesis", "experiment", "test"])
        self.assertEqual(
            scenario.evidence.test_result,
            "scientific work completed before final mutation",
        )

        def recovered_mutate(_action, _payload):
            calls.append("recovered")
            current["marker_present"] = True
            return {"accepted": True}

        recovered = execute_native_github(plan(), read_state=read_state, mutate=recovered_mutate)
        self.assertEqual(recovered.status.value, "pass")
        # Successful retry replaces the current result while preserving immutable attempt history.
        self.assertTrue(record_execution_result(state, recovered))
        stored = state.execution_results[recovered.action_id]
        self.assertEqual(stored["status"], "pass")
        self.assertEqual(stored["details"]["attempt_history"][0]["status"], "failed")
        self.assertTrue(stored["details"]["attempt_history"][0]["retryable"])
        self.assertEqual(continuation_from_execution(recovered).kind, ContinuationKind.NEXT_ACTION)
        self.assertEqual(calls, ["blocked", "recovered"])

    def test_native_replay_after_recovery_is_noop(self):
        current = {"marker_present": True}
        mutations = []

        result = execute_native_github(
            plan(),
            read_state=lambda _action, _payload: dict(current),
            mutate=lambda _action, _payload: mutations.append("unexpected"),
        )
        self.assertEqual(result.status.value, "noop")
        self.assertEqual(mutations, [])


if __name__ == "__main__":
    unittest.main()
