from chatgpt_operation.controller.action_plan import ExecutorKind
from chatgpt_operation.controller.durable_state import apply_action_completion
from chatgpt_operation.controller.execution import ExecutionResult, ExecutionStatus
from chatgpt_operation.controller.research import ResearchState


def result(status):
    return ExecutionResult(
        research_id="r", action_id="a", executor=ExecutorKind.GITHUB_NATIVE,
        status=status, observation="verified", details={"after":{"ok":True}},
    )


def test_durable_completion_marks_only_matching_pending_action():
    s=ResearchState("r","finish",action_queue={"a":{"status":"pending","plan":{}}},revision=4)
    p=apply_action_completion(s,result(ExecutionStatus.PASS))
    assert s.action_queue["a"]["status"]=="pending"
    assert p.action_queue["a"]["status"]=="complete"
    assert p.revision==5


def test_failed_receipt_cannot_remove_pending_action():
    s=ResearchState("r","finish",action_queue={"a":{"status":"pending","plan":{}}})
    try:
        apply_action_completion(s,result(ExecutionStatus.FAILED))
    except ValueError as exc:
        assert "PASS/NOOP" in str(exc)
    else:
        raise AssertionError("failed execution must remain pending")
