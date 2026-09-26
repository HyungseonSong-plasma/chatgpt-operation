"""Typed research state and deterministic workflow for autonomous research cycles."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import json
from pathlib import Path
from typing import Any


class ResearchStateError(ValueError):
    pass


class ResearchStage(str, Enum):
    DEFINE_PROBLEM = "define_problem"
    ACQUIRE_KNOWLEDGE = "acquire_knowledge"
    GENERATE_HYPOTHESIS = "generate_hypothesis"
    DESIGN_VALIDATION = "design_validation"
    DESIGN_EXPERIMENT = "design_experiment"
    IMPLEMENT = "implement"
    EXECUTE = "execute"
    ANALYZE = "analyze"
    DECIDE = "decide"
    ESCALATE = "escalate"
    COMPLETE = "complete"


ALLOWED_TRANSITIONS: dict[ResearchStage, frozenset[ResearchStage]] = {
    ResearchStage.DEFINE_PROBLEM: frozenset({ResearchStage.ACQUIRE_KNOWLEDGE}),
    ResearchStage.ACQUIRE_KNOWLEDGE: frozenset({ResearchStage.GENERATE_HYPOTHESIS}),
    ResearchStage.GENERATE_HYPOTHESIS: frozenset({
        ResearchStage.ACQUIRE_KNOWLEDGE, ResearchStage.DESIGN_VALIDATION
    }),
    ResearchStage.DESIGN_VALIDATION: frozenset({ResearchStage.DESIGN_EXPERIMENT}),
    ResearchStage.DESIGN_EXPERIMENT: frozenset({ResearchStage.IMPLEMENT}),
    ResearchStage.IMPLEMENT: frozenset({ResearchStage.EXECUTE}),
    ResearchStage.EXECUTE: frozenset({ResearchStage.ANALYZE}),
    ResearchStage.ANALYZE: frozenset({
        ResearchStage.ACQUIRE_KNOWLEDGE, ResearchStage.GENERATE_HYPOTHESIS,
        ResearchStage.DESIGN_EXPERIMENT, ResearchStage.DECIDE, ResearchStage.ESCALATE
    }),
    ResearchStage.DECIDE: frozenset({
        ResearchStage.ACQUIRE_KNOWLEDGE, ResearchStage.GENERATE_HYPOTHESIS,
        ResearchStage.DESIGN_EXPERIMENT, ResearchStage.COMPLETE, ResearchStage.ESCALATE
    }),
    ResearchStage.ESCALATE: frozenset({
        ResearchStage.ACQUIRE_KNOWLEDGE, ResearchStage.GENERATE_HYPOTHESIS,
        ResearchStage.DESIGN_EXPERIMENT, ResearchStage.DECIDE, ResearchStage.COMPLETE
    }),
    ResearchStage.COMPLETE: frozenset(),
}


@dataclass(frozen=True)
class HypothesisResult:
    statement: str
    mechanism: str
    falsification_test: str
    evidence_for: tuple[str, ...] = ()
    evidence_against: tuple[str, ...] = ()
    confidence: float = 0.0

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "HypothesisResult":
        required = ("statement", "mechanism", "falsification_test")
        if any(not isinstance(raw.get(k), str) or not raw[k].strip() for k in required):
            raise ResearchStateError("hypothesis requires non-empty statement, mechanism, and falsification_test")
        confidence = float(raw.get("confidence", 0.0))
        if not 0.0 <= confidence <= 1.0:
            raise ResearchStateError("hypothesis confidence must be in [0, 1]")
        return cls(
            statement=raw["statement"].strip(),
            mechanism=raw["mechanism"].strip(),
            falsification_test=raw["falsification_test"].strip(),
            evidence_for=tuple(raw.get("evidence_for", ())),
            evidence_against=tuple(raw.get("evidence_against", ())),
            confidence=confidence,
        )


@dataclass(frozen=True)
class DecisionRisk:
    impact: float
    uncertainty: float
    irreversibility: float

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "DecisionRisk":
        values = {}
        for name in ("impact", "uncertainty", "irreversibility"):
            value = float(raw.get(name, -1))
            if not 0.0 <= value <= 1.0:
                raise ResearchStateError(f"{name} must be in [0, 1]")
            values[name] = value
        return cls(**values)

    @property
    def score(self) -> float:
        return self.impact * self.uncertainty * self.irreversibility


@dataclass(frozen=True)
class EscalationPolicy:
    threshold: float = 0.5

    def __post_init__(self) -> None:
        if not 0.0 <= self.threshold <= 1.0:
            raise ResearchStateError("escalation threshold must be in [0, 1]")

    def requires_escalation(self, risk: DecisionRisk) -> bool:
        return risk.score >= self.threshold


@dataclass(frozen=True)
class AnalysisResult:
    hypothesis_status: str
    confidence: float
    knowledge_gap: bool = False
    additional_experiment_needed: bool = False
    high_consequence_ambiguity: bool = False
    decision_risk: DecisionRisk | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AnalysisResult":
        status = raw.get("hypothesis_status")
        if status not in {"supported", "rejected", "inconclusive"}:
            raise ResearchStateError("invalid hypothesis_status")
        confidence = float(raw.get("confidence", -1))
        if not 0.0 <= confidence <= 1.0:
            raise ResearchStateError("analysis confidence must be in [0, 1]")
        return cls(
            hypothesis_status=status,
            confidence=confidence,
            knowledge_gap=bool(raw.get("knowledge_gap", False)),
            additional_experiment_needed=bool(raw.get("additional_experiment_needed", False)),
            high_consequence_ambiguity=bool(raw.get("high_consequence_ambiguity", False)),
            decision_risk=(DecisionRisk.from_dict(raw["decision_risk"]) if raw.get("decision_risk") is not None else None),
        )


@dataclass
class ResearchState:
    research_id: str
    objective: str
    stage: ResearchStage = ResearchStage.DEFINE_PROBLEM
    completed_operation_ids: list[str] = field(default_factory=list)
    execution_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    revision: int = 0

    def transition(self, target: ResearchStage, *, execution_evidence: bool = False) -> None:
        if target not in ALLOWED_TRANSITIONS[self.stage]:
            raise ResearchStateError(f"transition {self.stage.value} -> {target.value} is not allowed")
        if target is ResearchStage.COMPLETE and not execution_evidence:
            raise ResearchStateError(
                "COMPLETE is evidence-gated; use transition_from_execution"
            )
        self.stage = target
        self.revision += 1

    def apply_once(
        self,
        operation_id: str,
        target: ResearchStage,
        *,
        execution_evidence: bool = False,
    ) -> bool:
        if operation_id in self.completed_operation_ids:
            return False
        self.transition(target, execution_evidence=execution_evidence)
        self.completed_operation_ids.append(operation_id)
        return True

    def save(self, path: str | Path) -> None:
        payload = asdict(self)
        payload["stage"] = self.stage.value
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(target)

    @classmethod
    def load(cls, path: str | Path) -> "ResearchState":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            research_id=raw["research_id"],
            objective=raw["objective"],
            stage=ResearchStage(raw["stage"]),
            completed_operation_ids=list(raw.get("completed_operation_ids", [])),
            execution_results=dict(raw.get("execution_results", {})),
            revision=int(raw.get("revision", 0)),
        )


def next_stage_from_analysis(result: AnalysisResult, escalation_policy: EscalationPolicy | None = None) -> ResearchStage:
    policy = escalation_policy or EscalationPolicy()
    if result.high_consequence_ambiguity:
        return ResearchStage.ESCALATE
    if result.decision_risk is not None and policy.requires_escalation(result.decision_risk):
        return ResearchStage.ESCALATE
    if result.knowledge_gap:
        return ResearchStage.ACQUIRE_KNOWLEDGE
    if result.hypothesis_status == "rejected":
        return ResearchStage.GENERATE_HYPOTHESIS
    if result.hypothesis_status == "inconclusive" or result.additional_experiment_needed:
        return ResearchStage.DESIGN_EXPERIMENT
    return ResearchStage.DECIDE
