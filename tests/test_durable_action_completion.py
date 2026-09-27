from chatgpt_operation.controller.action_plan import ActionPlan, ExecutorKind
from chatgpt_operation.controller.diagnostic import (
    enqueue_suspended_action, record_action_dispatch, record_action_dispatch_intent,
)
from chatgpt_operation.controller.durable_state import apply_action_completion
from chatgpt_operation.controller.execution import ExecutionResult, ExecutionStatus
from chatgpt_operation.controller.research import ResearchStage, ResearchState


HEAD_SHA="b"*40


def plan():
    return ActionPlan.from_dict({
        "schema_version":1,"research_id":"r","stage":"execute","executor":"github_native",
        "payload":{"action":"comment_issue","repository":"o/r","target":{"issue_number":44},
        "preconditions":{"state":"open"},"desired_postcondition":{"comment_present":True}},
        "expected_observation":"verified",
    })


def dispatched_state():
    p=plan(); s=ResearchState("r","finish",stage=ResearchStage.EXECUTE,revision=4)
    enqueue_suspended_action(s,p)
    record_action_dispatch_intent(
        s,p.idempotency_key,workflow="samuel-native-github.yml",ref="main",
        requested_at="2026-09-27T12:00:00Z",expected_head_sha=HEAD_SHA,
    )
    record_action_dispatch(s,p.idempotency_key,{
        "workflow_path":".github/workflows/samuel-native-github.yml",
        "ref":"main","correlation_id":p.idempotency_key,
        "workflow_run_id":99,
    })
    return p,s


def result(p,status,run_id=99):
    return ExecutionResult(
        research_id="r", action_id=p.idempotency_key, executor=ExecutorKind.GITHUB_NATIVE,
        status=status, observation="verified",
        details={
            "after":{"ok":True},
            "provenance":{"schema_version":1,"workflow_run_id":run_id,"run_attempt":1,
                          "head_sha":HEAD_SHA,"action_id":p.idempotency_key},
        },
    )


def test_durable_completion_marks_only_matching_dispatched_action():
    p,s=dispatched_state(); before=s.revision
    proposed=apply_action_completion(s,result(p,ExecutionStatus.PASS))
    assert s.action_queue[p.idempotency_key]["status"]=="dispatched"
    assert proposed.action_queue[p.idempotency_key]["status"]=="complete"
    assert proposed.revision==before+1


def test_pending_action_cannot_accept_terminal_result():
    p=plan(); s=ResearchState("r","finish",stage=ResearchStage.EXECUTE)
    enqueue_suspended_action(s,p)
    try:
        apply_action_completion(s,result(p,ExecutionStatus.PASS))
    except ValueError as exc:
        assert "not dispatched" in str(exc)
    else:
        raise AssertionError("undispatched action must not accept completion evidence")


def test_foreign_workflow_provenance_cannot_complete_action():
    p,s=dispatched_state()
    try:
        apply_action_completion(s,result(p,ExecutionStatus.PASS,run_id=100))
    except Exception as exc:
        assert "workflow_run_id mismatch" in str(exc)
    else:
        raise AssertionError("foreign workflow result must fail closed")


def test_failed_receipt_cannot_complete_dispatched_action():
    p,s=dispatched_state()
    try:
        apply_action_completion(s,result(p,ExecutionStatus.FAILED))
    except ValueError as exc:
        assert "PASS/NOOP" in str(exc)
    else:
        raise AssertionError("failed execution must not complete action")
