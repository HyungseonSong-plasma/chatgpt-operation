import unittest
from unittest.mock import patch

from chatgpt_operation.controller.action_lifecycle import DispatchIntent
from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.controller.command import ControllerCommand, ControllerCommandKind
from chatgpt_operation.controller.execution_gateway import (
    ExecutionGateway,
    ExecutionGatewayError,
    GatewayStatus,
)
from chatgpt_operation.controller.research import ResearchState


ACTION = "a" * 64
HEAD = "b" * 40


def plan():
    return ActionPlan.from_dict({
        "schema_version":1,
        "research_id":"r",
        "stage":"execute",
        "executor":"github_native",
        "payload":{
            "action":"comment_issue",
            "repository":"o/r",
            "target":{"issue_number":44},
            "preconditions":{"state":"open"},
            "desired_postcondition":{"comment_present":True},
        },
        "expected_observation":"verified",
    })


def intent(action_id=ACTION, workflow="samuel-native-github.yml"):
    return DispatchIntent(
        action_id=action_id,
        research_id="r",
        workflow=workflow,
        ref="main",
        requested_at="2026-09-27T20:00:00Z",
        state_revision=2,
        expected_head_sha=HEAD,
    )


def command(kind, revision=2, action_id=ACTION):
    return ControllerCommand(kind, action_id, "r", revision)


class ExecutionGatewayTests(unittest.TestCase):
    def test_stale_command_is_rejected_before_runtime_access(self):
        state=ResearchState("r","work",revision=3)
        gateway=ExecutionGateway(object())
        with self.assertRaisesRegex(ExecutionGatewayError,"stale controller command"):
            gateway.execute(
                command(ControllerCommandKind.DISPATCH_ACTION,revision=2),
                state=state,
            )

    @patch("chatgpt_operation.controller.execution_gateway.dispatch_native_plan_async")
    @patch("chatgpt_operation.controller.execution_gateway.resume_dispatch_intent")
    def test_action_dispatch_returns_bound_receipt(self, resume, dispatch):
        p=plan()
        resume.return_value=(p,intent(p.idempotency_key))
        receipt={
            "correlation_id":p.idempotency_key,
            "workflow_run_id":99,
            "ref":"main",
        }
        dispatch.return_value=receipt
        state=ResearchState("r","work",revision=2)
        result=ExecutionGateway(object()).execute(
            command(
                ControllerCommandKind.DISPATCH_ACTION,
                action_id=p.idempotency_key,
            ),
            state=state,
        )
        self.assertEqual(result.status,GatewayStatus.RECEIPT)
        self.assertEqual(result.surface,"action")
        self.assertEqual(result.receipt,receipt)
        self.assertEqual(dispatch.call_count,1)

    @patch("chatgpt_operation.controller.execution_gateway.dispatch_native_plan_async")
    @patch("chatgpt_operation.controller.execution_gateway.observe_native_intent")
    @patch("chatgpt_operation.controller.execution_gateway.resume_dispatch_intent")
    def test_action_no_match_recovery_dispatches_once(self, resume, observe, dispatch):
        p=plan(); i=intent(p.idempotency_key)
        resume.return_value=(p,i)
        observe.return_value={
            "observation":{"status":"NO_MATCH","matched_run_ids":[]},
            "receipt":None,
        }
        dispatch.return_value={
            "correlation_id":p.idempotency_key,
            "workflow_run_id":100,
            "ref":"main",
        }
        state=ResearchState("r","work",revision=2)
        result=ExecutionGateway(object()).execute(
            command(
                ControllerCommandKind.RECONCILE_ACTION,
                action_id=p.idempotency_key,
            ),
            state=state,
        )
        self.assertEqual(result.status,GatewayStatus.RECEIPT)
        self.assertEqual(dispatch.call_count,1)

    @patch("chatgpt_operation.controller.execution_gateway.observe_native_plan")
    @patch("chatgpt_operation.controller.execution_gateway.resume_dispatched_action")
    def test_action_terminal_returns_run_identity(self, resume, observe):
        p=plan(); i=intent(p.idempotency_key)
        receipt={"workflow_run_id":99,"correlation_id":p.idempotency_key}
        resume.return_value=(p,receipt)
        observe.return_value={
            "status":"MATCHED_TERMINAL",
            "matched_run_ids":[99],
            "conclusion":"success",
        }
        state=ResearchState(
            "r","work",revision=2,
            action_queue={
                p.idempotency_key:{
                    "status":"dispatched",
                    "plan":{},
                    "dispatch_intent":i.to_dict(),
                    "dispatch_receipt":receipt,
                }
            },
        )
        result=ExecutionGateway(object()).execute(
            command(
                ControllerCommandKind.OBSERVE_ACTION,
                action_id=p.idempotency_key,
            ),
            state=state,
        )
        self.assertEqual(result.status,GatewayStatus.TERMINAL)
        self.assertEqual(result.terminal_run_id,99)

    @patch("chatgpt_operation.controller.execution_gateway.observe_native_plan")
    @patch("chatgpt_operation.controller.execution_gateway.resume_dispatched_action")
    def test_bound_action_source_mismatch_becomes_terminal_recovery_event(
        self,resume,observe
    ):
        p=plan(); i=intent(p.idempotency_key)
        receipt={"workflow_run_id":99,"correlation_id":p.idempotency_key}
        resume.return_value=(p,receipt)
        observe.return_value={
            "status":"BOUND_RUN_IDENTITY_MISMATCH",
            "matched_run_ids":[99],
            "run_status":"completed",
            "conclusion":"success",
            "identity_mismatches":{
                "head_sha":{"expected":"b"*40,"observed":"c"*40}
            },
        }
        state=ResearchState(
            "r","work",revision=2,
            action_queue={
                p.idempotency_key:{
                    "status":"dispatched",
                    "plan":{},
                    "dispatch_intent":i.to_dict(),
                    "dispatch_receipt":receipt,
                }
            },
        )
        result=ExecutionGateway(object()).execute(
            command(
                ControllerCommandKind.OBSERVE_ACTION,
                action_id=p.idempotency_key,
            ),
            state=state,
        )
        self.assertEqual(result.status,GatewayStatus.TERMINAL)
        self.assertEqual(result.terminal_run_id,99)
        self.assertEqual(
            result.observation["status"],
            "BOUND_RUN_IDENTITY_MISMATCH",
        )

    @patch("chatgpt_operation.controller.execution_gateway.dispatch_workflow")
    @patch("chatgpt_operation.controller.execution_gateway.resume_evidence_dispatch_intent")
    def test_evidence_dispatch_uses_durable_correlation(self, resume, dispatch):
        i=intent(ACTION,"samuel-evidence-acquisition.yml")
        resume.return_value=(i,"evidence-correlation")
        dispatch.return_value={
            "workflow_run_id":101,
            "correlation_id":"evidence-correlation",
            "ref":"main",
        }
        state=ResearchState(
            "r","work",revision=2,
            diagnostic_recoveries={
                ACTION:{
                    "status":"needs_evidence",
                    "evidence_request":{"fingerprint":"f"},
                }
            },
        )
        result=ExecutionGateway(object()).execute(
            command(ControllerCommandKind.DISPATCH_EVIDENCE),
            state=state,
        )
        self.assertEqual(result.status,GatewayStatus.RECEIPT)
        self.assertEqual(result.surface,"evidence")
        self.assertEqual(
            dispatch.call_args.kwargs["correlation_id"],
            "evidence-correlation",
        )
        self.assertEqual(
            dispatch.call_args.kwargs["inputs"]["samuel_dispatch_id"],
            "evidence-correlation",
        )

    @patch("chatgpt_operation.controller.execution_gateway.observe_dispatch_once")
    @patch("chatgpt_operation.controller.execution_gateway.observation_receipt_from_identity")
    @patch("chatgpt_operation.controller.execution_gateway.resume_evidence_dispatch_intent")
    def test_evidence_no_match_waits_without_redispatch(self, resume, build, observe):
        i=intent(ACTION,"samuel-evidence-acquisition.yml")
        resume.return_value=(i,"evidence-correlation")
        build.return_value={
            "workflow_id":1,
            "workflow_run_id":None,
            "correlation_id":"evidence-correlation",
            "requested_at":i.requested_at,
            "ref":"main",
        }
        observe.return_value={"status":"NO_MATCH","matched_run_ids":[]}
        state=ResearchState("r","work",revision=2)
        result=ExecutionGateway(object()).execute(
            command(ControllerCommandKind.RECONCILE_EVIDENCE),
            state=state,
        )
        self.assertEqual(result.status,GatewayStatus.WAIT)
        self.assertEqual(result.observation["status"],"NO_MATCH")

    @patch("chatgpt_operation.controller.execution_gateway.dispatch_workflow")
    @patch("chatgpt_operation.controller.execution_gateway.observe_dispatch_once")
    @patch("chatgpt_operation.controller.execution_gateway.observation_receipt_from_identity")
    @patch("chatgpt_operation.controller.execution_gateway.resume_diagnostic_dispatch_intent")
    def test_diagnostic_no_match_uses_controlled_recovery_dispatch(
        self, resume, build, observe, dispatch
    ):
        i=intent(ACTION,"samuel-diagnostic-recovery.yml")
        resume.return_value=(i,"diagnostic-correlation")
        build.return_value={
            "workflow_id":1,
            "workflow_run_id":None,
            "correlation_id":"diagnostic-correlation",
            "requested_at":i.requested_at,
            "ref":"main",
        }
        observe.return_value={"status":"NO_MATCH","matched_run_ids":[]}
        dispatch.return_value={
            "workflow_run_id":102,
            "correlation_id":"diagnostic-correlation",
            "ref":"main",
        }
        state=ResearchState(
            "r","work",revision=2,
            diagnostic_recoveries={ACTION:{"status":"open"}},
        )
        result=ExecutionGateway(object()).execute(
            command(ControllerCommandKind.RECONCILE_DIAGNOSTIC),
            state=state,
        )
        self.assertEqual(result.status,GatewayStatus.RECEIPT)
        self.assertEqual(dispatch.call_count,1)


if __name__=="__main__":
    unittest.main()
