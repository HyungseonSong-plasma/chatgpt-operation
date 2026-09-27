import unittest
from unittest.mock import patch

from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.github.native_orchestration import (\n    NativeOrchestrationError, dispatch_native_plan, dispatch_native_plan_async, observe_native_plan,\n)


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


class AsyncNativeOrchestrationTests(unittest.TestCase):
    @patch("chatgpt_operation.github.native_orchestration.dispatch_workflow")
    def test_async_dispatch_returns_receipt_without_waiting(self, dispatch):
        p=plan()
        receipt={"workflow_id":1,"ref":"main","correlation_id":p.idempotency_key,
                 "requested_at":"2026-09-27T12:00:00Z","workflow_run_id":None}
        dispatch.return_value=receipt
        self.assertEqual(dispatch_native_plan_async(p,transport=object(),ref="main"),receipt)
        self.assertEqual(dispatch.call_count,1)
        self.assertEqual(dispatch.call_args.kwargs["correlation_id"],p.idempotency_key)
        self.assertIsNone(dispatch.call_args.kwargs["correlation_input"])

    @patch("chatgpt_operation.github.native_orchestration.observe_dispatch_once")
    def test_async_observation_never_redispatches(self, observe):
        p=plan()
        receipt={"workflow_id":1,"ref":"main","correlation_id":p.idempotency_key,
                 "requested_at":"2026-09-27T12:00:00Z","workflow_run_id":None}
        observe.return_value={"status":"MATCHED_ACTIVE"}
        result=observe_native_plan(p,receipt,transport=object())
        self.assertEqual(result["status"],"MATCHED_ACTIVE")
        self.assertEqual(observe.call_count,1)

    def test_async_observation_rejects_foreign_receipt(self):
        p=plan()
        with self.assertRaises(NativeOrchestrationError):
            observe_native_plan(
                p,{"correlation_id":"foreign"},transport=object()
            )
