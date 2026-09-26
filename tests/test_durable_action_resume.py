from chatgpt_operation.controller.action_plan import ActionPlan, ExecutorKind
from chatgpt_operation.controller.diagnostic import (
    complete_queued_action, enqueue_suspended_action,
    mark_action_suspended, resume_resolved_action,
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
