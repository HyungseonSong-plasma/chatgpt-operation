from chatgpt_operation.controller.execution import (
    ExecutionResult,
    ExecutionResultError,
    record_execution_result,
)
from chatgpt_operation.controller.research import ResearchState, ResearchStateError


ACTION_ID = "a" * 64


def result(**overrides):
    raw = {
        "schema_version": 1,
        "research_id": "r-41",
        "action_id": ACTION_ID,
        "executor": "repository_mutation",
        "status": "pass",
        "observation": "readback matched desired content",
        "retryable": False,
        "details": {"commit_sha": "b" * 40},
    }
    raw.update(overrides)
    return ExecutionResult.from_dict(raw)


def test_execution_result_records_and_persists(tmp_path):
    state = ResearchState("r-41", "automate research")
    assert record_execution_result(state, result())
    assert state.revision == 1

    path = tmp_path / "research.json"
    state.save(path)
    resumed = ResearchState.load(path)

    assert resumed.execution_results[ACTION_ID]["status"] == "pass"
    assert resumed.execution_results[ACTION_ID]["details"]["commit_sha"] == "b" * 40


def test_execution_result_replay_is_idempotent():
    state = ResearchState("r-41", "automate research")
    value = result()
    assert record_execution_result(state, value)
    revision = state.revision
    assert record_execution_result(state, value) is False
    assert state.revision == revision


def test_conflicting_replay_fails_closed():
    state = ResearchState("r-41", "automate research")
    record_execution_result(state, result())
    conflicting = result(
        status="failed",
        observation="postcondition mismatch",
        retryable=True,
    )
    try:
        record_execution_result(state, conflicting)
    except ResearchStateError:
        pass
    else:
        raise AssertionError("conflicting executor history must fail closed")


def test_cross_research_result_is_rejected():
    state = ResearchState("r-41", "automate research")
    try:
        record_execution_result(state, result(research_id="r-other"))
    except ResearchStateError:
        pass
    else:
        raise AssertionError("cross-research result must be rejected")


def test_successful_result_cannot_be_retryable():
    try:
        result(retryable=True)
    except ExecutionResultError:
        pass
    else:
        raise AssertionError("successful result cannot request retry")


def test_failed_result_can_be_retryable():
    value = result(
        status="failed",
        observation="transient runner error",
        retryable=True,
    )
    assert value.retryable is True


def test_action_id_contract_is_enforced():
    try:
        result(action_id="not-a-plan-id")
    except ExecutionResultError:
        pass
    else:
        raise AssertionError("invalid action identity must fail closed")
