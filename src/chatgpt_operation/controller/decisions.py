"""Durable, versioned architecture decisions and fail-closed decision guards."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import json
from pathlib import Path
from typing import Any


class DecisionError(ValueError):
    pass


class DecisionStatus(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class ArchitectureDecision:
    decision_id: str
    version: int
    status: DecisionStatus
    statement: str
    invariants: tuple[str, ...]
    evidence: tuple[str, ...] = ()
    accepted_at: str | None = None
    supersedes: int | None = None
    revision_policy: str = "explicit_revision"

    def __post_init__(self) -> None:
        if not self.decision_id.strip() or not self.statement.strip():
            raise DecisionError("decision_id and statement must be non-empty")
        if self.version < 1:
            raise DecisionError("decision version must be >= 1")
        if not self.invariants:
            raise DecisionError("decision must define at least one invariant")
        if self.status is DecisionStatus.ACCEPTED and not self.accepted_at:
            raise DecisionError("accepted decision requires accepted_at")
        if self.supersedes is not None and self.supersedes >= self.version:
            raise DecisionError("supersedes must reference an older version")


@dataclass
class DecisionRegistry:
    decisions: dict[str, list[ArchitectureDecision]] = field(default_factory=dict)

    def register(self, decision: ArchitectureDecision) -> None:
        versions = self.decisions.setdefault(decision.decision_id, [])
        if any(item.version == decision.version for item in versions):
            raise DecisionError("decision versions are immutable")
        if versions and decision.version != max(item.version for item in versions) + 1:
            raise DecisionError("decision revision must increment version by one")
        if versions and decision.supersedes != max(item.version for item in versions):
            raise DecisionError("revision must explicitly supersede the current version")
        versions.append(decision)

    def current(self, decision_id: str) -> ArchitectureDecision:
        versions = self.decisions.get(decision_id, [])
        if not versions:
            raise DecisionError(f"unknown decision: {decision_id}")
        return max(versions, key=lambda item: item.version)

    def accepted(self) -> tuple[ArchitectureDecision, ...]:
        return tuple(
            current for key in sorted(self.decisions)
            if (current := self.current(key)).status is DecisionStatus.ACCEPTED
        )

    def save(self, path: str | Path) -> None:
        payload = {
            key: [
                {**asdict(item), "status": item.status.value}
                for item in sorted(items, key=lambda value: value.version)
            ]
            for key, items in sorted(self.decisions.items())
        }
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(target)

    @classmethod
    def load(cls, path: str | Path) -> "DecisionRegistry":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        registry = cls()
        for key in sorted(raw):
            for item in raw[key]:
                registry.register(ArchitectureDecision(
                    decision_id=item["decision_id"],
                    version=int(item["version"]),
                    status=DecisionStatus(item["status"]),
                    statement=item["statement"],
                    invariants=tuple(item["invariants"]),
                    evidence=tuple(item.get("evidence", ())),
                    accepted_at=item.get("accepted_at"),
                    supersedes=item.get("supersedes"),
                    revision_policy=item.get("revision_policy", "explicit_revision"),
                ))
        return registry


class GuardOutcome(str, Enum):
    CONTINUE = "continue"
    IMPLEMENT_GAP = "implement_gap"
    REVISION_REQUIRED = "revision_required"
    REJECTED = "rejected"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ReasoningProposal:
    operation: str
    decision_id: str | None = None
    compatible_with_locked_decisions: bool = True
    revision_requested: bool = False


@dataclass(frozen=True)
class GuardResult:
    outcome: GuardOutcome
    reason: str


class DecisionGuard:
    def validate(
        self,
        proposal: ReasoningProposal,
        locked_decisions: tuple[ArchitectureDecision, ...],
        implementation_gaps: tuple[str, ...] = (),
    ) -> GuardResult:
        locked_ids = {item.decision_id for item in locked_decisions}
        if proposal.decision_id and proposal.decision_id not in locked_ids:
            return GuardResult(GuardOutcome.BLOCKED, "referenced decision is not locked in the reasoning envelope")
        if not proposal.compatible_with_locked_decisions:
            if proposal.revision_requested:
                return GuardResult(GuardOutcome.REVISION_REQUIRED, "explicit revision transaction required")
            return GuardResult(GuardOutcome.REJECTED, "proposal conflicts with an accepted locked decision")
        if proposal.operation == "implement_gap":
            if not implementation_gaps:
                return GuardResult(GuardOutcome.REJECTED, "no implementation gap is present")
            return GuardResult(GuardOutcome.IMPLEMENT_GAP, "proposal addresses a recorded implementation gap")
        return GuardResult(GuardOutcome.CONTINUE, "proposal is compatible with locked decisions")
