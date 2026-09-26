import unittest
from unittest.mock import patch

from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.github.native_orchestration import NativeOrchestrationError, dispatch_native_plan


def plan():
    return ActionPlan.from_dict({
        "schema_version":1,"research_id":"r","stage":"execute","executor":"github_native",
        "payload":{"action":"close_issue","repository":"o/r","target":{"number":1},"preconditions":{"issue_state":"open"},"desired_postcondition":{"issue_state":"closed"}},
        "expected_observation":"closed"
    })


class NativeOrchestrationTests(unittest.TestCase):
    @patch("chatgpt_operation.github.native_orchestration.dispatch_and_wait")
    def test_dispatch_uses_action_id_as_correlation(self, dispatch):
        dispatch.return_value={"dispatch":{},"observation":{"status":"MATCHED_TERMINAL","conclusion":"success"}}
        p=plan()
        dispatch_native_plan(p,transport=object(),ref="main")
        self.assertEqual(dispatch.call_args.kwargs["correlation_id"],p.idempotency_key)
        self.assertIsNone(dispatch.call_args.kwargs["correlation_input"])

    @patch("chatgpt_operation.github.native_orchestration.dispatch_and_wait")
    def test_non_terminal_observation_fails_closed(self, dispatch):
        dispatch.return_value={"dispatch":{},"observation":{"status":"OBSERVATION_INCOMPLETE"}}
        with self.assertRaises(NativeOrchestrationError):
            dispatch_native_plan(plan(),transport=object(),ref="main")


if __name__=="__main__":
    unittest.main()


def test_recovery_context_is_dispatched_with_native_plan():
    plan = make_plan()
    transport = FakeTransport()
    dispatch_native_plan(
        plan,
        transport=transport,
        ref="main",
        recovery_state="<!-- samuel-controller-state -->\n{}",
        recovery_authorization={
            "action_id": plan.idempotency_key,
            "source_plan_id": plan.idempotency_key,
            "corrective_action": "retry exact source plan",
            "token": "a" * 64,
        },
        timeout_seconds=1,
        poll_interval_seconds=0,
    )
    inputs = transport.dispatched_inputs
    assert inputs["recovery_state"].startswith("<!-- samuel-controller-state -->")
    auth = json.loads(inputs["recovery_authorization"])
    assert auth["action_id"] == plan.idempotency_key
