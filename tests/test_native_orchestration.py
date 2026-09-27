import json
import unittest
from unittest.mock import patch

from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.github.native_orchestration import (
    NativeOrchestrationError,
    dispatch_native_plan,
    dispatch_native_plan_async,
    observe_native_intent,
    observe_native_plan,
)


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
    p = plan()
    authorization = {
        "action_id": p.idempotency_key,
        "source_plan_id": p.idempotency_key,
        "corrective_action": "retry exact source plan",
        "corrective_provider": "fallback",
        "token": "a" * 64,
    }
    with patch("chatgpt_operation.github.native_orchestration.dispatch_and_wait") as dispatch:
        dispatch.return_value = {
            "dispatch": {},
            "observation": {"status": "MATCHED_TERMINAL", "conclusion": "success"},
        }
        dispatch_native_plan(
            p,
            transport=object(),
            ref="main",
            recovery_state="<!-- samuel-controller-state -->\n{}",
            recovery_authorization=authorization,
            timeout_seconds=1,
            poll_interval_seconds=0,
        )
    inputs = dispatch.call_args.kwargs["inputs"]
    assert inputs["recovery_state"].startswith("<!-- samuel-controller-state -->")
    auth = json.loads(inputs["recovery_authorization"])
    assert auth == authorization


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
        self.assertEqual(dispatch.call_args.kwargs["correlation_input"],"samuel_action_id")
        self.assertEqual(dispatch.call_args.kwargs["correlation_run_name_prefix"],"Samuel Native GitHub Executor action:")
        self.assertEqual(dispatch.call_args.kwargs["inputs"]["samuel_action_id"],p.idempotency_key)

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


class IntentRecoveryTests(unittest.TestCase):
    @patch("chatgpt_operation.github.native_orchestration.observe_dispatch_once")
    @patch("chatgpt_operation.github.native_orchestration.observation_receipt_from_identity")
    def test_intent_recovery_observes_without_redispatch(self, build_receipt, observe):
        p=plan()
        from chatgpt_operation.controller.action_lifecycle import DispatchIntent
        intent=DispatchIntent(
            action_id=p.idempotency_key,research_id="r",workflow="samuel-native-github.yml",
            ref="main",requested_at="2026-09-27T12:00:00Z",state_revision=2,
        )
        base={"workflow_id":1,"workflow_path":".github/workflows/samuel-native-github.yml",
              "ref":"main","correlation_id":p.idempotency_key,
              "correlation_input":"samuel_action_id",
              "correlation_run_name_prefix":"Samuel Native GitHub Executor action:",
              "requested_at":intent.requested_at,"workflow_run_id":None}
        build_receipt.return_value=base
        observe.return_value={"status":"MATCHED_ACTIVE","matched_run_ids":[99]}
        result=observe_native_intent(p,intent,transport=object())
        self.assertEqual(result["receipt"]["workflow_run_id"],99)
        self.assertTrue(result["receipt"]["recovered_from_intent"])
        self.assertEqual(observe.call_count,1)

    @patch("chatgpt_operation.github.native_orchestration.observe_dispatch_once")
    @patch("chatgpt_operation.github.native_orchestration.observation_receipt_from_identity")
    def test_intent_pending_visibility_does_not_invent_receipt(self, build_receipt, observe):
        p=plan()
        from chatgpt_operation.controller.action_lifecycle import DispatchIntent
        intent=DispatchIntent(
            action_id=p.idempotency_key,research_id="r",workflow="samuel-native-github.yml",
            ref="main",requested_at="2026-09-27T12:00:00Z",state_revision=2,
        )
        build_receipt.return_value={"workflow_id":1,"ref":"main","correlation_id":p.idempotency_key,
                                    "requested_at":intent.requested_at,"workflow_run_id":None}
        observe.return_value={"status":"PENDING_VISIBILITY","matched_run_ids":[]}
        result=observe_native_intent(p,intent,transport=object())
        self.assertIsNone(result["receipt"])
