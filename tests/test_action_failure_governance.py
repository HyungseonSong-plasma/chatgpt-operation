from chatgpt_operation.controller.action_plan import ActionPlan, ExecutorKind
from chatgpt_operation.controller.diagnostic import (
    enqueue_suspended_action, record_action_dispatch, record_action_dispatch_intent,
)
from chatgpt_operation.controller.durable_state import apply_action_failure
from chatgpt_operation.controller.execution import ExecutionResult, ExecutionStatus
from chatgpt_operation.controller.research import ResearchStage, ResearchState


HEAD_SHA="b"*40


def make_plan():
    return ActionPlan.from_dict({"schema_version":1,"research_id":"r","stage":"execute",
        "executor":"github_native","payload":{"action":"comment_issue","repository":"o/r",
        "target":{"issue_number":44},"preconditions":{"state":"open"},
        "desired_postcondition":{"comment_present":True}},"expected_observation":"verified"})


def dispatch(s,p,run_id):
    record_action_dispatch_intent(
        s,p.idempotency_key,workflow="samuel-native-github.yml",ref="main",
        requested_at=f"2026-09-27T12:{run_id % 60:02d}:00Z",expected_head_sha=HEAD_SHA,
    )
    record_action_dispatch(s,p.idempotency_key,{
        "workflow_path":".github/workflows/samuel-native-github.yml",
        "ref":"main","correlation_id":p.idempotency_key,"workflow_run_id":run_id,
    })


def failed(p,run_id,retryable=True):
    return ExecutionResult(research_id="r",action_id=p.idempotency_key,
        executor=ExecutorKind.GITHUB_NATIVE,status=ExecutionStatus.FAILED,
        observation="provider failed",retryable=retryable,
        details={"provider":"native","error_type":"HTTPError","provider_status":"403",
                 "provenance":{"schema_version":1,"workflow_run_id":run_id,"run_attempt":1,
                               "head_sha":HEAD_SHA,"action_id":p.idempotency_key}})


def test_first_retryable_failure_returns_action_to_clean_pending_state():
    p=make_plan(); s=ResearchState("r","finish",stage=ResearchStage.EXECUTE)
    enqueue_suspended_action(s,p); dispatch(s,p,99)
    once=apply_action_failure(s,failed(p,99))
    item=once.action_queue[p.idempotency_key]
    assert item["status"]=="pending"
    assert "dispatch_intent" not in item
    assert "dispatch_receipt" not in item


def test_second_identical_retryable_failure_suspends_and_opens_diagnosis():
    p=make_plan(); s=ResearchState("r","finish",stage=ResearchStage.EXECUTE)
    enqueue_suspended_action(s,p); dispatch(s,p,99)
    once=apply_action_failure(s,failed(p,99))
    dispatch(once,p,100)
    twice=apply_action_failure(once,failed(p,100))
    assert twice.action_queue[p.idempotency_key]["status"]=="suspended"
    recovery=twice.diagnostic_recoveries[p.idempotency_key]
    assert recovery["status"]=="open"
    assert recovery["source_plan"]["payload"]==p.payload


def test_failure_from_foreign_workflow_is_rejected():
    p=make_plan(); s=ResearchState("r","finish",stage=ResearchStage.EXECUTE)
    enqueue_suspended_action(s,p); dispatch(s,p,99)
    try:
        apply_action_failure(s,failed(p,100))
    except Exception as exc:
        assert "workflow_run_id mismatch" in str(exc)
    else:
        raise AssertionError("foreign workflow failure must fail closed")
