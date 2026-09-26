"""Adversarial regressions for Samuel controller governance and liveness."""
import pytest

from chatgpt_operation.controller.execution import ExecutionResult
from chatgpt_operation.controller.invariants import (
    Continuation,
    ContinuationKind,
    ControllerInvariantError,
    SkillEvidence,
    continuation_from_execution,
    require_single_continuation,
    require_skill_governance,
)
from chatgpt_operation.controller.research import ResearchStage, ResearchState


def execution(**overrides):
    raw = {
        "schema_version": 1,
        "research_id": "attack-suite",
        "action_id": "a" * 64,
        "executor": "github_native",
        "status": "failed",
        "observation": "transient executor failure",
        "retryable": True,
        "details": {},
    }
    raw.update(overrides)
    return ExecutionResult.from_dict(raw)


def test_attack_1_material_action_cannot_bypass_required_skill():
    with pytest.raises(ControllerInvariantError, match="bypassed"):
        require_skill_governance(
            required_contracts=("decision-guard", "github-native-dispatch"),
            evidence=(),
        )


def test_attack_2_loaded_only_skill_evidence_cannot_fake_governance():
    forged = SkillEvidence(
        contract="github-native-dispatch",
        contract_loaded=True,
        contract_executed=False,
        contract_passed=False,
    )
    with pytest.raises(ControllerInvariantError, match="did not pass"):
        require_skill_governance(
            required_contracts=("github-native-dispatch",),
            evidence=(forged,),
        )


def test_attack_3_nonterminal_controller_cannot_silently_stop():
    state = ResearchState("attack-suite", "break controller", stage=ResearchStage.EXECUTE)
    with pytest.raises(ControllerInvariantError, match="exactly one continuation"):
        require_single_continuation(state, ())


def test_attack_4_controller_cannot_emit_conflicting_next_and_retry_paths():
    state = ResearchState("attack-suite", "break controller", stage=ResearchStage.EXECUTE)
    with pytest.raises(ControllerInvariantError, match="exactly one continuation"):
        require_single_continuation(
            state,
            (
                Continuation(ContinuationKind.NEXT_ACTION, "advance"),
                Continuation(ContinuationKind.RETRY, "retry"),
            ),
        )


def test_attack_5_retryable_executor_failure_must_become_explicit_retry():
    state = ResearchState("attack-suite", "break controller", stage=ResearchStage.EXECUTE)
    continuation = continuation_from_execution(execution())
    assert continuation.kind is ContinuationKind.RETRY
    assert require_single_continuation(state, (continuation,)) == continuation


def test_nonretryable_failure_is_explicitly_blocked():
    continuation = continuation_from_execution(
        execution(retryable=False, observation="permanent postcondition failure")
    )
    assert continuation.kind is ContinuationKind.BLOCKED


def test_complete_state_rejects_followup_work():
    state = ResearchState("attack-suite", "done", stage=ResearchStage.COMPLETE)
    with pytest.raises(ControllerInvariantError):
        require_single_continuation(
            state,
            (Continuation(ContinuationKind.NEXT_ACTION, "should not run"),),
        )
