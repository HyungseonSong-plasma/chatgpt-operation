"""Qualification that observation failure cannot be converted into absence evidence."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from .state_refresh import evaluate


@dataclass(frozen=True)
class ObservationQualificationResult:
    case_id: str
    passed: bool
    status: str
    next_action: str
    absence_claim_allowed: bool


def qualify_failed_probe(snapshot: dict[str, Any]) -> ObservationQualificationResult:
    result = evaluate(snapshot)
    blocked = result["status"] == "PROBE_BLOCKED"
    return ObservationQualificationResult(
        case_id="failed-observation-is-not-absence",
        passed=blocked and result["next_action"] == "repair_probe_or_hold",
        status=result["status"],
        next_action=result["next_action"],
        absence_claim_allowed=not blocked,
    )
