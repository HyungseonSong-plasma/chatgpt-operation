"""End-to-end qualification of the Samuel controller closed loop."""
import json
import unittest
from unittest.mock import patch

from chatgpt_operation.controller.action_plan import ActionPlan, ExecutorKind
from chatgpt_operation.controller.decisions import DecisionRegistry
from chatgpt_operation.controller.durable_state import (
    apply_dispatch_receipt,
    decode_state,
    encode_state,
)
from chatgpt_operation.controller.execution import ExecutionResult, ExecutionStatus
from chatgpt_operation.controller.execution_gateway import (
    ExecutionGateway,
    GatewayStatus,
)
from chatgpt_operation.controller.issue_ingestion import (
    decode_admission_ledger,
    encode_admission_ledger,
)
from chatgpt_operation.controller.issue_reasoning import IssueReasoningProposal
from chatgpt_operation.controller.reasoning_submission import (
    ReasoningSubmission,
    encode_submission,
)
from chatgpt_operation.controller.runtime import (
    ControllerTrigger,
    SamuelController,
    TriggerKind,
)
from chatgpt_operation.controller.terminal_ingestion import (
    TerminalIngestionOutcome,
    TerminalSurface,
    ingest_terminal_artifact,
)


HEAD="b"*40


def trigger():
    return ControllerTrigger(
        TriggerKind.WORKFLOW_DISPATCH,
        action="",
        head_sha="a"*40,
        ref="refs/heads/main",
        executor_ref="main",
        executor_head_sha=HEAD,
    )


def action_plan():
    return ActionPlan.from_dict({
        "schema_version":1,
        "research_id":"issue:44",
        "stage":"implement",
        "executor":"github_native",
        "payload":{
            "action":"comment_issue",
            "repository":"HyungseonSong-plasma/chatgpt-operation",
            "target":{
                "number":44,
                "body":"<!-- samuel-closed-loop-qualification -->",
                "marker":"<!-- samuel-closed-loop-qualification -->",
            },
            "preconditions":{
                "issue_state":"open",
                "comment_present":False,
            },
            "desired_postcondition":{"comment_present":True},
        },
        "expected_observation":"qualification marker is visible",
    })


def admission_comment(status="reasoning_required"):
    work={
        "issue:44":{
            "work_id":"issue:44",
            "issue_number":44,
            "title":"Samuel OS",
            "body":"qualify controller closed loop",
            "html_url":"https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/44",
            "status":status,
        }
    }
    return {"id":7,"body":encode_admission_ledger(work)}


def reasoning_comment():
    plan=action_plan()
    proposal=IssueReasoningProposal(
        operation="analyze",
        decision_id="github_execution_authority",
        compatible_with_locked_decisions=True,
        revision_requested=False,
        action_plan=plan.to_dict(),
    )
    return {
        "id":8,
        "body":encode_submission(ReasoningSubmission("issue:44",proposal)),
    }


def state_comment(state):
    return {"id":9,"body":encode_state(state)}


class ControllerClosedLoopQualificationTests(unittest.TestCase):
    def test_root_dispatch_observe_ingest_replay_and_stop(self):
        controller=SamuelController(
            decisions=DecisionRegistry.load("automation/samuel/decisions.json")
        )

        # 1. Typed reasoning enters the composition root and becomes one
        # revision-bound dispatch intent + command.
        planned=controller.run_cycle(
            trigger(),
            comments=[admission_comment(),reasoning_comment()],
            pending=[],
        )
        self.assertEqual(planned.selected_work["kind"],"action")
        self.assertIsNotNone(planned.state_write)
        self.assertIsNotNone(planned.execution_command)
        action_id=planned.selected_work["action_id"]
        intent_state=decode_state(planned.state_write["body"])
        self.assertEqual(
            intent_state.action_queue[action_id]["status"],
            "dispatch_intent",
        )
        self.assertEqual(
            planned.execution_command.state_revision,
            intent_state.revision,
        )

        # 2. The execution gateway is the only dispatch boundary and returns
        # a causally bound receipt.
        receipt={
            "workflow_path":".github/workflows/samuel-native-github.yml",
            "ref":"main",
            "correlation_id":action_id,
            "workflow_run_id":99,
        }
        with patch(
            "chatgpt_operation.controller.execution_gateway.dispatch_native_plan_async",
            return_value=receipt,
        ):
            dispatched=ExecutionGateway(object()).execute(
                planned.execution_command,
                state=intent_state,
            )
        self.assertEqual(dispatched.status,GatewayStatus.RECEIPT)
        dispatched_state=apply_dispatch_receipt(
            intent_state,
            surface=dispatched.surface,
            action_id=dispatched.action_id,
            receipt=dispatched.receipt,
        )
        self.assertEqual(
            dispatched_state.action_queue[action_id]["status"],
            "dispatched",
        )

        # 3. A fresh controller cycle resumes from durable state and emits an
        # observation command instead of redispatching.
        admission_planned=decode_admission_ledger(
            planned.admission_write["body"]
        )
        resumed=controller.run_cycle(
            trigger(),
            comments=[
                {"id":7,"body":encode_admission_ledger(admission_planned)},
                state_comment(dispatched_state),
            ],
            pending=[],
        )
        self.assertEqual(resumed.selected_work["kind"],"action_observation")
        self.assertIsNotNone(resumed.execution_command)

        terminal_observation={
            "status":"MATCHED_TERMINAL",
            "matched_run_ids":[99],
            "conclusion":"success",
        }
        with patch(
            "chatgpt_operation.controller.execution_gateway.observe_native_plan",
            return_value=terminal_observation,
        ):
            terminal=ExecutionGateway(object()).execute(
                resumed.execution_command,
                state=dispatched_state,
            )
        self.assertEqual(terminal.status,GatewayStatus.TERMINAL)
        self.assertEqual(terminal.terminal_run_id,99)

        # 4. Terminal evidence is provenance-bound, advances durable state once,
        # and identical replay is a no-op.
        result=ExecutionResult(
            research_id="issue:44",
            action_id=action_id,
            executor=ExecutorKind.GITHUB_NATIVE,
            status=ExecutionStatus.PASS,
            observation="GitHub mutation verified by postcondition readback",
            retryable=False,
            details={
                "after":{"comment_present":True},
                "provenance":{
                    "schema_version":1,
                    "workflow_run_id":99,
                    "run_attempt":1,
                    "head_sha":HEAD,
                    "action_id":action_id,
                },
            },
        )
        artifact=json.dumps(result.to_dict(),sort_keys=True)
        ingested=ingest_terminal_artifact(
            dispatched_state,
            surface=TerminalSurface.ACTION,
            run_id=99,
            artifact_text=artifact,
            gateway_result=terminal.to_dict(),
        )
        self.assertEqual(ingested.outcome,TerminalIngestionOutcome.APPLIED)
        final_state=ingested.proposed_state
        self.assertIsNotNone(final_state)
        self.assertEqual(
            final_state.action_queue[action_id]["status"],
            "complete",
        )

        replay=ingest_terminal_artifact(
            final_state,
            surface=TerminalSurface.ACTION,
            run_id=99,
            artifact_text=artifact,
            gateway_result=terminal.to_dict(),
        )
        self.assertEqual(replay.outcome,TerminalIngestionOutcome.NOOP)
        self.assertIsNone(replay.proposed_state)

        # 5. With no pending/recovery work, the next composition-root cycle
        # terminates itself as idle.
        stopped=controller.run_cycle(
            trigger(),
            comments=[
                {"id":7,"body":encode_admission_ledger(admission_planned)},
                state_comment(final_state),
            ],
            pending=[],
        )
        self.assertEqual(stopped.selected_work,{"kind":"idle"})
        self.assertIsNone(stopped.execution_command)
        self.assertIsNone(stopped.state_write)


if __name__=="__main__":
    unittest.main()
