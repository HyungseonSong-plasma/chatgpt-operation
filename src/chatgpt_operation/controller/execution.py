"""Typed executor feedback recorded into persistent research state."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any

from .action_plan import ExecutorKind
from .research import ResearchState, ResearchStateError


ACTION_ID = re.compile(r"^[0-9a-f]{64}$")


class ExecutionResultError(ValueError):
    """Raised when executor feedback violates the typed result contract."""


class ExecutionStatus(str, Enum):
    PASS = "pass"
    NOOP = "noop"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(frozen=True)
class ExecutionResult:
    research_id: str
    action_id: str
    executor: ExecutorKind
    status: ExecutionStatus
    observation: str
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ExecutionResult":
        if not isinstance(raw, dict):
            raise ExecutionResultError("execution result must be an object")
        allowed = {
            "schema_version",
            "research_id",
            "action_id",
            "executor",
            "status",
            "observation",
            "retryable",
            "details",
        }
        required = allowed
        extra = sorted(set(raw) - allowed)
        missing = sorted(required - set(raw))
        if extra:
            raise ExecutionResultError(
                "execution result has unknown fields: " + ", ".join(extra)
            )
        if missing:
            raise ExecutionResultError(
                "execution result missing fields: " + ", ".join(missing)
            )
        if raw["schema_version"] != 1:
            raise ExecutionResultError("schema_version must be 1")

        research_id = raw["research_id"]
        if not isinstance(research_id, str) or not research_id.strip():
            raise ExecutionResultError("research_id must be a non-empty string")

        action_id = raw["action_id"]
        if not isinstance(action_id, str) or not ACTION_ID.fullmatch(action_id):
            raise ExecutionResultError("action_id must be lowercase 64-hex")

        try:
            executor = ExecutorKind(raw["executor"])
        except (TypeError, ValueError) as exc:
            raise ExecutionResultError("executor is unsupported") from exc

        try:
            status = ExecutionStatus(raw["status"])
        except (TypeError, ValueError) as exc:
            raise ExecutionResultError("status is unsupported") from exc

        observation = raw["observation"]
        if not isinstance(observation, str) or not observation.strip():
            raise ExecutionResultError("observation must be a non-empty string")

        retryable = raw["retryable"]
        if not isinstance(retryable, bool):
            raise ExecutionResultError("retryable must be boolean")
        if status in {ExecutionStatus.PASS, ExecutionStatus.NOOP} and retryable:
            raise ExecutionResultError("successful execution cannot be retryable")

        details = raw["details"]
        if not isinstance(details, dict):
            raise ExecutionResultError("details must be an object")

        return cls(
            research_id=research_id.strip(),
            action_id=action_id,
            executor=executor,
            status=status,
            observation=observation.strip(),
            retryable=retryable,
            details=dict(details),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "research_id": self.research_id,
            "action_id": self.action_id,
            "executor": self.executor.value,
            "status": self.status.value,
            "observation": self.observation,
            "retryable": self.retryable,
            "details": dict(self.details),
        }


def record_execution_result(
    state: ResearchState,
    result: ExecutionResult,
) -> bool:
    """Record executor feedback exactly once.

    Identical replay is a no-op. Conflicting feedback for the same action id is a
    hard state error so scheduled retries cannot silently rewrite history.
    """
    if result.research_id != state.research_id:
        raise ResearchStateError(
            f"execution result belongs to {result.research_id}, not {state.research_id}"
        )

    encoded = result.to_dict()
    previous = state.execution_results.get(result.action_id)
    if previous is not None:
        if previous == encoded:
            return False
        previous_result = ExecutionResult.from_dict(previous)
        if previous_result.status is ExecutionStatus.FAILED and previous_result.retryable:
            attempts = list(previous.get("details", {}).get("attempt_history", []))
            attempts.append(previous)
            encoded["details"] = dict(encoded["details"])
            encoded["details"]["attempt_history"] = attempts
            state.execution_results[result.action_id] = encoded
            state.revision += 1
            return True
        raise ResearchStateError(
            f"conflicting execution result for action {result.action_id}"
        )

    state.execution_results[result.action_id] = encoded
    state.revision += 1
    return True


def transition_from_execution(
    state: ResearchState,
    result: ExecutionResult,
    target: ResearchStage,
) -> bool:
    """Apply an execution-driven state transition with typed evidence.

    COMPLETE is evidence-gated: only PASS/NOOP from a recorded executor result
    can authorize it. FAILED/REJECTED evidence can be recorded but cannot be
    promoted to COMPLETE.
    """
    record_execution_result(state, result)
    if target is ResearchStage.COMPLETE and result.status not in {
        ExecutionStatus.PASS,
        ExecutionStatus.NOOP,
    }:
        raise ResearchStateError(
            "COMPLETE requires PASS/NOOP execution evidence"
        )
    return state.apply_once(
        f"execution:{result.action_id}:{target.value}",
        target,
    )
