from chatgpt_operation.controller.diagnostic import (
    record_evidence_dispatch,
    record_evidence_dispatch_intent,
)
from chatgpt_operation.controller.durable_state import (
    DurableStateError,
    apply_evidence_patch,
)
from chatgpt_operation.controller.research import ResearchState


ACTION_ID="a"*64
HEAD="b"*40


def dispatched_state():
    s=ResearchState("r","finish",diagnostic_recoveries={ACTION_ID:{
        "status":"needs_evidence",
        "failure":{"details":{}},
        "evidence_request":{"fingerprint":"f"*64},
    }},revision=3)
    _,correlation_id=record_evidence_dispatch_intent(
        s,ACTION_ID,workflow="samuel-evidence-acquisition.yml",
        ref="feature",requested_at="2026-09-27T19:20:00Z",
        expected_head_sha=HEAD,
    )
    record_evidence_dispatch(s,ACTION_ID,{
        "workflow_path":".github/workflows/samuel-evidence-acquisition.yml",
        "ref":"feature",
        "correlation_id":correlation_id,
        "workflow_run_id":99,
    })
    return s,correlation_id


def artifact(correlation_id,**overrides):
    provenance={
        "schema_version":1,
        "workflow_run_id":99,
        "run_attempt":1,
        "head_sha":HEAD,
        "action_id":ACTION_ID,
        "dispatch_id":correlation_id,
    }
    provenance.update(overrides)
    return {
        "schema_version":1,
        "action_id":ACTION_ID,
        "evidence":{"provider":"native"},
        "controller_state":"ignored",
        "revision_delta":1,
        "provenance":provenance,
    }


def test_evidence_patch_reopens_waiting_diagnostic():
    s,correlation_id=dispatched_state()
    before=s.revision
    p=apply_evidence_patch(s,artifact(correlation_id))
    assert s.diagnostic_recoveries[ACTION_ID]["status"]=="needs_evidence"
    assert p.diagnostic_recoveries[ACTION_ID]["status"]=="open"
    assert p.diagnostic_recoveries[ACTION_ID]["failure"]["details"]["provider"]=="native"
    assert "evidence_dispatch" not in p.diagnostic_recoveries[ACTION_ID]
    assert p.revision==before+1


def test_evidence_patch_rejects_foreign_workflow_run():
    s,correlation_id=dispatched_state()
    try:
        apply_evidence_patch(s,artifact(correlation_id,workflow_run_id=100))
    except DurableStateError as exc:
        assert "workflow_run_id mismatch" in str(exc)
    else:
        raise AssertionError("foreign evidence workflow must fail closed")


def test_evidence_patch_rejects_foreign_source_head():
    s,correlation_id=dispatched_state()
    try:
        apply_evidence_patch(s,artifact(correlation_id,head_sha="c"*40))
    except DurableStateError as exc:
        assert "head_sha mismatch" in str(exc)
    else:
        raise AssertionError("foreign evidence source head must fail closed")


def test_evidence_patch_rejects_foreign_dispatch_identity():
    s,correlation_id=dispatched_state()
    try:
        apply_evidence_patch(s,artifact(correlation_id,dispatch_id="foreign"))
    except DurableStateError as exc:
        assert "dispatch_id mismatch" in str(exc)
    else:
        raise AssertionError("foreign evidence dispatch must fail closed")
