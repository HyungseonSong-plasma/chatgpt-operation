import copy
import json

from chatgpt_operation.controller.action_plan import ActionPlan, ExecutorKind
from chatgpt_operation.controller.diagnostic import (
    enqueue_suspended_action,
    record_action_dispatch,
    record_action_dispatch_intent,
    record_diagnostic_dispatch,
    record_diagnostic_dispatch_intent,
    record_evidence_dispatch,
    record_evidence_dispatch_intent,
)
from chatgpt_operation.controller.execution import ExecutionResult, ExecutionStatus
from chatgpt_operation.controller.research import ResearchStage, ResearchState
from chatgpt_operation.controller.terminal_ingestion import (
    TerminalIngestionError,
    TerminalIngestionOutcome,
    TerminalSurface,
    ingest_terminal_artifact,
)


HEAD="b"*40
ACTION="a"*64


def action_plan():
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


def dispatched_action():
    p=action_plan()
    state=ResearchState("r","work",stage=ResearchStage.EXECUTE)
    enqueue_suspended_action(state,p)
    record_action_dispatch_intent(
        state,p.idempotency_key,
        workflow="samuel-native-github.yml",ref="main",
        requested_at="2026-09-27T20:00:00Z",expected_head_sha=HEAD,
    )
    record_action_dispatch(state,p.idempotency_key,{
        "workflow_path":".github/workflows/samuel-native-github.yml",
        "ref":"main","correlation_id":p.idempotency_key,"workflow_run_id":99,
    })
    return p,state


def gateway(surface,action_id,run_id,conclusion="success"):
    return {
        "schema_version":1,
        "surface":surface,
        "action_id":action_id,
        "status":"terminal",
        "receipt":None,
        "observation":{
            "status":"MATCHED_TERMINAL",
            "conclusion":conclusion,
        },
        "terminal_run_id":run_id,
    }


def test_action_pass_artifact_completes_dispatched_action():
    p,state=dispatched_action()
    result=ExecutionResult(
        research_id="r",
        action_id=p.idempotency_key,
        executor=ExecutorKind.GITHUB_NATIVE,
        status=ExecutionStatus.PASS,
        observation="verified",
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
    ingestion=ingest_terminal_artifact(
        state,
        surface=TerminalSurface.ACTION,
        run_id=99,
        artifact_text=json.dumps(result.to_dict()),
        gateway_result=gateway("action",p.idempotency_key,99),
    )
    assert ingestion.outcome is TerminalIngestionOutcome.APPLIED
    assert ingestion.proposed_state.action_queue[p.idempotency_key]["status"]=="complete"
    assert state.action_queue[p.idempotency_key]["status"]=="dispatched"


def test_invalid_action_json_retires_physical_attempt_for_safe_retry():
    p,state=dispatched_action()
    ingestion=ingest_terminal_artifact(
        state,
        surface=TerminalSurface.ACTION,
        run_id=99,
        artifact_text='{"broken":true}\n{"extra":true}',
        gateway_result=gateway("action",p.idempotency_key,99,conclusion="failure"),
    )
    assert ingestion.outcome is TerminalIngestionOutcome.RECOVERED_INVALID_EVIDENCE
    item=ingestion.proposed_state.action_queue[p.idempotency_key]
    assert item["status"]=="pending"
    assert item["dispatch_attempt_history"][-1]["workflow_run_id"]==99


def test_action_gateway_run_mismatch_fails_closed():
    p,state=dispatched_action()
    try:
        ingest_terminal_artifact(
            state,
            surface=TerminalSurface.ACTION,
            run_id=99,
            artifact_text="{}",
            gateway_result=gateway("action",p.idempotency_key,100),
        )
    except TerminalIngestionError as exc:
        assert "run_id" in str(exc)
    else:
        raise AssertionError("foreign terminal run must fail closed")


def dispatched_evidence():
    state=ResearchState(
        "r","evidence",stage=ResearchStage.EXECUTE,
        diagnostic_recoveries={
            ACTION:{
                "status":"needs_evidence",
                "evidence_request":{"fingerprint":"fingerprint"},
                "failure":{"details":{}},
            }
        },
    )
    intent,correlation=record_evidence_dispatch_intent(
        state,ACTION,workflow="samuel-evidence-acquisition.yml",ref="main",
        requested_at="2026-09-27T20:00:00Z",expected_head_sha=HEAD,
    )
    record_evidence_dispatch(state,ACTION,{
        "workflow_path":".github/workflows/samuel-evidence-acquisition.yml",
        "ref":"main","correlation_id":correlation,"workflow_run_id":100,
    })
    return state,correlation


def test_evidence_artifact_is_bound_to_gateway_and_dispatch_provenance():
    state,correlation=dispatched_evidence()
    artifact={
        "schema_version":1,
        "action_id":ACTION,
        "evidence":{"available_providers":["repository-actions"]},
        "revision_delta":1,
        "provenance":{
            "schema_version":1,
            "workflow_run_id":100,
            "run_attempt":1,
            "head_sha":HEAD,
            "action_id":ACTION,
            "dispatch_id":correlation,
        },
    }
    ingestion=ingest_terminal_artifact(
        state,
        surface=TerminalSurface.EVIDENCE,
        run_id=100,
        artifact_text=json.dumps(artifact),
        gateway_result=gateway("evidence",ACTION,100),
    )
    recovery=ingestion.proposed_state.diagnostic_recoveries[ACTION]
    assert recovery["status"]=="open"
    assert "evidence_dispatch" not in recovery


def dispatched_diagnostic():
    recovery={
        "status":"open",
        "fingerprint":["failure"],
        "failure":{"details":{"provider":"native","error_type":"HTTPError"}},
        "root_cause":None,
        "corrective_action":None,
        "resolution_evidence":None,
    }
    state=ResearchState(
        "r","diagnose",stage=ResearchStage.EXECUTE,
        diagnostic_recoveries={ACTION:recovery},
    )
    _intent,correlation=record_diagnostic_dispatch_intent(
        state,ACTION,workflow="samuel-diagnostic-recovery.yml",ref="main",
        requested_at="2026-09-27T20:00:00Z",expected_head_sha=HEAD,
    )
    record_diagnostic_dispatch(state,ACTION,{
        "workflow_path":".github/workflows/samuel-diagnostic-recovery.yml",
        "ref":"main","correlation_id":correlation,"workflow_run_id":101,
    })
    return state,correlation


def test_diagnostic_artifact_retires_dispatch_after_provenance_check():
    state,correlation=dispatched_diagnostic()
    patched=copy.deepcopy(state.diagnostic_recoveries[ACTION])
    patched["root_cause"]="provider=native;error_type=HTTPError"
    artifact={
        "action_id":ACTION,
        "phase":"investigate_root_cause",
        "advanced":True,
        "evidence":"typed failure evidence",
        "recovery":patched,
        "revision_delta":1,
        "execution_run_id":None,
        "provenance":{
            "schema_version":1,
            "workflow_run_id":101,
            "run_attempt":1,
            "head_sha":HEAD,
            "action_id":ACTION,
            "dispatch_id":correlation,
        },
    }
    ingestion=ingest_terminal_artifact(
        state,
        surface=TerminalSurface.DIAGNOSTIC,
        run_id=101,
        artifact_text=json.dumps(artifact),
        gateway_result=gateway("diagnostic",ACTION,101),
    )
    recovery=ingestion.proposed_state.diagnostic_recoveries[ACTION]
    assert recovery["root_cause"].startswith("provider=native")
    assert "diagnostic_dispatch" not in recovery
