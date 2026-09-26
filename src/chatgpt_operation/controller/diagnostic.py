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
        available = details.get("available_providers")
        failures = details.get("provider_failures")
        failed = {provider} if provider else set()
        if isinstance(failures, list):
            failed.update(
                str(item.get("provider", "")).strip()
                for item in failures
                if isinstance(item, dict) and str(item.get("provider", "")).strip()
            )
        if isinstance(available, list):
            eligible = sorted({
                str(name).strip() for name in available
                if isinstance(name, str) and name.strip() and name.strip() not in failed
            })
            if eligible:
                recovery["corrective_provider"] = eligible[0]
                evidence = "retry through eligible provider=" + eligible[0]
                record_diagnostic_corrective_action(state, action_id, evidence)
                return DiagnosticAdvance(action_id, phase, True, evidence)
        return DiagnosticAdvance(
            action_id, phase, False,
            "no eligible provider proven by capability evidence",
        )

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
    corrective_provider: str
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
        "corrective_provider": str(recovery.get("corrective_provider", "")),
        "status": recovery["status"],
    }
    token = hashlib.sha256(json.dumps(
        semantic, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    provider=str(recovery.get("corrective_provider", "")).strip()
    if not provider:
        raise ValueError("diagnostic recovery has no selected corrective provider")
    return RecoveryAuthorization(action_id, plan.idempotency_key, corrective, provider, token)


def validate_recovery_authorization(
    state: ResearchState,
    plan: ActionPlan,
    authorization: RecoveryAuthorization,
) -> None:
    expected = recovery_authorization(state, plan.idempotency_key)
    if authorization != expected:
        raise ValueError("recovery authorization does not match current diagnostic state")


def recovery_authorization_from_dict(raw: dict[str, Any]) -> RecoveryAuthorization:
    required = {"action_id", "source_plan_id", "corrective_action", "corrective_provider", "token"}
    if not isinstance(raw, dict) or set(raw) != required:
        raise ValueError("invalid recovery authorization schema")
    return RecoveryAuthorization(
        action_id=str(raw["action_id"]),
        source_plan_id=str(raw["source_plan_id"]),
        corrective_action=str(raw["corrective_action"]),
        corrective_provider=str(raw["corrective_provider"]),
        token=str(raw["token"]),
    )


def recovery_authorization_to_dict(auth: RecoveryAuthorization) -> dict[str, str]:
    return {
        "action_id": auth.action_id,
        "source_plan_id": auth.source_plan_id,
        "corrective_action": auth.corrective_action,
        "corrective_provider": auth.corrective_provider,
        "token": auth.token,
    }


def enqueue_suspended_action(state: ResearchState, plan: ActionPlan) -> None:
    """Persist ownership of an action before it can enter diagnostic suspension."""
    if plan.research_id != state.research_id:
        raise ValueError("queued plan belongs to a different research state")
    state.action_queue[plan.idempotency_key] = {
        "status": "pending",
        "plan": {
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
        },
    }
    state.revision += 1


def mark_action_suspended(state: ResearchState, action_id: str) -> None:
    item = state.action_queue.get(action_id)
    if item is None:
        raise ValueError("diagnostic action is not owned by durable queue")
    item["status"] = "suspended"
    state.revision += 1


def resume_resolved_action(state: ResearchState, action_id: str) -> ActionPlan:
    recovery = state.diagnostic_recoveries.get(action_id)
    item = state.action_queue.get(action_id)
    if recovery is None or recovery.get("status") != "resolved":
        raise ValueError("diagnostic recovery is not resolved")
    if item is None or item.get("status") != "suspended":
        raise ValueError("resolved action is not suspended in durable queue")
    plan = ActionPlan.from_dict(item["plan"])
    if plan.idempotency_key != action_id:
        raise ValueError("queued action identity changed")
    item["status"] = "pending"
    state.revision += 1
    return plan


def complete_queued_action(state: ResearchState, action_id: str, result) -> None:
    item = state.action_queue.get(action_id)
    if item is None or item.get("status") != "pending":
        raise ValueError("action is not pending")
    if result.action_id != action_id or result.research_id != state.research_id:
        raise ValueError("execution result does not match queued action")
    if result.status not in {ExecutionStatus.PASS, ExecutionStatus.NOOP}:
        raise ValueError("queued action requires PASS/NOOP completion evidence")
    item["status"] = "complete"
    item["completion_result"] = result.to_dict()
    state.revision += 1


def record_diagnostic_wait(
    state: ResearchState,
    action_id: str,
    *,
    phase: str,
    evidence: str,
    max_identical_waits: int = 2,
) -> str:
    """Persist repeated WAIT evidence and break identical diagnostic loops."""
    recovery = state.diagnostic_recoveries.get(action_id)
    if recovery is None or recovery.get("status") != "open":
        raise ValueError("diagnostic recovery is not open")
    semantic = {"phase": phase, "evidence": evidence}
    fingerprint = hashlib.sha256(json.dumps(
        semantic, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    wait = recovery.get("wait") or {}
    attempts = int(wait.get("attempts", 0)) + 1 if wait.get("fingerprint") == fingerprint else 1
    recovery["wait"] = {
        "fingerprint": fingerprint,
        "phase": phase,
        "evidence": evidence,
        "attempts": attempts,
    }
    if attempts >= max_identical_waits:
        recovery["status"] = "needs_evidence"
        recovery["evidence_request"] = {
            "phase": phase,
            "reason": evidence,
            "fingerprint": fingerprint,
        }
    state.revision += 1
    return recovery["status"]


def record_acquired_diagnostic_evidence(
    state: ResearchState,
    action_id: str,
    evidence: dict[str, Any],
) -> None:
    """Reopen a diagnostic only when new typed evidence is durably supplied."""
    recovery = state.diagnostic_recoveries.get(action_id)
    if recovery is None or recovery.get("status") != "needs_evidence":
        raise ValueError("diagnostic is not waiting for evidence acquisition")
    if not isinstance(evidence, dict) or not evidence:
        raise ValueError("typed diagnostic evidence is required")
    recovery["acquired_evidence"] = dict(evidence)
    failure = recovery.get("failure") or {}
    details = dict(failure.get("details") or {})
    details.update(evidence)
    failure["details"] = details
    recovery["failure"] = failure
    recovery["status"] = "open"
    recovery.pop("evidence_request", None)
    state.revision += 1
