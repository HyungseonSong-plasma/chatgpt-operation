from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.controller.diagnostic import (
    enqueue_suspended_action,
    record_action_dispatch_intent,
    record_diagnostic_dispatch_intent,
    record_evidence_dispatch_intent,
)
from chatgpt_operation.controller.durable_state import (
    DurableStateError,
    apply_dispatch_receipt,
)
from chatgpt_operation.controller.research import ResearchStage, ResearchState


HEAD="b"*40
ACTION="a"*64


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


def test_action_receipt_binding_is_one_immutable_revision():
    p=plan()
    state=ResearchState("r","work",stage=ResearchStage.EXECUTE)
    enqueue_suspended_action(state,p)
    record_action_dispatch_intent(
        state,p.idempotency_key,
        workflow="samuel-native-github.yml",ref="main",
        requested_at="2026-09-27T20:00:00Z",expected_head_sha=HEAD,
    )
    before=state.revision
    receipt={
        "workflow_path":".github/workflows/samuel-native-github.yml",
        "ref":"main","correlation_id":p.idempotency_key,"workflow_run_id":99,
    }
    proposed=apply_dispatch_receipt(
        state,surface="action",action_id=p.idempotency_key,receipt=receipt
    )
    assert state.action_queue[p.idempotency_key]["status"]=="dispatch_intent"
    assert proposed.action_queue[p.idempotency_key]["status"]=="dispatched"
    assert proposed.revision==before+1


def test_evidence_receipt_binding_uses_same_state_kernel():
    state=ResearchState(
        "r","evidence",stage=ResearchStage.EXECUTE,
        diagnostic_recoveries={
            ACTION:{
                "status":"needs_evidence",
                "evidence_request":{"fingerprint":"f"},
            }
        },
    )
    _,correlation=record_evidence_dispatch_intent(
        state,ACTION,workflow="samuel-evidence-acquisition.yml",ref="main",
        requested_at="2026-09-27T20:00:00Z",expected_head_sha=HEAD,
    )
    receipt={
        "workflow_path":".github/workflows/samuel-evidence-acquisition.yml",
        "ref":"main","correlation_id":correlation,"workflow_run_id":100,
    }
    proposed=apply_dispatch_receipt(
        state,surface="evidence",action_id=ACTION,receipt=receipt
    )
    dispatch=proposed.diagnostic_recoveries[ACTION]["evidence_dispatch"]
    assert dispatch["status"]=="dispatched"
    assert dispatch["receipt"]==receipt


def test_diagnostic_receipt_binding_uses_same_state_kernel():
    state=ResearchState(
        "r","diagnose",stage=ResearchStage.EXECUTE,
        diagnostic_recoveries={
            ACTION:{
                "status":"open",
                "failure":{"details":{"provider":"native","error_type":"HTTPError"}},
                "root_cause":None,
                "corrective_action":None,
                "resolution_evidence":None,
            }
        },
    )
    _,correlation=record_diagnostic_dispatch_intent(
        state,ACTION,workflow="samuel-diagnostic-recovery.yml",ref="main",
        requested_at="2026-09-27T20:00:00Z",expected_head_sha=HEAD,
    )
    receipt={
        "workflow_path":".github/workflows/samuel-diagnostic-recovery.yml",
        "ref":"main","correlation_id":correlation,"workflow_run_id":101,
    }
    proposed=apply_dispatch_receipt(
        state,surface="diagnostic",action_id=ACTION,receipt=receipt
    )
    dispatch=proposed.diagnostic_recoveries[ACTION]["diagnostic_dispatch"]
    assert dispatch["status"]=="dispatched"
    assert dispatch["receipt"]==receipt


def test_unknown_receipt_surface_fails_closed():
    state=ResearchState("r","work")
    try:
        apply_dispatch_receipt(
            state,surface="invented",action_id=ACTION,receipt={}
        )
    except DurableStateError as exc:
        assert "unsupported dispatch receipt surface" in str(exc)
    else:
        raise AssertionError("unknown receipt surface must fail closed")
