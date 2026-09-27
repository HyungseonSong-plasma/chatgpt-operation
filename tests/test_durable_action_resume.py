from chatgpt_operation.controller.action_plan import ActionPlan, ExecutorKind
from chatgpt_operation.controller.diagnostic import (
    complete_queued_action, enqueue_suspended_action,
    mark_action_suspended, resume_resolved_action,
    record_action_dispatch_intent, resume_dispatch_intent,
    record_action_dispatch, resume_dispatched_action,
)
from chatgpt_operation.controller.execution import ExecutionResult, ExecutionStatus
from chatgpt_operation.controller.research import ResearchStage, ResearchState


def plan():
    return ActionPlan.from_dict({
        "schema_version":1,"research_id":"r","stage":"execute","executor":"github_native",
        "payload":{"action":"comment_issue","repository":"o/r","target":{"issue_number":44},
        "preconditions":{"state":"open"},"desired_postcondition":{"comment_present":True}},
        "expected_observation":"verified",
    })


def test_resolved_action_returns_to_pending_and_completes_only_with_evidence():
    p=plan(); s=ResearchState("r","finish",stage=ResearchStage.EXECUTE)
    enqueue_suspended_action(s,p)
    mark_action_suspended(s,p.idempotency_key)
    s.diagnostic_recoveries[p.idempotency_key]={"status":"resolved"}
    resumed=resume_resolved_action(s,p.idempotency_key)
    assert resumed.idempotency_key==p.idempotency_key
    assert s.action_queue[p.idempotency_key]["status"]=="pending"
    result=ExecutionResult(
        research_id="r",action_id=p.idempotency_key,executor=ExecutorKind.GITHUB_NATIVE,
        status=ExecutionStatus.PASS,observation="verified",details={"after":{"comment_present":True}},
    )
    complete_queued_action(s,p.idempotency_key,result)
    assert s.action_queue[p.idempotency_key]["status"]=="complete"


def test_unresolved_action_cannot_resume():
    p=plan(); s=ResearchState("r","finish",stage=ResearchStage.EXECUTE)
    enqueue_suspended_action(s,p); mark_action_suspended(s,p.idempotency_key)
    s.diagnostic_recoveries[p.idempotency_key]={"status":"open"}
    try:
        resume_resolved_action(s,p.idempotency_key)
    except ValueError as exc:
        assert "not resolved" in str(exc)
    else:
        raise AssertionError("open recovery must not resume")


def test_dispatch_receipt_is_durable_and_reentrant_without_redispatch():
    p=plan(); s=ResearchState("r","finish",stage=ResearchStage.EXECUTE)
    enqueue_suspended_action(s,p)
    receipt={
        "workflow":"samuel-native-github.yml",
        "workflow_id":367604874,
        "ref":"main",
        "correlation_id":p.idempotency_key,
        "requested_at":"2026-09-27T12:00:00Z",
        "workflow_run_id":99,
    }
    before=s.revision
    intent=record_action_dispatch_intent(
        s,p.idempotency_key,workflow="samuel-native-github.yml",ref="main",requested_at="2026-09-27T12:00:00Z"
    )
    assert s.revision==before+1
    assert intent.action_id==p.idempotency_key
    planned, persisted_intent=resume_dispatch_intent(s,p.idempotency_key)
    assert planned.idempotency_key==p.idempotency_key
    assert persisted_intent==intent
    receipt["workflow_path"]=".github/workflows/samuel-native-github.yml"
    record_action_dispatch(s,p.idempotency_key,receipt)
    assert s.revision==before+2
    assert s.action_queue[p.idempotency_key]["status"]=="dispatched"
    resumed, persisted=resume_dispatched_action(s,p.idempotency_key)
    assert resumed.idempotency_key==p.idempotency_key
    assert persisted==receipt
    record_action_dispatch(s,p.idempotency_key,receipt)
    assert s.revision==before+2


def test_dispatch_receipt_requires_authoritative_workflow_run_id():
    p=plan(); s=ResearchState("r","finish",stage=ResearchStage.EXECUTE)
    enqueue_suspended_action(s,p)
    record_action_dispatch_intent(
        s,p.idempotency_key,workflow="samuel-native-github.yml",ref="main",
        requested_at="2026-09-27T12:00:00Z"
    )
    try:
        record_action_dispatch(
            s,p.idempotency_key,{
                "correlation_id":p.idempotency_key,
                "ref":"main",
                "workflow_run_id":None,
            },
        )
    except ValueError as exc:
        assert "authoritative workflow_run_id" in str(exc)
    else:
        raise AssertionError("receipt without workflow run identity must fail closed")


def test_dispatch_receipt_rejects_wrong_action_identity():
    p=plan(); s=ResearchState("r","finish",stage=ResearchStage.EXECUTE)
    enqueue_suspended_action(s,p)
    record_action_dispatch_intent(
        s,p.idempotency_key,workflow="samuel-native-github.yml",ref="main",requested_at="2026-09-27T12:00:00Z"
    )
    try:
        record_action_dispatch(
            s,p.idempotency_key,{"correlation_id":"wrong","ref":"main"}
        )
    except ValueError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("wrong dispatch correlation must fail closed")


def test_dispatch_requires_durable_intent_before_external_receipt():
    p=plan(); s=ResearchState("r","finish",stage=ResearchStage.EXECUTE)
    enqueue_suspended_action(s,p)
    receipt={"correlation_id":p.idempotency_key,"ref":"main"}
    try:
        record_action_dispatch(s,p.idempotency_key,receipt)
    except ValueError as exc:
        assert "no durable dispatch intent" in str(exc)
    else:
        raise AssertionError("dispatch receipt without intent must fail closed")


def test_duplicate_enqueue_is_idempotent_but_identity_conflict_is_rejected():
    p=plan(); s=ResearchState("r","finish",stage=ResearchStage.EXECUTE)
    enqueue_suspended_action(s,p)
    before=s.revision
    enqueue_suspended_action(s,p)
    assert s.revision==before
    raw={
        "schema_version":1,"research_id":"r","stage":"execute","executor":"github_native",
        "payload":dict(p.payload),"expected_observation":"verified",
        "decision_risk":{"impact":0.9,"uncertainty":0.2,"irreversibility":0.1},
    }
    conflicting=ActionPlan.from_dict(raw)
    assert conflicting.idempotency_key==p.idempotency_key
    try:
        enqueue_suspended_action(s,conflicting)
    except ValueError as exc:
        assert "different plan" in str(exc)
    else:
        raise AssertionError("same action id with different typed plan must fail closed")


def test_dispatch_intent_is_reentrant_and_conflicting_target_fails_closed():
    p=plan(); s=ResearchState("r","finish",stage=ResearchStage.EXECUTE)
    enqueue_suspended_action(s,p)
    first=record_action_dispatch_intent(
        s,p.idempotency_key,workflow="samuel-native-github.yml",ref="main",requested_at="2026-09-27T12:00:00Z"
    )
    before=s.revision
    second=record_action_dispatch_intent(
        s,p.idempotency_key,workflow="samuel-native-github.yml",ref="main",requested_at="2026-09-27T12:00:00Z"
    )
    assert second==first
    assert s.revision==before
    try:
        record_action_dispatch_intent(
            s,p.idempotency_key,workflow="samuel-native-github.yml",ref="other",requested_at="2026-09-27T12:05:00Z"
        )
    except ValueError as exc:
        assert "conflicts" in str(exc)
    else:
        raise AssertionError("dispatch target drift must fail closed")


def test_dispatch_intent_rejects_invalid_timestamp():
    p=plan(); s=ResearchState("r","finish",stage=ResearchStage.EXECUTE)
    enqueue_suspended_action(s,p)
    try:
        record_action_dispatch_intent(
            s,p.idempotency_key,workflow="samuel-native-github.yml",
            ref="main",requested_at="not-a-time"
        )
    except ValueError as exc:
        assert "ISO-8601" in str(exc)
    else:
        raise AssertionError("invalid dispatch timestamp must fail closed")
