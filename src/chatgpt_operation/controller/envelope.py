"""Bounded reasoning context built from durable decisions and implementation state."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .decisions import ArchitectureDecision, DecisionRegistry
from .implementation import ImplementationState


class ReasoningEnvelopeError(ValueError):
    pass


@dataclass(frozen=True)
class ReasoningEnvelope:
    goal: str
    observations: tuple[str, ...]
    locked_decisions: tuple[ArchitectureDecision, ...]
    implementation_gaps: tuple[str, ...]
    allowed_reasoning_operations: tuple[str, ...]
    required_outputs: tuple[str, ...]
    escalation_constraints: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.goal.strip():
            raise ReasoningEnvelopeError("goal must be non-empty")
        if not self.allowed_reasoning_operations:
            raise ReasoningEnvelopeError("allowed_reasoning_operations must not be empty")
        if not self.required_outputs:
            raise ReasoningEnvelopeError("required_outputs must not be empty")

    def as_reasoning_context(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "observations": list(self.observations),
            "locked_decisions": [
                {
                    "decision_id": item.decision_id,
                    "version": item.version,
                    "statement": item.statement,
                    "invariants": list(item.invariants),
                }
                for item in self.locked_decisions
            ],
            "implementation_gaps": list(self.implementation_gaps),
            "allowed_reasoning_operations": list(self.allowed_reasoning_operations),
            "required_outputs": list(self.required_outputs),
            "escalation_constraints": list(self.escalation_constraints),
        }


def build_reasoning_envelope(
    *,
    goal: str,
    observations: tuple[str, ...],
    registry: DecisionRegistry,
    implementation: ImplementationState,
    required_capabilities: tuple[str, ...],
    allowed_reasoning_operations: tuple[str, ...],
    required_outputs: tuple[str, ...],
    escalation_constraints: tuple[str, ...] = (),
) -> ReasoningEnvelope:
    locked = registry.accepted()
    if not locked:
        raise ReasoningEnvelopeError("reasoning requires at least one accepted locked decision")
    return ReasoningEnvelope(
        goal=goal,
        observations=observations,
        locked_decisions=locked,
        implementation_gaps=implementation.gaps(required_capabilities),
        allowed_reasoning_operations=allowed_reasoning_operations,
        required_outputs=required_outputs,
        escalation_constraints=escalation_constraints,
    )
