"""Canonical solver-independent scientific semantic records.

These immutable records were promoted from the qualified moose-test-repo\nsemantic layer. They are solver independent and contain no MOOSE/PETSc syntax.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

SEMANTIC_CONTRACT_ID = "QPX_STATE_SEMANTICS_V1"
ONTOLOGY_SCHEMA_VERSION = "1"


class HypothesisSupport(str, Enum):
    UNKNOWN = "UNKNOWN"
    CONTRADICTED = "CONTRADICTED"
    DISFAVORED = "DISFAVORED"
    PLAUSIBLE = "PLAUSIBLE"
    SUPPORTED = "SUPPORTED"
    STRONGLY_SUPPORTED = "STRONGLY_SUPPORTED"


class ResolutionStatus(str, Enum):
    OPEN = "OPEN"
    HOLD = "HOLD"
    RESOLVED = "RESOLVED"


class ScopeStatus(str, Enum):
    IN_SCOPE = "IN_SCOPE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    NOT_REQUIRED = "NOT_REQUIRED"


class ValidationStatus(str, Enum):
    UNASSESSED = "UNASSESSED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class ApplicabilityStatus(str, Enum):
    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    DEGENERATE = "DEGENERATE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class AcceptanceStatus(str, Enum):
    BLOCKED = "BLOCKED"
    ACCEPTED = "ACCEPTED"


class ProductionReadiness(str, Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    BLOCKED = "BLOCKED"
    READY = "READY"


class EvidenceAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"
    UNAVAILABLE = "UNAVAILABLE"


class EvidenceAdmissibility(str, Enum):
    ADMISSIBLE = "ADMISSIBLE"
    NON_EVIDENTIARY = "NON_EVIDENTIARY"
    UNKNOWN = "UNKNOWN"


class ExecutionStatus(str, Enum):
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    STALL_SUSPECTED = "STALL_SUSPECTED"


class ExecutionOutcomeStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    NOT_EXECUTED = "NOT_EXECUTED"


@dataclass(frozen=True)
class ProvenanceRecord:
    provenance_id: str
    source_identity: str
    artifact_ids: tuple[str, ...] = ()
    run_id: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    uri: str
    media_type: str | None = None
    content_hash: str | None = None
    schema_id: str | None = None
    provenance_id: str | None = None


@dataclass(frozen=True)
class Observation:
    observation_id: str
    name: str
    value: Any
    unit: str | None = None
    artifact_id: str | None = None
    run_id: str | None = None
    provenance_id: str | None = None


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    observation_id: str
    context_id: str
    availability: EvidenceAvailability = EvidenceAvailability.AVAILABLE
    admissibility: EvidenceAdmissibility = EvidenceAdmissibility.ADMISSIBLE
    provenance_id: str | None = None


@dataclass(frozen=True)
class DerivedFact:
    fact_id: str
    statement: str
    source_ids: tuple[str, ...]
    value: Any = None
    provenance_id: str | None = None


@dataclass(frozen=True)
class Constraint:
    constraint_id: str
    statement: str
    kind: str = "DECLARED"


@dataclass(frozen=True)
class DevelopmentGoal:
    goal_id: str
    statement: str


@dataclass(frozen=True)
class Proposition:
    proposition_id: str
    statement: str


@dataclass(frozen=True)
class Hypothesis(Proposition):
    pass


@dataclass(frozen=True)
class MechanismClaim(Proposition):
    pass


@dataclass(frozen=True)
class ValidationClaim(Proposition):
    pass


@dataclass(frozen=True)
class OpenQuestion:
    question_id: str
    statement: str


@dataclass(frozen=True)
class HypothesisAssessment:
    assessment_id: str
    hypothesis_id: str
    state_id: str
    support: HypothesisSupport = HypothesisSupport.UNKNOWN
    resolution: ResolutionStatus = ResolutionStatus.OPEN
    scope: ScopeStatus = ScopeStatus.IN_SCOPE
    confidence: float | None = None
    evidence_ids: tuple[str, ...] = ()
    provenance_id: str | None = None


@dataclass(frozen=True)
class ClaimAssessment:
    assessment_id: str
    claim_id: str
    state_id: str
    validation: ValidationStatus = ValidationStatus.UNASSESSED
    applicability: ApplicabilityStatus = ApplicabilityStatus.APPLICABLE
    acceptance: AcceptanceStatus = AcceptanceStatus.BLOCKED
    production_readiness: ProductionReadiness = ProductionReadiness.NOT_ASSESSED
    evidence_ids: tuple[str, ...] = ()
    blocker_ids: tuple[str, ...] = ()
    provenance_id: str | None = None


@dataclass(frozen=True)
class DiagnosticConclusion:
    conclusion_id: str
    state_id: str
    statement: str
    proposition_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    localized_owner: str | None = None
    owner_granularity: str | None = None
    mechanism_id: str | None = None
    provenance_id: str | None = None


@dataclass(frozen=True)
class CapabilityDescriptor:
    capability_id: str
    responsibility: str
    semantic_inputs: tuple[str, ...] = ()
    semantic_outputs: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    version: str = "1"
    available: bool = True


@dataclass(frozen=True)
class ExperimentCaseIntent:
    case_id: str
    parameters: tuple[tuple[str, Any], ...] = ()
    constraint_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExperimentIntent:
    intent_id: str
    experiment_id: str
    objective: str
    model_ref: str | None = None
    goal_ids: tuple[str, ...] = ()
    target_ids: tuple[str, ...] = ()
    requested_capabilities: tuple[str, ...] = ()
    parameters: tuple[tuple[str, Any], ...] = ()
    constraint_ids: tuple[str, ...] = ()
    requested_observations: tuple[str, ...] = ()
    execution_bounds: tuple[tuple[str, Any], ...] = ()
    case_ids: tuple[str, ...] = ()
    provenance_id: str | None = None


@dataclass(frozen=True)
class ActionSpec:
    action_id: str
    intended_effect: str
    target: str
    intervention_type: str
    discriminates: tuple[str, ...] = ()
    expected_information_gain: float | None = None
    expected_cost: float | None = None
    expected_risk: float | None = None
    preserves: tuple[str, ...] = ()
    required_authorization: str | None = None
    parameters: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class SearchDecision:
    decision_id: str
    state_id: str
    action_id: str
    disposition: str
    rationale: str
    evidence_ids: tuple[str, ...] = ()
    constraint_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScientificPolicy:
    policy_id: str
    source_state_id: str
    source_intent_id: str
    objective: str
    selected_actions: tuple[ActionSpec, ...]
    target_ids: tuple[str, ...] = ()
    considered_actions: tuple[ActionSpec, ...] = ()
    decisions: tuple[SearchDecision, ...] = ()
    held_fixed: tuple[str, ...] = ()
    required_observations: tuple[str, ...] = ()
    acceptance_requirements: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    unresolved_requirements: tuple[str, ...] = ()
    derived_values: tuple[tuple[str, Any], ...] = ()
    policy_rule_ids: tuple[str, ...] = ()
    execution_bounds: tuple[tuple[str, Any], ...] = ()
    model_ref: str | None = None
    rationale: str = ""
    provenance_id: str | None = None
    semantic_contract: str = SEMANTIC_CONTRACT_ID


@dataclass(frozen=True)
class DevelopmentState:
    state_id: str
    case_id: str
    system: tuple[tuple[str, Any], ...] = ()
    observation_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    derived_fact_ids: tuple[str, ...] = ()
    hypothesis_assessment_ids: tuple[str, ...] = ()
    claim_assessment_ids: tuple[str, ...] = ()
    diagnostic_conclusion_ids: tuple[str, ...] = ()
    open_question_ids: tuple[str, ...] = ()
    considered_action_ids: tuple[str, ...] = ()
    repository: tuple[tuple[str, Any], ...] = ()
    provenance_id: str | None = None
    semantic_contract: str = SEMANTIC_CONTRACT_ID


@dataclass(frozen=True)
class StateDelta:
    world_delta: tuple[tuple[str, Any], ...] = ()
    observation_delta: tuple[str, ...] = ()
    epistemic_delta: tuple[str, ...] = ()
    search_delta: tuple[str, ...] = ()
    claim_delta: tuple[str, ...] = ()
    repository_delta: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class StateTransition:
    transition_id: str
    predecessor_id: str
    successor_id: str
    delta: StateDelta
    caused_by_execution_id: str | None = None
    provenance_id: str | None = None


@dataclass(frozen=True)
class ActionExecution:
    execution_id: str
    action_id: str
    source_state_id: str
    status: ExecutionStatus | None = None
    provenance_id: str | None = None


@dataclass(frozen=True)
class ExecutionOutcome:
    outcome_id: str
    execution_id: str
    status: ExecutionOutcomeStatus
    artifact_ids: tuple[str, ...] = ()
    observation_ids: tuple[str, ...] = ()
    message: str | None = None


def frozen_mapping(value: Mapping[str, Any] | None) -> tuple[tuple[str, Any], ...]:
    """Return a deterministic immutable mapping projection."""
    if not value:
        return ()
    return tuple(sorted(value.items(), key=lambda item: item[0]))
