"""Canonical solver-independent scientific planning and policy synthesis."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from .ontology import (
    ActionSpec,
    CapabilityDescriptor,
    DevelopmentState,
    ExperimentIntent,
    ScientificPolicy,
    SearchDecision,
)

PolicyRule = Callable[..., tuple[ActionSpec, ...]]


@dataclass(frozen=True)
class PolicyRuleDescriptor:
    rule_id: str
    capability_id: str
    semantic_inputs: tuple[str, ...]
    semantic_outputs: tuple[str, ...]
    solver_independent: bool = True
    version: str = "1"


def default_capabilities() -> tuple[CapabilityDescriptor, ...]:
    """Small solver-independent capability catalog used by the canonical pipeline."""
    return (
        CapabilityDescriptor(
            capability_id="electron_energy_diffusion",
            responsibility="scientific_intervention",
            semantic_inputs=("diffusivity",),
            semantic_outputs=("controlled_diffusion_action",),
        ),
        CapabilityDescriptor(
            capability_id="electron_energy_inventory_observation",
            responsibility="observation",
            semantic_outputs=("energy_inventory",),
        ),
        CapabilityDescriptor(
            capability_id="quasi_neutral_initialization",
            responsibility="derived_policy",
            semantic_inputs=("heavy_species_charge",),
            semantic_outputs=("electron_reference",),
        ),
        CapabilityDescriptor(
            capability_id="poisson_electrostatics",
            responsibility="scientific_intervention",
            semantic_outputs=("electrostatic_action",),
        ),
        CapabilityDescriptor(
            capability_id="observability_instrumentation",
            responsibility="observation_intervention",
            semantic_outputs=("instrumentation_action",),
        ),
    )




import hashlib
import json
import math
from typing import Any


def _stable_id(prefix: str, payload: object) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return f"{prefix}:{hashlib.sha256(blob.encode('utf-8')).hexdigest()[:16]}"


def _parameter_map(intent: ExperimentIntent) -> dict[str, Any]:
    return dict(intent.parameters)


def _system_map(state: DevelopmentState) -> dict[str, Any]:
    return dict(state.system)


def _diffusion_actions(intent: ExperimentIntent) -> tuple[ActionSpec, ...]:
    params = _parameter_map(intent)
    requested = params.get("diffusivity", params.get("diffusion_coefficient", 1.0))
    try:
        requested_value = float(requested)
    except (TypeError, ValueError) as exc:
        raise ValueError("electron-energy diffusivity must be numeric") from exc
    if not math.isfinite(requested_value) or requested_value < 0.0:
        raise ValueError("electron-energy diffusivity must be finite and non-negative")
    preserves = intent.constraint_ids
    control = ActionSpec(
        action_id=f"action:{intent.intent_id}:diffusion-control",
        intended_effect="establish controlled no-diffusion reference",
        target="electron_energy_transport",
        intervention_type="PARAMETER_CONTROL",
        discriminates=intent.target_ids,
        expected_information_gain=0.5,
        expected_cost=1.0,
        expected_risk=0.1,
        preserves=preserves,
        parameters=(("diffusivity", 0.0),),
    )
    treatment = ActionSpec(
        action_id=f"action:{intent.intent_id}:diffusion-treatment",
        intended_effect="apply requested controlled electron-energy diffusion",
        target="electron_energy_transport",
        intervention_type="PARAMETER_TREATMENT",
        discriminates=intent.target_ids,
        expected_information_gain=1.0,
        expected_cost=1.0,
        expected_risk=0.1,
        preserves=preserves,
        parameters=(("diffusivity", requested_value),),
    )
    return (control, treatment)


def _observability_action(intent: ExperimentIntent) -> tuple[ActionSpec, ...]:
    return (
        ActionSpec(
            action_id=f"action:{intent.intent_id}:observability",
            intended_effect="increase observability without changing intended physics",
            target="runtime_observability",
            intervention_type="OBSERVABILITY_INTERVENTION",
            discriminates=intent.target_ids,
            expected_information_gain=1.0,
            expected_cost=0.2,
            expected_risk=0.0,
            preserves=intent.constraint_ids,
        ),
    )


def _quasi_neutral_action(
    state: DevelopmentState,
    intent: ExperimentIntent,
) -> tuple[ActionSpec | None, tuple[tuple[str, Any], ...], str | None]:
    system = _system_map(state)
    raw = system.get("signed_heavy_charge_number_density_m3")
    if raw is None:
        return None, (), "INSUFFICIENT_STATE_INFORMATION:quasi_neutral_initialization"
    try:
        electron_reference = float(raw)
    except (TypeError, ValueError):
        return None, (), "INSUFFICIENT_STATE_INFORMATION:quasi_neutral_initialization"
    if not math.isfinite(electron_reference) or electron_reference <= 0.0:
        return None, (), "CONSTRAINT_CONFLICT:quasi_neutral_initialization"
    derived = (("electron_reference_density_m3", electron_reference),)
    action = ActionSpec(
        action_id=f"action:{intent.intent_id}:quasi-neutral-initialization",
        intended_effect="initialize electron reference density from signed heavy-species charge",
        target="electron_reference_density",
        intervention_type="DERIVED_INITIALIZATION",
        discriminates=intent.target_ids,
        expected_information_gain=0.0,
        expected_cost=0.0,
        expected_risk=0.0,
        preserves=intent.constraint_ids,
        parameters=derived,
    )
    return action, derived, None


def synthesize_policy(
    state: DevelopmentState,
    intent: ExperimentIntent,
    capabilities: Iterable[CapabilityDescriptor],
) -> ScientificPolicy:
    """Synthesize a bounded semantic policy without process execution or solver syntax."""
    capability_map = {item.capability_id: item for item in capabilities if item.available}
    missing_capabilities = tuple(
        capability
        for capability in intent.requested_capabilities
        if capability not in capability_map
    )
    unresolved = [f"CAPABILITY_GAP:{item}" for item in missing_capabilities]

    actions: list[ActionSpec] = []
    derived_values: list[tuple[str, Any]] = []
    policy_rule_ids: list[str] = []

    if "electron_energy_diffusion" in intent.requested_capabilities:
        if "electron_energy_diffusion" in capability_map:
            actions.extend(_diffusion_actions(intent))
            policy_rule_ids.append("controlled-electron-energy-diffusion:v1")

    if "observability_instrumentation" in intent.requested_capabilities:
        if "observability_instrumentation" in capability_map:
            actions.extend(_observability_action(intent))
            policy_rule_ids.append("observability-intervention:v1")

    if "quasi_neutral_initialization" in intent.requested_capabilities:
        if "quasi_neutral_initialization" in capability_map:
            action, derived, gap = _quasi_neutral_action(state, intent)
            policy_rule_ids.append("quasi-neutral-initialization:v1")
            if gap is not None:
                unresolved.append(gap)
            elif action is not None:
                actions.append(action)
                derived_values.extend(derived)

    specialized = {
        "electron_energy_diffusion",
        "observability_instrumentation",
        "quasi_neutral_initialization",
    }
    for capability in intent.requested_capabilities:
        if capability in missing_capabilities or capability in specialized:
            continue
        descriptor = capability_map[capability]
        if descriptor.responsibility in {"observation", "analysis", "validation"}:
            continue
        actions.append(
            ActionSpec(
                action_id=f"action:{intent.intent_id}:{capability}",
                intended_effect=f"realize semantic capability {capability}",
                target=capability,
                intervention_type="SEMANTIC_CAPABILITY",
                discriminates=intent.target_ids,
                preserves=intent.constraint_ids,
            )
        )
        policy_rule_ids.append(f"generic-capability:{capability}:v1")

    decisions = tuple(
        SearchDecision(
            decision_id=f"decision:{action.action_id}",
            state_id=state.state_id,
            action_id=action.action_id,
            disposition="SELECTED",
            rationale=(
                "selected by deterministic capability synthesis for intent "
                f"{intent.intent_id}"
            ),
            constraint_ids=intent.constraint_ids,
        )
        for action in actions
    )

    acceptance_requirements = tuple(
        f"evaluate target {target_id} with admitted evidence"
        for target_id in intent.target_ids
    )
    payload = {
        "state": state.state_id,
        "intent": intent.intent_id,
        "actions": [action.action_id for action in actions],
        "derived": derived_values,
        "rules": policy_rule_ids,
        "unresolved": unresolved,
    }
    policy_id = _stable_id("policy", payload)
    rationale = (
        "deterministic semantic capability synthesis"
        if not unresolved
        else "policy contains unresolved semantic requirements"
    )
    return ScientificPolicy(
        policy_id=policy_id,
        source_state_id=state.state_id,
        source_intent_id=intent.intent_id,
        objective=intent.objective,
        selected_actions=tuple(actions),
        target_ids=intent.target_ids,
        considered_actions=tuple(actions),
        decisions=decisions,
        held_fixed=intent.constraint_ids,
        required_observations=intent.requested_observations,
        acceptance_requirements=acceptance_requirements,
        required_capabilities=intent.requested_capabilities,
        unresolved_requirements=tuple(unresolved),
        derived_values=tuple(derived_values),
        policy_rule_ids=tuple(policy_rule_ids),
        execution_bounds=intent.execution_bounds,
        model_ref=intent.model_ref,
        rationale=rationale,
        provenance_id=intent.provenance_id,
    )




__all__ = [
    "ActionSpec", "CapabilityDescriptor", "ScientificPolicy", "SearchDecision",
    "PolicyRule", "PolicyRuleDescriptor", "default_capabilities", "synthesize_policy",
]
