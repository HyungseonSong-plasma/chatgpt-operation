"""Solver-independent execution IR compiled from ScientificPolicy."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExecutionCase:
    case_id: str
    action_id: str
    target: str = ""
    intervention_type: str = ""
    parameters: tuple[tuple[str, Any], ...] = ()
    required_observations: tuple[str, ...] = ()
    held_fixed: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutionPlan:
    plan_id: str
    source_policy_id: str
    cases: tuple[ExecutionCase, ...]
    model_ref: str | None = None
    execution_bounds: tuple[tuple[str, Any], ...] = ()
    required_observations: tuple[str, ...] = ()
    artifact_contracts: tuple[str, ...] = ()
    target_capabilities: tuple[str, ...] = ()
    derived_values: tuple[tuple[str, Any], ...] = ()
    provenance_id: str | None = None

    def case(self, case_id: str) -> ExecutionCase:
        matches = [item for item in self.cases if item.case_id == case_id]
        if len(matches) != 1:
            raise KeyError(f"expected one case {case_id!r}, found {len(matches)}")
        return matches[0]




import hashlib
import json

from .ontology import ScientificPolicy


class UnresolvedPolicyError(ValueError):
    pass


def compile_execution_plan(policy: ScientificPolicy) -> ExecutionPlan:
    if policy.unresolved_requirements:
        raise UnresolvedPolicyError(
            "policy is not runnable while unresolved requirements remain: "
            + ", ".join(policy.unresolved_requirements)
        )
    cases = tuple(
        ExecutionCase(
            case_id=f"case:{index}:{action.action_id}",
            action_id=action.action_id,
            target=action.target,
            intervention_type=action.intervention_type,
            parameters=action.parameters,
            required_observations=policy.required_observations,
            held_fixed=tuple(dict.fromkeys((*policy.held_fixed, *action.preserves))),
        )
        for index, action in enumerate(policy.selected_actions)
    )
    payload = {
        "policy": policy.policy_id,
        "model_ref": policy.model_ref,
        "cases": [
            {
                "id": item.case_id,
                "action": item.action_id,
                "target": item.target,
                "intervention_type": item.intervention_type,
                "parameters": item.parameters,
                "observations": item.required_observations,
                "held_fixed": item.held_fixed,
            }
            for item in cases
        ],
        "bounds": policy.execution_bounds,
        "derived": policy.derived_values,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return ExecutionPlan(
        plan_id=f"plan:{digest}",
        source_policy_id=policy.policy_id,
        cases=cases,
        model_ref=policy.model_ref,
        execution_bounds=policy.execution_bounds,
        required_observations=policy.required_observations,
        artifact_contracts=("run_log", "observation_artifacts"),
        target_capabilities=policy.required_capabilities,
        derived_values=policy.derived_values,
        provenance_id=policy.provenance_id,
    )




__all__ = [
    "ExecutionCase", "ExecutionPlan", "UnresolvedPolicyError",
    "compile_execution_plan",
]
