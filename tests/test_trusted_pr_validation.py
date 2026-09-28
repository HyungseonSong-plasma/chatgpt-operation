import copy
import unittest
from unittest.mock import patch

from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.controller.command import (
    ControllerCommand,
    ControllerCommandKind,
)
from chatgpt_operation.controller.diagnostic import enqueue_suspended_action
from chatgpt_operation.controller.durable_state import apply_dispatch_receipt
from chatgpt_operation.controller.execution_gateway import (
    ExecutionGateway,
    GatewayStatus,
)
from chatgpt_operation.controller.research import ResearchState
from chatgpt_operation.controller.trusted_validation import (
    record_trusted_validation_dispatch,
    record_trusted_validation_intent,
    select_trusted_validation_work,
)


ACTION_HEAD="c"*40
MAIN_HEAD="d"*40
BRANCH="samuel/issues-24-43-weekly-maintenance-v2"


def create_pr_plan():
    return ActionPlan.from_dict({
        "schema_version":1,
        "research_id":"issue:24",
        "stage":"analyze",
        "executor":"github_native",
        "payload":{
            "action":"create_pr",
            "repository":"HyungseonSong-plasma/chatgpt-operation",
            "target":{
                "head":BRANCH,
                "base":"main",
                "title":"Weekly maintenance",
                "body":"bounded work",
            },
            "preconditions":{"pr_present":False},
            "desired_postcondition":{"pr_present":True},
        },
        "expected_observation":"PR exists",
    })


def completed_state():
    state=ResearchState("issue:24","weekly maintenance")
    plan=create_pr_plan()
    enqueue_suspended_action(state,plan)
    item=state.action_queue[plan.idempotency_key]
    item["status"]="complete"
    item["completion_result"]={
        "schema_version":1,
        "research_id":"issue:24",
        "action_id":plan.idempotency_key,
        "executor":"github_native",
        "status":"pass",
        "observation":"PR exists",
        "retryable":False,
        "details":{"after":{"pr_number":173,"head_sha":ACTION_HEAD}},
    }
    return state,plan


def repository_context(*,head_sha=ACTION_HEAD,ci_state="unknown"):
    return {
        "repository":"HyungseonSong-plasma/chatgpt-operation",
        "observed_head_sha":MAIN_HEAD,
        "open_pull_requests":[{
            "number":173,
            "title":"Weekly maintenance",
            "state":"open",
            "draft":False,
            "head_ref":BRANCH,
            "head_sha":head_sha,
            "base_ref":"main",
            "ci_state":ci_state,
        }],
    }


class TrustedValidationLifecycleTests(unittest.TestCase):
    def test_unknown_ci_requires_exact_current_head_validation(self):
        state,plan=completed_state()
        kind,payload=select_trusted_validation_work(
            state,repository_context()
        )
        self.assertEqual(kind,"trusted_validation")
        self.assertEqual(payload["action_id"],plan.idempotency_key)
        self.assertEqual(payload["pr"]["head_sha"],ACTION_HEAD)

    def test_pending_or_terminal_ci_does_not_duplicate_validation(self):
        state,_=completed_state()
        self.assertIsNone(
            select_trusted_validation_work(
                state,repository_context(ci_state="pending")
            )
        )
        self.assertIsNone(
            select_trusted_validation_work(
                state,repository_context(ci_state="success")
            )
        )
        self.assertIsNone(
            select_trusted_validation_work(
                state,repository_context(ci_state="failure")
            )
        )

    def test_intent_and_receipt_are_durable_and_exact_head_bound(self):
        state,plan=completed_state()
        before=state.revision
        record=record_trusted_validation_intent(
            state,
            plan.idempotency_key,
            pr_number=173,
            head_sha=ACTION_HEAD,
            head_branch=BRANCH,
            base_ref="main",
            workflow="samuel-trusted-pr-validation.yml",
            ref="main",
            requested_at="2026-09-28T10:00:00Z",
            expected_head_sha=MAIN_HEAD,
        )
        self.assertEqual(state.revision,before+1)
        self.assertEqual(record["status"],"dispatch_intent")
        self.assertEqual(record["intent"]["expected_head_sha"],MAIN_HEAD)
        validation_id=record["validation_id"]
        receipt={
            "workflow_path":".github/workflows/samuel-trusted-pr-validation.yml",
            "ref":"main",
            "correlation_id":validation_id,
            "workflow_run_id":999,
        }
        proposed=apply_dispatch_receipt(
            state,
            surface="trusted_validation",
            action_id=plan.idempotency_key,
            receipt=receipt,
        )
        durable=proposed.action_queue[plan.idempotency_key]["trusted_validation"]
        self.assertEqual(durable["status"],"dispatched")
        self.assertEqual(durable["receipt"]["workflow_run_id"],999)
        kind,_=select_trusted_validation_work(
            proposed,repository_context()
        )
        self.assertEqual(kind,"trusted_validation_wait")

    def test_new_pr_head_requires_new_validation_after_old_dispatch(self):
        state,plan=completed_state()
        record=record_trusted_validation_intent(
            state,plan.idempotency_key,
            pr_number=173,head_sha=ACTION_HEAD,head_branch=BRANCH,base_ref="main",
            workflow="samuel-trusted-pr-validation.yml",ref="main",
            requested_at="2026-09-28T10:00:00Z",expected_head_sha=MAIN_HEAD,
        )
        record_trusted_validation_dispatch(state,plan.idempotency_key,{
            "workflow_path":".github/workflows/samuel-trusted-pr-validation.yml",
            "ref":"main",
            "correlation_id":record["validation_id"],
            "workflow_run_id":999,
        })
        newer="e"*40
        kind,payload=select_trusted_validation_work(
            state,repository_context(head_sha=newer)
        )
        self.assertEqual(kind,"trusted_validation")
        self.assertEqual(payload["pr"]["head_sha"],newer)


class TrustedValidationGatewayTests(unittest.TestCase):
    @patch("chatgpt_operation.controller.execution_gateway.dispatch_workflow")
    @patch(
        "chatgpt_operation.controller.execution_gateway."
        "resume_trusted_validation_intent"
    )
    def test_dispatch_uses_exact_pr_identity_and_correlation(self,resume,dispatch):
        state,plan=completed_state()
        record=record_trusted_validation_intent(
            state,plan.idempotency_key,
            pr_number=173,head_sha=ACTION_HEAD,head_branch=BRANCH,base_ref="main",
            workflow="samuel-trusted-pr-validation.yml",ref="main",
            requested_at="2026-09-28T10:00:00Z",expected_head_sha=MAIN_HEAD,
        )
        from chatgpt_operation.controller.action_lifecycle import DispatchIntent
        resume.return_value=(record,DispatchIntent.from_dict(record["intent"]))
        dispatch.return_value={
            "workflow_run_id":999,
            "correlation_id":record["validation_id"],
            "ref":"main",
        }
        command=ControllerCommand(
            ControllerCommandKind.DISPATCH_TRUSTED_VALIDATION,
            plan.idempotency_key,
            state.research_id,
            state.revision,
        )
        result=ExecutionGateway(object()).execute(command,state=state)
        self.assertEqual(result.status,GatewayStatus.RECEIPT)
        self.assertEqual(result.surface,"trusted_validation")
        kwargs=dispatch.call_args.kwargs
        self.assertEqual(kwargs["workflow"],"samuel-trusted-pr-validation.yml")
        self.assertEqual(kwargs["inputs"]["pr_number"],"173")
        self.assertEqual(kwargs["inputs"]["head_sha"],ACTION_HEAD)
        self.assertEqual(kwargs["inputs"]["head_branch"],BRANCH)
        self.assertEqual(
            kwargs["correlation_id"],record["validation_id"]
        )


if __name__=="__main__":
    unittest.main()
