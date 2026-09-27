from chatgpt_operation.controller.action_plan import ActionPlan, ExecutorKind
from chatgpt_operation.controller.diagnostic import (
    complete_queued_action, enqueue_suspended_action,
    mark_action_suspended, resume_resolved_action,
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
        "workflow_run_id":None,
    }
    before=s.revision
    record_action_dispatch(s,p.idempotency_key,receipt)
    assert s.revision==before+1
    assert s.action_queue[p.idempotency_key]["status"]=="dispatched"
    resumed, persisted=resume_dispatched_action(s,p.idempotency_key)
    assert resumed.idempotency_key==p.idempotency_key
    assert persisted==receipt
    record_action_dispatch(s,p.idempotency_key,receipt)
    assert s.revision==before+1


def test_dispatch_receipt_rejects_wrong_action_identity():
    p=plan(); s=ResearchState("r","finish",stage=ResearchStage.EXECUTE)
    enqueue_suspended_action(s,p)
    try:
        record_action_dispatch(s,p.idempotency_key,{"correlation_id":"wrong"})
    except ValueError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("wrong dispatch correlation must fail closed")
