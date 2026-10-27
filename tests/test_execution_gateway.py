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


class DispatchBlockerGateTests(unittest.TestCase):
    def setUp(self):
        from chatgpt_operation.repository.blocker_journal import GitHubIssueBlockerJournal
        from chatgpt_operation.repository.blocker_gate import CommonPreWriteGate
        from chatgpt_operation.repository.blocker_triage import (
            BlockerObservation, BlockerSource, logical_intent_id,
        )
        from chatgpt_operation.repository.blocker_resolution import (
            ClearanceEvidence, ClearanceKind,
        )
        class IssueAPI:
            def __init__(self):
                self.comments = []
            def get(self, path, *, query=None):
                if path != "/issues/236/comments":
                    raise AssertionError(path)
                offset = (int(query["page"]) - 1) * 100
                return self.comments[offset:offset + 100]
            def request(self, method, path, *, payload=None):
                if method != "POST" or path != "/issues/236/comments":
                    raise AssertionError("unexpected write")
                c = {"id": len(self.comments) + 1, "body": payload["body"],
                     "user": {"login": "samuel-bot"}}
                self.comments.append(c)
                return c
        self.db = GitHubIssueBlockerJournal(
            IssueAPI(), issue_number=236, trusted_actor="samuel-bot",
        )
        self.work_id = "trusted-controller-r"
        self.intent_id = logical_intent_id(
            repository="o/r", branch="samuel/controller",
            work_id=self.work_id, paths=("actions/github_native",),
        )
        self.db.register_work(logical_intent_id=self.intent_id,
                              exact_head_sha=HEAD, evidence_ref="controller-registered")
        self.db.record_blocker(BlockerObservation(
            BlockerSource.TOOL_SAFETY, self.intent_id, "connector", "denial-1",
        ))
        self.auth_proof = ClearanceEvidence(
            self.intent_id, "denial-1", ClearanceKind.UPSTREAM_SAFETY_CLEARED,
            HEAD, "upstream-authority-proof",
        )
        self.Gate = CommonPreWriteGate
        self.gate = self.Gate(
            journal=self.db, trusted_head_reader=lambda: HEAD,
            technical_verifier=lambda _: False, authority_verifier=lambda _: False,
        )

    @patch("chatgpt_operation.controller.execution_gateway.dispatch_native_plan_async")
    @patch("chatgpt_operation.controller.execution_gateway.resume_dispatch_intent")
    def test_controller_refuses_action_workflow_dispatch_on_active_denial(self, resume, dispatch):
        p = plan()
        resume.return_value = (p, intent(p.idempotency_key))
        gateway = ExecutionGateway(
            object(), blocker_gate=self.gate,
            trusted_work_id=self.work_id, trusted_head_sha=HEAD,
        )
        with self.assertRaisesRegex(ExecutionGatewayError, "common prewrite gate"):
            gateway.execute(
                command(ControllerCommandKind.DISPATCH_ACTION,
                        action_id=p.idempotency_key),
                state=ResearchState("r", "work", revision=2),
            )
        dispatch.assert_not_called()

    @patch("chatgpt_operation.controller.execution_gateway.dispatch_native_plan_async")
    @patch("chatgpt_operation.controller.execution_gateway.resume_dispatch_intent")
    def test_controller_dispatch_requires_trusted_work_identity(self, resume, dispatch):
        p = plan()
        resume.return_value = (p, intent(p.idempotency_key))
        with self.assertRaisesRegex(ExecutionGatewayError, "trusted action dispatch work/head"):
            ExecutionGateway(object(), blocker_gate=self.gate).execute(
                command(ControllerCommandKind.DISPATCH_ACTION,
                        action_id=p.idempotency_key),
                state=ResearchState("r", "work", revision=2),
            )
        dispatch.assert_not_called()

    @patch("chatgpt_operation.controller.execution_gateway.dispatch_native_plan_async")
    @patch("chatgpt_operation.controller.execution_gateway.resume_dispatch_intent")
    def test_verified_originating_authority_clearance_allows_regular_dispatch_preflight(self, resume, dispatch):
        p = plan()
        resume.return_value = (p, intent(p.idempotency_key))
        self.db.record_clearance(self.auth_proof)
        trusted_gate = self.Gate(
            journal=self.db, trusted_head_reader=lambda: HEAD,
            technical_verifier=lambda _: False, authority_verifier=lambda _: True,
        )
        dispatch.return_value = {"workflow_run_id": 99,
                                 "correlation_id": p.idempotency_key, "ref": "main"}
        result = ExecutionGateway(
            object(), blocker_gate=trusted_gate,
            trusted_work_id=self.work_id, trusted_head_sha=HEAD,
        ).execute(
            command(ControllerCommandKind.DISPATCH_ACTION,
                    action_id=p.idempotency_key),
            state=ResearchState("r", "work", revision=2),
        )
        self.assertEqual(result.status, GatewayStatus.RECEIPT)
        dispatch.assert_called_once()


if __name__=="__main__":
    unittest.main()
