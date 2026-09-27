from chatgpt_operation.controller.diagnostic import (
    evidence_dispatch_correlation_id,
    record_acquired_diagnostic_evidence,
    record_evidence_dispatch,
    record_evidence_dispatch_intent,
    resume_dispatched_evidence,
    resume_evidence_dispatch_intent,
)
from chatgpt_operation.controller.research import ResearchState


ACTION_ID = "a" * 64
HEAD = "b" * 40


def state():
    return ResearchState(
        "r",
        "finish",
        diagnostic_recoveries={
            ACTION_ID: {
                "status": "needs_evidence",
                "failure": {"details": {}},
                "evidence_request": {
                    "phase": "investigate_root_cause",
                    "reason": "missing provider evidence",
                    "fingerprint": "f" * 64,
                },
            }
        },
        revision=3,
    )


def test_evidence_dispatch_intent_is_durable_and_reentrant():
    s = state()
    before = s.revision
    intent, correlation_id = record_evidence_dispatch_intent(
        s,
        ACTION_ID,
        workflow="samuel-evidence-acquisition.yml",
        ref="feature",
        requested_at="2026-09-27T19:20:00Z",
        expected_head_sha=HEAD,
    )
    assert s.revision == before + 1
    assert correlation_id == evidence_dispatch_correlation_id(s, ACTION_ID)
    assert s.diagnostic_recoveries[ACTION_ID]["evidence_dispatch"]["status"] == "dispatch_intent"
    persisted_intent, persisted_correlation = resume_evidence_dispatch_intent(s, ACTION_ID)
    assert persisted_intent == intent
    assert persisted_correlation == correlation_id

    before = s.revision
    second, second_correlation = record_evidence_dispatch_intent(
        s,
        ACTION_ID,
        workflow="samuel-evidence-acquisition.yml",
        ref="feature",
        requested_at="2026-09-27T19:25:00Z",
        expected_head_sha=HEAD,
    )
    assert second == intent
    assert second_correlation == correlation_id
    assert s.revision == before


def test_evidence_dispatch_requires_matching_authoritative_receipt():
    s = state()
    _, correlation_id = record_evidence_dispatch_intent(
        s,
        ACTION_ID,
        workflow="samuel-evidence-acquisition.yml",
        ref="feature",
        requested_at="2026-09-27T19:20:00Z",
        expected_head_sha=HEAD,
    )
    try:
        record_evidence_dispatch(
            s,
            ACTION_ID,
            {
                "correlation_id": correlation_id,
                "ref": "feature",
                "workflow_run_id": None,
            },
        )
    except ValueError as exc:
        assert "authoritative workflow_run_id" in str(exc)
    else:
        raise AssertionError("receipt without workflow run id must fail closed")

    try:
        record_evidence_dispatch(
            s,
            ACTION_ID,
            {
                "correlation_id": "foreign",
                "ref": "feature",
                "workflow_run_id": 99,
            },
        )
    except ValueError as exc:
        assert "correlation mismatch" in str(exc)
    else:
        raise AssertionError("foreign evidence receipt must fail closed")


def test_dispatched_evidence_round_trip_and_consume_clears_transport_state():
    s = state()
    _, correlation_id = record_evidence_dispatch_intent(
        s,
        ACTION_ID,
        workflow="samuel-evidence-acquisition.yml",
        ref="feature",
        requested_at="2026-09-27T19:20:00Z",
        expected_head_sha=HEAD,
    )
    receipt = {
        "workflow_path": ".github/workflows/samuel-evidence-acquisition.yml",
        "ref": "feature",
        "correlation_id": correlation_id,
        "workflow_run_id": 99,
    }
    record_evidence_dispatch(s, ACTION_ID, receipt)
    intent, persisted_correlation, persisted_receipt = resume_dispatched_evidence(s, ACTION_ID)
    assert intent.action_id == ACTION_ID
    assert persisted_correlation == correlation_id
    assert persisted_receipt == receipt
    assert s.diagnostic_recoveries[ACTION_ID]["evidence_dispatch"]["status"] == "dispatched"

    record_acquired_diagnostic_evidence(s, ACTION_ID, {"provider": "repository-actions"})
    recovery = s.diagnostic_recoveries[ACTION_ID]
    assert recovery["status"] == "open"
    assert "evidence_request" not in recovery
    assert "evidence_dispatch" not in recovery
