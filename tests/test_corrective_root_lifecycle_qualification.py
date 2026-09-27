"""Qualification of corrective recovery through the Samuel composition root."""
import json
import unittest
from unittest.mock import patch

from chatgpt_operation.controller.action_plan import ActionPlan, ExecutorKind
from chatgpt_operation.controller.command import ControllerCommandKind
from chatgpt_operation.controller.decisions import DecisionRegistry
from chatgpt_operation.controller.diagnostic import attach_source_plan
from chatgpt_operation.controller.durable_state import (
    apply_dispatch_receipt,
    decode_state,
    encode_state,
)
from chatgpt_operation.controller.execution import ExecutionResult, ExecutionStatus
from chatgpt_operation.controller.execution_gateway import ExecutionGateway, GatewayStatus
from chatgpt_operation.controller.research import ResearchStage, ResearchState
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


def plan():
    return ActionPlan.from_dict({
        "schema_version":1,
        "research_id":"issue:44",
        "stage":"execute",
        "executor":"github_native",
        "payload":{
            "action":"comment_issue",
            "repository":"HyungseonSong-plasma/chatgpt-operation",
            "target":{"issue_number":44},
            "preconditions":{"state":"open"},
            "desired_postcondition":{"comment_present":True},
        },
        "expected_observation":"verified",
    })


def corrective_ready_state():
    p=plan()
    state=ResearchState(
        "issue:44",
        "recover failed native action",
        stage=ResearchStage.EXECUTE,
        action_queue={
            p.idempotency_key:{
                "status":"suspended",
                "plan":{
                    "schema_version":1,
                    "research_id":p.research_id,
                    "stage":p.stage.value,
                    "executor":p.executor.value,
                    "payload":p.payload,
                    "expected_observation":p.expected_observation,
                    "decision_risk":None,
                },
            }
        },
        diagnostic_recoveries={
            p.idempotency_key:{
                "status":"open",
                "fingerprint":[],
                "failure":{"details":{
                    "provider":"primary",
                    "available_providers":["fallback"],
                }},
                "root_cause":"provider failure",
                "corrective_action":"retry through eligible provider=fallback",
                "corrective_provider":"fallback",
                "resolution_evidence":None,
            }
        },
        revision=5,
    )
    attach_source_plan(state,p.idempotency_key,p)
    return p,state


def trigger():
    return ControllerTrigger(
        TriggerKind.WORKFLOW_DISPATCH,
        head_sha="a"*40,
        ref="refs/heads/main",
        executor_ref="main",
        executor_head_sha=HEAD,
    )


def comment(state):
    return {"id":9,"body":encode_state(state)}


class CorrectiveRootLifecycleQualificationTests(unittest.TestCase):
    def test_corrective_recovery_uses_root_gateway_terminal_ingestion_and_resumes_action(self):
        p,state=corrective_ready_state()
        controller=SamuelController(
            decisions=DecisionRegistry.load("automation/samuel/decisions.json"),
            now=lambda: __import__("datetime").datetime(
                2026,9,27,21,0,
                tzinfo=__import__("datetime").timezone.utc,
            ),
        )

        cycle=controller.run_cycle(
            trigger(),comments=[comment(state)],pending=[]
        )
        self.assertEqual(cycle.selected_work["kind"],"corrective")
        self.assertEqual(
            cycle.execution_command.kind,
            ControllerCommandKind.DISPATCH_CORRECTIVE,
        )
        intent_state=decode_state(cycle.state_write["body"])
        dispatch=intent_state.diagnostic_recoveries[p.idempotency_key][
            "corrective_dispatch"
        ]
        self.assertEqual(dispatch["status"],"dispatch_intent")
        correlation_id=dispatch["correlation_id"]

        receipt={
            "workflow_path":".github/workflows/samuel-native-github.yml",
            "ref":"main",
            "correlation_id":correlation_id,
            "workflow_run_id":99,
        }
        with patch(
            "chatgpt_operation.controller.execution_gateway.dispatch_native_plan_async",
            return_value=receipt,
        ) as dispatch_call:
            gateway=ExecutionGateway(object()).execute(
                cycle.execution_command,state=intent_state
            )
        self.assertEqual(gateway.status,GatewayStatus.RECEIPT)
        kwargs=dispatch_call.call_args.kwargs
        self.assertEqual(kwargs["dispatch_id"],correlation_id)
        self.assertIn("recovery_state",kwargs)
        self.assertEqual(
            kwargs["recovery_authorization"]["corrective_provider"],
            "fallback",
        )

        dispatched_state=apply_dispatch_receipt(
            intent_state,
            surface=gateway.surface,
            action_id=gateway.action_id,
            receipt=gateway.receipt,
        )
        self.assertEqual(
            dispatched_state.diagnostic_recoveries[p.idempotency_key][
                "corrective_dispatch"
            ]["status"],
            "dispatched",
        )

        observe_cycle=controller.run_cycle(
            trigger(),comments=[comment(dispatched_state)],pending=[]
        )
        self.assertEqual(
            observe_cycle.selected_work["kind"],
            "corrective_observation",
        )
        self.assertEqual(
            observe_cycle.execution_command.kind,
            ControllerCommandKind.OBSERVE_CORRECTIVE,
        )
        with patch(
            "chatgpt_operation.controller.execution_gateway.observe_native_plan",
            return_value={
                "status":"MATCHED_TERMINAL",
                "matched_run_ids":[99],
                "conclusion":"success",
            },
        ) as observe_call:
            terminal=ExecutionGateway(object()).execute(
                observe_cycle.execution_command,
                state=dispatched_state,
            )
        self.assertEqual(terminal.status,GatewayStatus.TERMINAL)
        self.assertEqual(terminal.surface,"corrective")
        self.assertEqual(terminal.terminal_run_id,99)
        self.assertEqual(
            observe_call.call_args.kwargs["dispatch_id"],
            correlation_id,
        )

        result=ExecutionResult(
            research_id=state.research_id,
            action_id=p.idempotency_key,
            executor=ExecutorKind.GITHUB_NATIVE,
            status=ExecutionStatus.PASS,
            observation="corrective postcondition verified",
            retryable=False,
            details={
                "after":{"comment_present":True},
                "provenance":{
                    "schema_version":1,
                    "workflow_run_id":99,
                    "run_attempt":1,
                    "head_sha":HEAD,
                    "action_id":p.idempotency_key,
                },
            },
        )
        ingested=ingest_terminal_artifact(
            dispatched_state,
            surface=TerminalSurface.CORRECTIVE,
            run_id=99,
            artifact_text=json.dumps(result.to_dict()),
            gateway_result=terminal.to_dict(),
        )
        self.assertEqual(ingested.outcome,TerminalIngestionOutcome.APPLIED)
        final_state=ingested.proposed_state
        self.assertEqual(
            final_state.diagnostic_recoveries[p.idempotency_key]["status"],
            "resolved",
        )
        self.assertNotIn(
            "corrective_dispatch",
            final_state.diagnostic_recoveries[p.idempotency_key],
        )
        self.assertEqual(
            final_state.action_queue[p.idempotency_key]["status"],
            "pending",
        )

        retry_cycle=controller.run_cycle(
            trigger(),comments=[comment(final_state)],pending=[]
        )
        self.assertEqual(retry_cycle.selected_work["kind"],"action")
        self.assertEqual(
            retry_cycle.execution_command.kind,
            ControllerCommandKind.DISPATCH_ACTION,
        )


if __name__=="__main__":
    unittest.main()
