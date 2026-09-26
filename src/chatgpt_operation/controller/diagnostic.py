"""Deterministic diagnostic recovery engine driven by typed execution evidence."""
from __future__ import annotations

from dataclasses import dataclass

from .execution import (
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
