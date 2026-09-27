"""Deterministic diagnostic recovery engine driven by typed execution evidence."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from .action_plan import ActionPlan, ExecutorKind
from .action_lifecycle import ActionLifecycle, DispatchIntent

from .execution import (
    ExecutionStatus,
    diagnostic_next_action,
    require_execution_provenance,
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


def _serialized_plan(plan: ActionPlan) -> dict[str, Any]:
    return {
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


def enqueue_suspended_action(state: ResearchState, plan: ActionPlan) -> None:
    """Persist ownership of an action without allowing identity overwrite."""
    if plan.research_id != state.research_id:
        raise ValueError("queued plan belongs to a different research state")
    action_id = plan.idempotency_key
    serialized = _serialized_plan(plan)
    existing = state.action_queue.get(action_id)
    if existing is not None:
        if existing.get("plan") == serialized:
            return
        raise ValueError("action id already owns a different plan")
    state.action_queue[action_id] = {
        "status": ActionLifecycle.PENDING.value,
        "plan": serialized,
    }
    state.revision += 1


def record_action_dispatch_intent(
    state: ResearchState,
    action_id: str,
    *,
    workflow: str,
    ref: str,
    requested_at: str,
    expected_head_sha: str,
) -> DispatchIntent:
    """Durably reserve one logical dispatch before the external side effect."""
    if not isinstance(workflow, str) or not workflow.strip():
        raise ValueError("workflow must be a non-empty string")
    if not isinstance(ref, str) or not ref.strip():
        raise ValueError("ref must be a non-empty string")
    item = state.action_queue.get(action_id)
    if item is None:
        raise ValueError("action is not owned by durable queue")
    plan = ActionPlan.from_dict(item.get("plan"))
    if plan.idempotency_key != action_id or plan.research_id != state.research_id:
        raise ValueError("queued action identity changed")

    if item.get("status") == ActionLifecycle.DISPATCH_INTENT.value:
        intent = DispatchIntent.from_dict(item.get("dispatch_intent"))
        if (
            intent.workflow != workflow
            or intent.ref != ref
            or intent.expected_head_sha != expected_head_sha
        ):
            raise ValueError("existing dispatch intent conflicts with requested dispatch")
        return intent
    if item.get("status") != ActionLifecycle.PENDING.value:
        raise ValueError("action is not pending")

    intent = DispatchIntent.from_dict({
        "schema_version": 2,
        "action_id": action_id,
        "research_id": state.research_id,
        "workflow": workflow,
        "ref": ref,
        "requested_at": requested_at,
        "state_revision": state.revision + 1,
        "expected_head_sha": expected_head_sha,
    })
    item["dispatch_intent"] = intent.to_dict()
    item["status"] = ActionLifecycle.DISPATCH_INTENT.value
    state.revision += 1
    return intent


def resume_dispatch_intent(
    state: ResearchState,
    action_id: str,
) -> tuple[ActionPlan, DispatchIntent]:
    """Resume only the exact pre-dispatch transaction already persisted."""
    item = state.action_queue.get(action_id)
    if item is None or item.get("status") != ActionLifecycle.DISPATCH_INTENT.value:
        raise ValueError("action is not awaiting dispatch")
    plan = ActionPlan.from_dict(item.get("plan"))
    intent = DispatchIntent.from_dict(item.get("dispatch_intent"))
    if (
        plan.idempotency_key != action_id
        or intent.action_id != action_id
        or intent.research_id != state.research_id
    ):
        raise ValueError("dispatch intent identity changed")
    return plan, intent


def record_action_dispatch(
    state: ResearchState,
    action_id: str,
    receipt: dict[str, Any],
) -> None:
    """Bind one external dispatch receipt to a previously persisted intent."""
    item = state.action_queue.get(action_id)
    if item is None:
        raise ValueError("action is not owned by durable queue")
    if item.get("status") == ActionLifecycle.DISPATCHED.value:
        existing = item.get("dispatch_receipt")
        if existing == receipt:
            return
        raise ValueError("action already has a different dispatch receipt")
    if item.get("status") != ActionLifecycle.DISPATCH_INTENT.value:
        raise ValueError("action has no durable dispatch intent")

    intent = DispatchIntent.from_dict(item.get("dispatch_intent"))
    if not isinstance(receipt, dict) or receipt.get("correlation_id") != action_id:
        raise ValueError("dispatch receipt does not match queued action")
    run_id = receipt.get("workflow_run_id")
    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id < 1:
        raise ValueError("dispatch receipt has no authoritative workflow_run_id")
    if receipt.get("ref") != intent.ref:
        raise ValueError("dispatch receipt ref does not match intent")
    workflow_path = receipt.get("workflow_path")
    if workflow_path is not None and str(workflow_path).rsplit("/", 1)[-1] != intent.workflow:
        raise ValueError("dispatch receipt workflow does not match intent")

    item["dispatch_receipt"] = dict(receipt)
    item["status"] = ActionLifecycle.DISPATCHED.value
    state.revision += 1


def record_native_dispatch_evidence_failure(
    state: ResearchState,
    action_id: str,
    *,
    workflow_run_id: int,
    conclusion: str,
    failure_kind: str,
) -> None:
    """Retire one native dispatch whose terminal result evidence is unusable.

    The logical ActionPlan remains pending. The failed physical attempt is retained
    for audit, and only the idempotent native executor may take this recovery path.
    """
    item = state.action_queue.get(action_id)
    if item is None or item.get("status") != ActionLifecycle.DISPATCHED.value:
        raise ValueError("action is not dispatched")
    plan = ActionPlan.from_dict(item.get("plan"))
    if plan.executor is not ExecutorKind.GITHUB_NATIVE:
        raise ValueError("only github_native dispatches may recover invalid result evidence")
    receipt = item.get("dispatch_receipt")
    if not isinstance(receipt, dict) or receipt.get("workflow_run_id") != workflow_run_id:
        raise ValueError("terminal evidence does not match dispatched workflow run")
    if not isinstance(conclusion, str) or not conclusion.strip():
        raise ValueError("terminal workflow conclusion is required")
    if not isinstance(failure_kind, str) or not failure_kind.strip():
        raise ValueError("dispatch evidence failure kind is required")
    intent = DispatchIntent.from_dict(item.get("dispatch_intent"))
    history = list(item.get("dispatch_attempt_history", []))
    history.append({
        "schema_version": 1,
        "workflow_run_id": workflow_run_id,
        "conclusion": conclusion.strip(),
        "failure_kind": failure_kind.strip(),
        "dispatch_intent": intent.to_dict(),
        "dispatch_receipt": dict(receipt),
    })
    item["dispatch_attempt_history"] = history
    item.pop("dispatch_intent", None)
    item.pop("dispatch_receipt", None)
    item["status"] = ActionLifecycle.PENDING.value
    state.revision += 1


def resume_dispatched_action(
    state: ResearchState,
    action_id: str,
) -> tuple[ActionPlan, dict[str, Any]]:
    """Return the exact plan and receipt for a previously dispatched action."""
    item = state.action_queue.get(action_id)
    if item is None or item.get("status") != ActionLifecycle.DISPATCHED.value:
        raise ValueError("action is not awaiting observation")
    plan = ActionPlan.from_dict(item.get("plan"))
    intent = DispatchIntent.from_dict(item.get("dispatch_intent"))
    receipt = item.get("dispatch_receipt")
    if (
        plan.idempotency_key != action_id
        or intent.action_id != action_id
        or intent.research_id != state.research_id
        or not isinstance(receipt, dict)
    ):
        raise ValueError("dispatched action identity changed")
    if receipt.get("correlation_id") != action_id or receipt.get("ref") != intent.ref:
        raise ValueError("dispatch receipt correlation changed")
    return plan, dict(receipt)


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
    if item is None or item.get("status") != ActionLifecycle.DISPATCHED.value:
        raise ValueError("action is not dispatched")
    if result.action_id != action_id or result.research_id != state.research_id:
        raise ValueError("execution result does not match queued action")
    if result.status not in {ExecutionStatus.PASS, ExecutionStatus.NOOP}:
        raise ValueError("queued action requires PASS/NOOP completion evidence")
    receipt = item.get("dispatch_receipt")
    run_id = None if not isinstance(receipt, dict) else receipt.get("workflow_run_id")
    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id < 1:
        raise ValueError("dispatched action has no authoritative workflow_run_id")
    intent = DispatchIntent.from_dict(item.get("dispatch_intent"))
    require_execution_provenance(
        result,
        workflow_run_id=run_id,
        head_sha=intent.expected_head_sha,
    )
    item["status"] = ActionLifecycle.COMPLETE.value
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


def diagnostic_dispatch_correlation_id(
    state: ResearchState,
    action_id: str,
) -> str:
    """Return the deterministic identity for one diagnostic phase execution."""
    recovery = state.diagnostic_recoveries.get(action_id)
    if recovery is None or recovery.get("status") != "open":
        raise ValueError("diagnostic recovery is not open")
    semantic_recovery = {
        key: value for key, value in recovery.items()
        if key != "diagnostic_dispatch"
    }
    semantic = {
        "kind": "diagnostic",
        "research_id": state.research_id,
        "action_id": action_id,
        "recovery": semantic_recovery,
    }
    return "diagnostic-" + hashlib.sha256(json.dumps(
        semantic, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()


def record_diagnostic_dispatch_intent(
    state: ResearchState,
    action_id: str,
    *,
    workflow: str,
    ref: str,
    requested_at: str,
    expected_head_sha: str,
) -> tuple[DispatchIntent, str]:
    """Persist one diagnostic workflow intent before external dispatch."""
    recovery = state.diagnostic_recoveries.get(action_id)
    if recovery is None or recovery.get("status") != "open":
        raise ValueError("diagnostic recovery is not open")
    correlation_id = diagnostic_dispatch_correlation_id(state, action_id)
    existing = recovery.get("diagnostic_dispatch")
    if existing is not None:
        if not isinstance(existing, dict) or existing.get("status") not in {
            ActionLifecycle.DISPATCH_INTENT.value,
            ActionLifecycle.DISPATCHED.value,
        }:
            raise ValueError("invalid diagnostic dispatch lifecycle")
        intent = DispatchIntent.from_dict(existing.get("intent"))
        if (
            existing.get("correlation_id") != correlation_id
            or intent.workflow != workflow
            or intent.ref != ref
            or intent.expected_head_sha != expected_head_sha
        ):
            raise ValueError("existing diagnostic dispatch conflicts with requested dispatch")
        return intent, correlation_id

    intent = DispatchIntent.from_dict({
        "schema_version": 2,
        "action_id": action_id,
        "research_id": state.research_id,
        "workflow": workflow,
        "ref": ref,
        "requested_at": requested_at,
        "state_revision": state.revision + 1,
        "expected_head_sha": expected_head_sha,
    })
    recovery["diagnostic_dispatch"] = {
        "status": ActionLifecycle.DISPATCH_INTENT.value,
        "correlation_id": correlation_id,
        "intent": intent.to_dict(),
    }
    state.revision += 1
    return intent, correlation_id


def resume_diagnostic_dispatch_intent(
    state: ResearchState,
    action_id: str,
) -> tuple[DispatchIntent, str]:
    recovery = state.diagnostic_recoveries.get(action_id)
    if recovery is None or recovery.get("status") != "open":
        raise ValueError("diagnostic recovery is not open")
    dispatch = recovery.get("diagnostic_dispatch")
    if not isinstance(dispatch, dict) or dispatch.get("status") != ActionLifecycle.DISPATCH_INTENT.value:
        raise ValueError("diagnostic recovery is not awaiting dispatch")
    intent = DispatchIntent.from_dict(dispatch.get("intent"))
    correlation_id = diagnostic_dispatch_correlation_id(state, action_id)
    if (
        intent.action_id != action_id
        or intent.research_id != state.research_id
        or dispatch.get("correlation_id") != correlation_id
    ):
        raise ValueError("diagnostic dispatch intent identity changed")
    return intent, correlation_id


def record_diagnostic_dispatch(
    state: ResearchState,
    action_id: str,
    receipt: dict[str, Any],
) -> None:
    recovery = state.diagnostic_recoveries.get(action_id)
    if recovery is None or recovery.get("status") != "open":
        raise ValueError("diagnostic recovery is not open")
    dispatch = recovery.get("diagnostic_dispatch")
    if not isinstance(dispatch, dict):
        raise ValueError("diagnostic recovery has no durable dispatch intent")
    if dispatch.get("status") == ActionLifecycle.DISPATCHED.value:
        if dispatch.get("receipt") == receipt:
            return
        raise ValueError("diagnostic recovery already has a different receipt")
    if dispatch.get("status") != ActionLifecycle.DISPATCH_INTENT.value:
        raise ValueError("diagnostic recovery is not awaiting dispatch")
    intent = DispatchIntent.from_dict(dispatch.get("intent"))
    correlation_id = diagnostic_dispatch_correlation_id(state, action_id)
    if not isinstance(receipt, dict) or receipt.get("correlation_id") != correlation_id:
        raise ValueError("diagnostic dispatch receipt correlation mismatch")
    run_id = receipt.get("workflow_run_id")
    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id < 1:
        raise ValueError("diagnostic dispatch receipt has no authoritative workflow_run_id")
    if receipt.get("ref") != intent.ref:
        raise ValueError("diagnostic dispatch receipt ref mismatch")
    workflow_path = receipt.get("workflow_path")
    if workflow_path is not None and str(workflow_path).rsplit("/", 1)[-1] != intent.workflow:
        raise ValueError("diagnostic dispatch receipt workflow mismatch")
    dispatch["receipt"] = dict(receipt)
    dispatch["status"] = ActionLifecycle.DISPATCHED.value
    state.revision += 1


def resume_dispatched_diagnostic(
    state: ResearchState,
    action_id: str,
) -> tuple[DispatchIntent, str, dict[str, Any]]:
    recovery = state.diagnostic_recoveries.get(action_id)
    if recovery is None or recovery.get("status") != "open":
        raise ValueError("diagnostic recovery is not open")
    dispatch = recovery.get("diagnostic_dispatch")
    if not isinstance(dispatch, dict) or dispatch.get("status") != ActionLifecycle.DISPATCHED.value:
        raise ValueError("diagnostic recovery is not dispatched")
    intent = DispatchIntent.from_dict(dispatch.get("intent"))
    receipt = dispatch.get("receipt")
    correlation_id = diagnostic_dispatch_correlation_id(state, action_id)
    if (
        intent.action_id != action_id
        or intent.research_id != state.research_id
        or dispatch.get("correlation_id") != correlation_id
        or not isinstance(receipt, dict)
        or receipt.get("correlation_id") != correlation_id
    ):
        raise ValueError("diagnostic dispatch identity changed")
    return intent, correlation_id, dict(receipt)


def evidence_dispatch_correlation_id(
    state: ResearchState,
    action_id: str,
) -> str:
    """Return the deterministic identity for one evidence-acquisition request."""
    recovery = state.diagnostic_recoveries.get(action_id)
    if recovery is None or recovery.get("status") != "needs_evidence":
        raise ValueError("diagnostic is not waiting for evidence acquisition")
    request = recovery.get("evidence_request")
    fingerprint = None if not isinstance(request, dict) else request.get("fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint.strip():
        raise ValueError("evidence request fingerprint is required")
    semantic = {
        "kind": "evidence",
        "research_id": state.research_id,
        "action_id": action_id,
        "request_fingerprint": fingerprint.strip(),
    }
    return "evidence-" + hashlib.sha256(json.dumps(
        semantic, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()


def record_evidence_dispatch_intent(
    state: ResearchState,
    action_id: str,
    *,
    workflow: str,
    ref: str,
    requested_at: str,
    expected_head_sha: str,
) -> tuple[DispatchIntent, str]:
    """Persist evidence-dispatch intent before any external workflow side effect."""
    recovery = state.diagnostic_recoveries.get(action_id)
    if recovery is None or recovery.get("status") != "needs_evidence":
        raise ValueError("diagnostic is not waiting for evidence acquisition")
    correlation_id = evidence_dispatch_correlation_id(state, action_id)
    existing = recovery.get("evidence_dispatch")
    if existing is not None:
        if not isinstance(existing, dict) or existing.get("status") not in {
            ActionLifecycle.DISPATCH_INTENT.value,
            ActionLifecycle.DISPATCHED.value,
        }:
            raise ValueError("invalid evidence dispatch lifecycle")
        intent = DispatchIntent.from_dict(existing.get("intent"))
        if (
            existing.get("correlation_id") != correlation_id
            or intent.workflow != workflow
            or intent.ref != ref
            or intent.expected_head_sha != expected_head_sha
        ):
            raise ValueError("existing evidence dispatch conflicts with requested dispatch")
        return intent, correlation_id

    intent = DispatchIntent.from_dict({
        "schema_version": 2,
        "action_id": action_id,
        "research_id": state.research_id,
        "workflow": workflow,
        "ref": ref,
        "requested_at": requested_at,
        "state_revision": state.revision + 1,
        "expected_head_sha": expected_head_sha,
    })
    recovery["evidence_dispatch"] = {
        "status": ActionLifecycle.DISPATCH_INTENT.value,
        "correlation_id": correlation_id,
        "intent": intent.to_dict(),
    }
    state.revision += 1
    return intent, correlation_id


def resume_evidence_dispatch_intent(
    state: ResearchState,
    action_id: str,
) -> tuple[DispatchIntent, str]:
    recovery = state.diagnostic_recoveries.get(action_id)
    if recovery is None or recovery.get("status") != "needs_evidence":
        raise ValueError("diagnostic is not waiting for evidence acquisition")
    dispatch = recovery.get("evidence_dispatch")
    if not isinstance(dispatch, dict) or dispatch.get("status") != ActionLifecycle.DISPATCH_INTENT.value:
        raise ValueError("evidence acquisition is not awaiting dispatch")
    intent = DispatchIntent.from_dict(dispatch.get("intent"))
    correlation_id = evidence_dispatch_correlation_id(state, action_id)
    if (
        intent.action_id != action_id
        or intent.research_id != state.research_id
        or dispatch.get("correlation_id") != correlation_id
    ):
        raise ValueError("evidence dispatch intent identity changed")
    return intent, correlation_id


def record_evidence_dispatch(
    state: ResearchState,
    action_id: str,
    receipt: dict[str, Any],
) -> None:
    recovery = state.diagnostic_recoveries.get(action_id)
    if recovery is None or recovery.get("status") != "needs_evidence":
        raise ValueError("diagnostic is not waiting for evidence acquisition")
    dispatch = recovery.get("evidence_dispatch")
    if not isinstance(dispatch, dict):
        raise ValueError("evidence acquisition has no durable dispatch intent")
    if dispatch.get("status") == ActionLifecycle.DISPATCHED.value:
        if dispatch.get("receipt") == receipt:
            return
        raise ValueError("evidence acquisition already has a different receipt")
    if dispatch.get("status") != ActionLifecycle.DISPATCH_INTENT.value:
        raise ValueError("evidence acquisition is not awaiting dispatch")
    intent = DispatchIntent.from_dict(dispatch.get("intent"))
    correlation_id = evidence_dispatch_correlation_id(state, action_id)
    if not isinstance(receipt, dict) or receipt.get("correlation_id") != correlation_id:
        raise ValueError("evidence dispatch receipt correlation mismatch")
    run_id = receipt.get("workflow_run_id")
    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id < 1:
        raise ValueError("evidence dispatch receipt has no authoritative workflow_run_id")
    if receipt.get("ref") != intent.ref:
        raise ValueError("evidence dispatch receipt ref mismatch")
    workflow_path = receipt.get("workflow_path")
    if workflow_path is not None and str(workflow_path).rsplit("/", 1)[-1] != intent.workflow:
        raise ValueError("evidence dispatch receipt workflow mismatch")
    dispatch["receipt"] = dict(receipt)
    dispatch["status"] = ActionLifecycle.DISPATCHED.value
    state.revision += 1


def resume_dispatched_evidence(
    state: ResearchState,
    action_id: str,
) -> tuple[DispatchIntent, str, dict[str, Any]]:
    recovery = state.diagnostic_recoveries.get(action_id)
    if recovery is None or recovery.get("status") != "needs_evidence":
        raise ValueError("diagnostic is not waiting for evidence acquisition")
    dispatch = recovery.get("evidence_dispatch")
    if not isinstance(dispatch, dict) or dispatch.get("status") != ActionLifecycle.DISPATCHED.value:
        raise ValueError("evidence acquisition is not dispatched")
    intent = DispatchIntent.from_dict(dispatch.get("intent"))
    receipt = dispatch.get("receipt")
    correlation_id = evidence_dispatch_correlation_id(state, action_id)
    if (
        intent.action_id != action_id
        or intent.research_id != state.research_id
        or dispatch.get("correlation_id") != correlation_id
        or not isinstance(receipt, dict)
        or receipt.get("correlation_id") != correlation_id
    ):
        raise ValueError("evidence dispatch identity changed")
    return intent, correlation_id, dict(receipt)


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
    recovery.pop("evidence_dispatch", None)
    state.revision += 1
