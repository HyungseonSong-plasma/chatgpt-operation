"""Typed executor feedback recorded into persistent research state."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any

from .action_plan import ExecutorKind
from .research import ResearchStage, ResearchState, ResearchStateError


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
        execution_evidence=True,
    )


def open_diagnostic_recovery(
    state: ResearchState,
    result: ExecutionResult,
    *,
    fingerprint: tuple[str, ...],
) -> None:
    """Persist a loop break before the failed action can execute again."""
    state.diagnostic_recoveries[result.action_id] = {
        "status": "open",
        "fingerprint": list(fingerprint),
        "failure": result.to_dict(),
        "root_cause": None,
        "corrective_action": None,
        "resolution_evidence": None,
    }
    state.revision += 1


def resolve_diagnostic_recovery(
    state: ResearchState,
    action_id: str,
    *,
    root_cause: str,
    corrective_action: str,
    resolution_evidence: str,
) -> None:
    recovery = state.diagnostic_recoveries.get(action_id)
    if recovery is None or recovery.get("status") != "open":
        raise ResearchStateError("no open diagnostic recovery for action")
    values=(root_cause, corrective_action, resolution_evidence)
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ResearchStateError("diagnostic resolution requires root cause, corrective action, and evidence")
    recovery.update({
        "status": "resolved",
        "root_cause": root_cause.strip(),
        "corrective_action": corrective_action.strip(),
        "resolution_evidence": resolution_evidence.strip(),
    })
    state.revision += 1


def require_action_recoverable(state: ResearchState, action_id: str) -> None:
    """Forbid replay while diagnosis is open."""
    recovery = state.diagnostic_recoveries.get(action_id)
    if recovery is not None and recovery.get("status") == "open":
        raise ResearchStateError(
            f"action {action_id} is suspended pending diagnostic recovery"
        )


def diagnostic_next_action(state: ResearchState, action_id: str) -> dict[str, Any]:
    """Return the only permitted next recovery action for a suspended execution."""
    recovery = state.diagnostic_recoveries.get(action_id)
    if recovery is None or recovery.get("status") != "open":
        raise ResearchStateError("no open diagnostic recovery for action")
    if not recovery.get("root_cause"):
        return {
            "kind": "investigate_root_cause",
            "action_id": action_id,
            "failure": recovery["failure"],
            "fingerprint": recovery["fingerprint"],
        }
    if not recovery.get("corrective_action"):
        return {
            "kind": "apply_corrective_action",
            "action_id": action_id,
            "root_cause": recovery["root_cause"],
        }
    if not recovery.get("resolution_evidence"):
        return {
            "kind": "verify_resolution",
            "action_id": action_id,
            "root_cause": recovery["root_cause"],
            "corrective_action": recovery["corrective_action"],
        }
    raise ResearchStateError("open diagnostic recovery has inconsistent completed fields")


def record_diagnostic_root_cause(
    state: ResearchState, action_id: str, root_cause: str
) -> None:
    recovery = state.diagnostic_recoveries.get(action_id)
    if recovery is None or recovery.get("status") != "open":
        raise ResearchStateError("no open diagnostic recovery for action")
    if not isinstance(root_cause, str) or not root_cause.strip():
        raise ResearchStateError("root cause evidence is required")
    recovery["root_cause"] = root_cause.strip()
    state.revision += 1


def record_diagnostic_corrective_action(
    state: ResearchState, action_id: str, corrective_action: str
) -> None:
    recovery = state.diagnostic_recoveries.get(action_id)
    if recovery is None or recovery.get("status") != "open" or not recovery.get("root_cause"):
        raise ResearchStateError("root cause must be established before corrective action")
    if not isinstance(corrective_action, str) or not corrective_action.strip():
        raise ResearchStateError("corrective action evidence is required")
    recovery["corrective_action"] = corrective_action.strip()
    state.revision += 1


def record_diagnostic_resolution(
    state: ResearchState, action_id: str, resolution_evidence: str
) -> None:
    recovery = state.diagnostic_recoveries.get(action_id)
    if (
        recovery is None
        or recovery.get("status") != "open"
        or not recovery.get("root_cause")
        or not recovery.get("corrective_action")
    ):
        raise ResearchStateError("corrective action must precede resolution verification")
    if not isinstance(resolution_evidence, str) or not resolution_evidence.strip():
        raise ResearchStateError("resolution evidence is required")
    recovery["resolution_evidence"] = resolution_evidence.strip()
    recovery["status"] = "resolved"
    state.revision += 1
