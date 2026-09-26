from chatgpt_operation.controller.action_plan import ActionPlan, ExecutorKind
from chatgpt_operation.controller.diagnostic import enqueue_suspended_action
from chatgpt_operation.controller.durable_state import apply_action_failure
from chatgpt_operation.controller.execution import ExecutionResult, ExecutionStatus
from chatgpt_operation.controller.research import ResearchStage, ResearchState


def make_plan():
    return ActionPlan.from_dict({"schema_version":1,"research_id":"r","stage":"execute",
        "executor":"github_native","payload":{"action":"comment_issue","repository":"o/r",
        "target":{"issue_number":44},"preconditions":{"state":"open"},
        "desired_postcondition":{"comment_present":True}},"expected_observation":"verified"})


def failed(p):
    return ExecutionResult(research_id="r",action_id=p.idempotency_key,
        executor=ExecutorKind.GITHUB_NATIVE,status=ExecutionStatus.FAILED,
        observation="provider failed",retryable=True,
        details={"provider":"native","error_type":"HTTPError","provider_status":"403"})


def test_second_identical_retryable_failure_suspends_and_opens_diagnosis():
    p=make_plan(); s=ResearchState("r","finish",stage=ResearchStage.EXECUTE)
    enqueue_suspended_action(s,p)
    once=apply_action_failure(s,failed(p))
    assert once.action_queue[p.idempotency_key]["status"]=="pending"
    twice=apply_action_failure(once,failed(p))
    assert twice.action_queue[p.idempotency_key]["status"]=="suspended"
    recovery=twice.diagnostic_recoveries[p.idempotency_key]
    assert recovery["status"]=="open"
    assert recovery["source_plan"]["payload"]==p.payload
