from chatgpt_operation.controller.diagnostic import (
    diagnostic_dispatch_correlation_id,
    record_diagnostic_dispatch,
    record_diagnostic_dispatch_intent,
    resume_diagnostic_dispatch_intent,
    resume_dispatched_diagnostic,
)
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
