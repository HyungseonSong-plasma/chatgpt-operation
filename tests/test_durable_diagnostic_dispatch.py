from chatgpt_operation.controller.diagnostic import (
    diagnostic_dispatch_correlation_id,
    record_diagnostic_dispatch,
    record_diagnostic_dispatch_intent,
    resume_diagnostic_dispatch_intent,
    resume_dispatched_diagnostic,
)
from chatgpt_operation.controller.durable_state import apply_diagnostic_patch
from chatgpt_operation.controller.research import ResearchState


ACTION = "a" * 64
HEAD = "b" * 40


def state():
    return ResearchState(
        "r",
        "recover",
        diagnostic_recoveries={
            ACTION: {
                "status": "open",
                "fingerprint": ["failure"],
                "failure": {
                    "details": {
                        "provider": "native",
                        "error_type": "HTTPError",
                    }
                },
                "root_cause": None,
                "corrective_action": None,
                "resolution_evidence": None,
            }
        },
    )


def test_diagnostic_dispatch_intent_is_durable_and_reentrant():
    s=state()
    before=s.revision
    intent,correlation=record_diagnostic_dispatch_intent(
        s,ACTION,workflow="samuel-diagnostic-recovery.yml",ref="main",
        requested_at="2026-09-27T19:00:00Z",expected_head_sha=HEAD,
    )
    assert correlation==diagnostic_dispatch_correlation_id(s,ACTION)
    assert s.revision==before+1
    resumed,resumed_correlation=resume_diagnostic_dispatch_intent(s,ACTION)
    assert resumed==intent
    assert resumed_correlation==correlation
    before=s.revision
    same,same_correlation=record_diagnostic_dispatch_intent(
        s,ACTION,workflow="samuel-diagnostic-recovery.yml",ref="main",
        requested_at="2026-09-27T19:00:00Z",expected_head_sha=HEAD,
    )
    assert same==intent
    assert same_correlation==correlation
    assert s.revision==before


def test_diagnostic_dispatch_requires_authoritative_run_identity():
    s=state()
    _,correlation=record_diagnostic_dispatch_intent(
        s,ACTION,workflow="samuel-diagnostic-recovery.yml",ref="main",
        requested_at="2026-09-27T19:00:00Z",expected_head_sha=HEAD,
    )
    try:
        record_diagnostic_dispatch(
            s,ACTION,{
                "correlation_id":correlation,
                "ref":"main",
                "workflow_run_id":None,
            },
        )
    except ValueError as exc:
        assert "authoritative workflow_run_id" in str(exc)
    else:
        raise AssertionError("unbound diagnostic receipt must fail closed")


def test_dispatched_diagnostic_round_trip_preserves_identity():
    s=state()
    intent,correlation=record_diagnostic_dispatch_intent(
        s,ACTION,workflow="samuel-diagnostic-recovery.yml",ref="main",
        requested_at="2026-09-27T19:00:00Z",expected_head_sha=HEAD,
    )
    receipt={
        "workflow_path":".github/workflows/samuel-diagnostic-recovery.yml",
        "ref":"main",
        "correlation_id":correlation,
        "workflow_run_id":99,
    }
    record_diagnostic_dispatch(s,ACTION,receipt)
    resumed_intent,resumed_correlation,resumed_receipt=resume_dispatched_diagnostic(s,ACTION)
    assert resumed_intent==intent
    assert resumed_correlation==correlation
    assert resumed_receipt==receipt


def dispatched_state():
    s=state()
    _,correlation=record_diagnostic_dispatch_intent(
        s,ACTION,workflow="samuel-diagnostic-recovery.yml",ref="main",
        requested_at="2026-09-27T19:00:00Z",expected_head_sha=HEAD,
    )
    receipt={
        "workflow_path":".github/workflows/samuel-diagnostic-recovery.yml",
        "ref":"main","correlation_id":correlation,"workflow_run_id":99,
    }
    record_diagnostic_dispatch(s,ACTION,receipt)
    return s,correlation


def diagnostic_artifact(correlation, run_id=99):
    return {
        "schema_version":1,
        "action_id":ACTION,
        "phase":"investigate_root_cause",
        "advanced":True,
        "evidence":"typed failure",
        "revision_delta":1,
        "execution_run_id":None,
        "recovery":{
            "status":"open",
            "fingerprint":["failure"],
            "failure":{"details":{"provider":"native","error_type":"HTTPError"}},
            "root_cause":"provider=native;error_type=HTTPError",
            "corrective_action":None,
            "resolution_evidence":None,
        },
        "provenance":{
            "schema_version":1,
            "workflow_run_id":run_id,
            "run_attempt":1,
            "head_sha":HEAD,
            "action_id":ACTION,
            "dispatch_id":correlation,
        },
    }


def test_diagnostic_patch_requires_matching_dispatch_provenance():
    s,correlation=dispatched_state()
    proposed=apply_diagnostic_patch(s,diagnostic_artifact(correlation))
    recovery=proposed.diagnostic_recoveries[ACTION]
    assert recovery["root_cause"]=="provider=native;error_type=HTTPError"
    assert "diagnostic_dispatch" not in recovery


def test_diagnostic_patch_rejects_foreign_workflow_run():
    s,correlation=dispatched_state()
    try:
        apply_diagnostic_patch(s,diagnostic_artifact(correlation,run_id=100))
    except Exception as exc:
        assert "workflow_run_id mismatch" in str(exc)
    else:
        raise AssertionError("foreign diagnostic artifact must fail closed")
