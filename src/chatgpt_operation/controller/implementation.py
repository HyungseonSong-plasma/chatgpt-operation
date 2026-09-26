"""Typed implementation status kept separate from accepted architecture decisions."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ImplementationStateError(ValueError):
    pass


class CapabilityStatus(str, Enum):
    PLANNED = "planned"
    PARTIAL = "partial"
    IMPLEMENTED = "implemented"
    VERIFIED = "verified"
    DEPRECATED = "deprecated"


@dataclass(frozen=True)
class Capability:
    name: str
    status: CapabilityStatus
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ImplementationStateError("capability name must be non-empty")
        if self.status is CapabilityStatus.VERIFIED and not self.evidence:
            raise ImplementationStateError("verified capability requires evidence")


@dataclass
class ImplementationState:
    capabilities: dict[str, Capability] = field(default_factory=dict)

    def record(self, capability: Capability) -> None:
        self.capabilities[capability.name] = capability

    def get(self, name: str) -> Capability:
        try:
            return self.capabilities[name]
        except KeyError as exc:
            raise ImplementationStateError(f"unknown capability: {name}") from exc

    def gaps(self, required: tuple[str, ...]) -> tuple[str, ...]:
        complete = {CapabilityStatus.IMPLEMENTED, CapabilityStatus.VERIFIED}
        return tuple(
            name for name in required
            if name not in self.capabilities or self.capabilities[name].status not in complete
        )
