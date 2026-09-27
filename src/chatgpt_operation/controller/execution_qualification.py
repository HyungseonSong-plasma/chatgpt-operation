"""Reusable deterministic qualification for execution continuation invariants."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable

from .execution import ExecutionResult, ExecutionStatus
from .invariants import ContinuationKind, governed_continuation_from_execution


@dataclass(frozen=True)
class ExecutionQualificationResult:
    case_id: str
    passed: bool
    expected: ContinuationKind
    actual: ContinuationKind
    action_id: str
    retryable: bool


def qualify_execution_continuation(
    *,
    case_id: str,
    result: ExecutionResult,
    expected: ContinuationKind,
    history: Iterable[ExecutionResult] = (),
    repeat_limit: int = 3,
) -> ExecutionQualificationResult:
    """Check typed executor evidence against Samuel's authoritative continuation path."""
    continuation = governed_continuation_from_execution(
        result, history=history, repeat_limit=repeat_limit
    )
    return ExecutionQualificationResult(
        case_id=case_id,
        passed=continuation.kind is expected,
        expected=expected,
        actual=continuation.kind,
        action_id=result.action_id,
        retryable=result.retryable,
    )


def retryable_failure_case(result: ExecutionResult) -> ExecutionQualificationResult:
    if result.status is not ExecutionStatus.FAILED or not result.retryable:
        raise ValueError("retryable failure qualification requires FAILED + retryable=true")
    return qualify_execution_continuation(
        case_id="retryable-execution-failure",
        result=result,
        expected=ContinuationKind.RETRY,
    )
