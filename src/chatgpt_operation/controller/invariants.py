"""Fail-closed governance and liveness invariants for Samuel controller cycles."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .execution import ExecutionResult, ExecutionStatus
from .research import ResearchStage, ResearchState


class ControllerInvariantError(ValueError):
    pass


class ContinuationKind(str, Enum):
    NEXT_ACTION = "next_action"
    RETRY = "retry"
    SCHEDULED_WAKEUP = "scheduled_wakeup"
    HUMAN_DECISION_REQUIRED = "human_decision_required"
    BLOCKED = "blocked"
    COMPLETE = "complete"


@dataclass(frozen=True)
class SkillEvidence:
    contract: str
    contract_loaded: bool
    contract_executed: bool
    contract_passed: bool


@dataclass(frozen=True)
class Continuation:
    kind: ContinuationKind
    reason: str
    execution_evidence: ExecutionResult | None = None


def require_skill_governance(
    *,
    required_contracts: Iterable[str],
    evidence: Iterable[SkillEvidence],
) -> None:
    """Reject material work unless every required Skill contract actually passed."""
    required = set(required_contracts)
    by_name = {item.contract: item for item in evidence}
    missing = sorted(required - set(by_name))
    if missing:
        raise ControllerInvariantError(
            "material action bypassed required Skill contracts: " + ", ".join(missing)
        )
    failed = sorted(
        name for name in required
        if not (
            by_name[name].contract_loaded
            and by_name[name].contract_executed
            and by_name[name].contract_passed
        )
    )
    if failed:
        raise ControllerInvariantError(
            "required Skill contracts did not pass: " + ", ".join(failed)
        )


def require_single_continuation(
    state: ResearchState,
    continuations: Iterable[Continuation],
) -> Continuation:
    """A non-terminal cycle may never end silently or ambiguously."""
    values = tuple(continuations)
    if state.stage is ResearchStage.COMPLETE:
        if values:
            raise ControllerInvariantError("complete research cannot schedule continuation")
        return Continuation(ContinuationKind.COMPLETE, "research is complete")
    if len(values) != 1:
        raise ControllerInvariantError(
            f"non-terminal research requires exactly one continuation, got {len(values)}"
        )
    if not values[0].reason.strip():
        raise ControllerInvariantError("continuation requires a non-empty reason")
    if values[0].kind in {ContinuationKind.RETRY, ContinuationKind.BLOCKED}:
        evidence = values[0].execution_evidence
        if evidence is None:
            raise ControllerInvariantError(
                f"{values[0].kind.value} requires typed execution evidence"
            )
        expected = continuation_from_execution(evidence).kind
        if expected is not values[0].kind:
            raise ControllerInvariantError(
                f"{values[0].kind.value} conflicts with execution evidence"
            )
    return values[0]


def continuation_from_execution(result: ExecutionResult) -> Continuation:
    """Translate executor feedback into an explicit liveness outcome."""
    if result.status in {ExecutionStatus.PASS, ExecutionStatus.NOOP}:
        return Continuation(ContinuationKind.NEXT_ACTION, result.observation, result)
    if result.status is ExecutionStatus.FAILED and result.retryable:
        return Continuation(ContinuationKind.RETRY, result.observation, result)
    if result.status is ExecutionStatus.REJECTED:
        return Continuation(ContinuationKind.BLOCKED, result.observation, result)
    if result.status is ExecutionStatus.FAILED:
        return Continuation(ContinuationKind.BLOCKED, result.observation, result)
    raise ControllerInvariantError(f"unsupported execution status: {result.status}")
