"""Deterministic diagnostic recovery engine driven by typed execution evidence."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from .action_plan import ActionPlan

from .execution import (
    ExecutionStatus,
    diagnostic_next_action,
    record_diagnostic_corrective_action,
    record_diagnostic_resolution,
    record_diagnostic_root_cause,
)
from .research import ResearchState


@dataclass(frozen=True)
class DiagnosticAdvance:
    action_id: str
    phase: str
    advanced: bool
    evidence: str


def advance_diagnostic(state: ResearchState, action_id: str) -> DiagnosticAdvance:
    """Advance one phase only when existing typed evidence determines the result."""
    next_action = diagnostic_next_action(state, action_id)
    recovery = state.diagnostic_recoveries[action_id]
    failure = recovery.get("failure") or {}
    details = failure.get("details") or {}
    phase = next_action["kind"]

    if phase == "investigate_root_cause":
        provider = str(details.get("provider", "")).strip()
        error_type = str(details.get("error_type", "")).strip()
        provider_status = str(details.get("provider_status", "")).strip()
        if not provider or not error_type:
            return DiagnosticAdvance(action_id, phase, False, "typed failure evidence insufficient")
        evidence = f"provider={provider};error_type={error_type}"
        if provider_status:
            evidence += f";provider_status={provider_status}"
        record_diagnostic_root_cause(state, action_id, evidence)
        return DiagnosticAdvance(action_id, phase, True, evidence)

    if phase == "apply_corrective_action":
        provider = str(details.get("provider", "")).strip()
        failures = details.get("provider_failures")
        if isinstance(failures, list) and failures:
            alternatives = [
                str(item.get("provider", "")).strip()
                for item in failures
                if isinstance(item, dict) and str(item.get("provider", "")).strip() != provider
            ]
            if alternatives:
                evidence = "retry through alternative provider=" + alternatives[0]
                record_diagnostic_corrective_action(state, action_id, evidence)
                return DiagnosticAdvance(action_id, phase, True, evidence)
        return DiagnosticAdvance(action_id, phase, False, "no typed corrective action available")

    if phase == "verify_resolution":
        verification = details.get("resolution_verification")
        if isinstance(verification, dict) and verification.get("verified") is True:
            evidence = str(verification.get("evidence", "")).strip()
            if evidence:
                record_diagnostic_resolution(state, action_id, evidence)
                return DiagnosticAdvance(action_id, phase, True, evidence)
        return DiagnosticAdvance(action_id, phase, False, "resolution not independently verified")

    raise AssertionError("unsupported diagnostic phase")


def resolve_from_execution_receipt(
    state: ResearchState,
    action_id: str,
    *,
    corrective_result,
) -> DiagnosticAdvance:
    """Resolve only from an executor result whose postcondition was authoritatively verified."""
    recovery = state.diagnostic_recoveries.get(action_id)
    if recovery is None or recovery.get("status") != "open":
        raise ValueError("diagnostic recovery is not open")
    if not recovery.get("root_cause") or not recovery.get("corrective_action"):
        raise ValueError("diagnostic correction has not been planned")
    if corrective_result.research_id != state.research_id:
        raise ValueError("corrective result belongs to a different research state")
    if corrective_result.status not in {ExecutionStatus.PASS, ExecutionStatus.NOOP}:
        return DiagnosticAdvance(
            action_id, "verify_resolution", False,
            "corrective execution did not produce PASS/NOOP",
        )
    if corrective_result.status is ExecutionStatus.PASS:
        after = corrective_result.details.get("after")
        if not isinstance(after, dict):
            return DiagnosticAdvance(
                action_id, "verify_resolution", False,
                "PASS result lacks postcondition readback",
            )
        evidence = "verified corrective execution: " + corrective_result.observation
    else:
        before = corrective_result.details.get("before")
        if not isinstance(before, dict):
            return DiagnosticAdvance(
                action_id, "verify_resolution", False,
                "NOOP result lacks desired-state readback",
            )
        evidence = "verified desired state already held: " + corrective_result.observation
    record_diagnostic_resolution(state, action_id, evidence)
    return DiagnosticAdvance(action_id, "verify_resolution", True, evidence)


def attach_source_plan(
    state: ResearchState,
    action_id: str,
    plan: ActionPlan,
) -> None:
    """Bind the exact failed ActionPlan to recovery so correction cannot be invented later."""
    recovery = state.diagnostic_recoveries.get(action_id)
    if recovery is None or recovery.get("status") != "open":
        raise ValueError("diagnostic recovery is not open")
    if plan.research_id != state.research_id or plan.idempotency_key != action_id:
        raise ValueError("source plan does not match suspended action")
    recovery["source_plan"] = {
        "schema_version": 1,
        "research_id": plan.research_id,
        "stage": plan.stage.value,
        "executor": plan.executor.value,
        "payload": dict(plan.payload),
        "expected_observation": plan.expected_observation,
        "decision_risk": None if plan.decision_risk is None else {
            "impact": plan.decision_risk.impact,
            "uncertainty": plan.decision_risk.uncertainty,
            "irreversibility": plan.decision_risk.irreversibility,
        },
    }
    state.revision += 1


def corrective_plan_from_recovery(
    state: ResearchState,
    action_id: str,
) -> ActionPlan:
    """Return an executable corrective replay only from the exact persisted source plan."""
    recovery = state.diagnostic_recoveries.get(action_id)
    if recovery is None or recovery.get("status") != "open":
        raise ValueError("diagnostic recovery is not open")
    if not recovery.get("root_cause") or not recovery.get("corrective_action"):
        raise ValueError("diagnostic correction is not ready")
    raw = recovery.get("source_plan")
    if not isinstance(raw, dict):
        raise ValueError("diagnostic recovery has no typed source ActionPlan")
    plan = ActionPlan.from_dict(raw)
    if plan.idempotency_key != action_id:
        raise ValueError("persisted source ActionPlan identity changed")
    return plan


@dataclass(frozen=True)
class RecoveryAuthorization:
    action_id: str
    source_plan_id: str
    corrective_action: str
    token: str


def recovery_authorization(state: ResearchState, action_id: str) -> RecoveryAuthorization:
    """Issue a deterministic authorization bound to one open corrective recovery."""
    plan = corrective_plan_from_recovery(state, action_id)
    recovery = state.diagnostic_recoveries[action_id]
    corrective = str(recovery["corrective_action"])
    semantic = {
        "research_id": state.research_id,
        "action_id": action_id,
        "source_plan_id": plan.idempotency_key,
        "corrective_action": corrective,
        "status": recovery["status"],
    }
    token = hashlib.sha256(json.dumps(
        semantic, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    return RecoveryAuthorization(action_id, plan.idempotency_key, corrective, token)


def validate_recovery_authorization(
    state: ResearchState,
    plan: ActionPlan,
    authorization: RecoveryAuthorization,
) -> None:
    expected = recovery_authorization(state, plan.idempotency_key)
    if authorization != expected:
        raise ValueError("recovery authorization does not match current diagnostic state")


def recovery_authorization_from_dict(raw: dict[str, Any]) -> RecoveryAuthorization:
    required = {"action_id", "source_plan_id", "corrective_action", "token"}
    if not isinstance(raw, dict) or set(raw) != required:
        raise ValueError("invalid recovery authorization schema")
    return RecoveryAuthorization(
        action_id=str(raw["action_id"]),
        source_plan_id=str(raw["source_plan_id"]),
        corrective_action=str(raw["corrective_action"]),
        token=str(raw["token"]),
    )


def recovery_authorization_to_dict(auth: RecoveryAuthorization) -> dict[str, str]:
    return {
        "action_id": auth.action_id,
        "source_plan_id": auth.source_plan_id,
        "corrective_action": auth.corrective_action,
        "token": auth.token,
    }
