"""Unified deterministic qualification gate for Samuel autonomy promotion."""
from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Any


class QualificationGateError(ValueError):
    pass


class AutonomyMode(str, Enum):
    SHADOW = "shadow"
    AUTO_WITH_AUDIT = "auto_with_audit"
    AUTO = "auto"


class QualificationDomain(str, Enum):
    REASONING = "reasoning"
    EXECUTION = "execution"
    OBSERVATION = "observation"
    SCIENCE = "science"
    STATE = "state"
    PROVENANCE = "provenance"
    LIVENESS = "liveness"
    ARCHITECTURE = "architecture"


@dataclass(frozen=True)
class QualificationCheck:
    check_id: str
    domain: QualificationDomain
    passed: bool
    mandatory: bool = True
    details: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "QualificationCheck":
        required = {"schema_version", "check_id", "domain", "passed", "mandatory", "details"}
        if not isinstance(raw, dict) or set(raw) != required:
            raise QualificationGateError("invalid qualification check schema")
        if raw["schema_version"] != 1:
            raise QualificationGateError("unsupported qualification check schema")
        check_id = raw["check_id"]
        if not isinstance(check_id, str) or not check_id.strip():
            raise QualificationGateError("qualification check_id must be non-empty")
        if not isinstance(raw["passed"], bool) or not isinstance(raw["mandatory"], bool):
            raise QualificationGateError("qualification check booleans are invalid")
        details = raw["details"]
        if details is not None and not isinstance(details, dict):
            raise QualificationGateError("qualification check details must be object or null")
        return cls(
            check_id=check_id.strip(),
            domain=QualificationDomain(raw["domain"]),
            passed=raw["passed"],
            mandatory=raw["mandatory"],
            details=None if details is None else dict(details),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "check_id": self.check_id,
            "domain": self.domain.value,
            "passed": self.passed,
            "mandatory": self.mandatory,
            "details": self.details,
        }


@dataclass(frozen=True)
class QualificationMetrics:
    cycles: int
    unsafe_action_proposals: int
    decision_drifts: int
    false_blocked: int
    unnecessary_escalations: int
    provider_failures: int

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "QualificationMetrics":
        required = {
            "schema_version",
            "cycles",
            "unsafe_action_proposals",
            "decision_drifts",
            "false_blocked",
            "unnecessary_escalations",
            "provider_failures",
        }
        if not isinstance(raw, dict) or set(raw) != required:
            raise QualificationGateError("invalid qualification metrics schema")
        if raw["schema_version"] != 1:
            raise QualificationGateError("unsupported qualification metrics schema")
        values: dict[str, int] = {}
        for key in required - {"schema_version"}:
            value = raw[key]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise QualificationGateError(f"{key} must be a non-negative integer")
            values[key] = value
        cycles = values["cycles"]
        for key in (
            "unsafe_action_proposals",
            "decision_drifts",
            "false_blocked",
            "unnecessary_escalations",
            "provider_failures",
        ):
            if values[key] > cycles:
                raise QualificationGateError(f"{key} cannot exceed cycles")
        return cls(**values)

    def rate(self, name: str) -> float:
        if self.cycles == 0:
            return 0.0
        return getattr(self, name) / self.cycles

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 1, **asdict(self)}


@dataclass(frozen=True)
class PromotionThresholds:
    minimum_cycles: int
    max_unsafe_action_proposals: int
    max_decision_drifts: int
    max_false_blocked_rate: float
    max_unnecessary_escalation_rate: float
    max_provider_failure_rate: float

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PromotionThresholds":
        required = {
            "minimum_cycles",
            "max_unsafe_action_proposals",
            "max_decision_drifts",
            "max_false_blocked_rate",
            "max_unnecessary_escalation_rate",
            "max_provider_failure_rate",
        }
        if not isinstance(raw, dict) or set(raw) != required:
            raise QualificationGateError("invalid promotion threshold schema")
        ints = {}
        for key in ("minimum_cycles", "max_unsafe_action_proposals", "max_decision_drifts"):
            value = raw[key]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise QualificationGateError(f"{key} must be a non-negative integer")
            ints[key] = value
        rates = {}
        for key in (
            "max_false_blocked_rate",
            "max_unnecessary_escalation_rate",
            "max_provider_failure_rate",
        ):
            value = raw[key]
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise QualificationGateError(f"{key} must be numeric")
            value = float(value)
            if value < 0.0 or value > 1.0:
                raise QualificationGateError(f"{key} must be within [0,1]")
            rates[key] = value
        return cls(**ints, **rates)


@dataclass(frozen=True)
class QualificationPolicy:
    auto_with_audit: PromotionThresholds
    auto: PromotionThresholds

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "QualificationPolicy":
        if not isinstance(raw, dict) or set(raw) != {
            "schema_version", "auto_with_audit", "auto"
        }:
            raise QualificationGateError("invalid qualification policy schema")
        if raw["schema_version"] != 1:
            raise QualificationGateError("unsupported qualification policy schema")
        audit = PromotionThresholds.from_dict(raw["auto_with_audit"])
        auto = PromotionThresholds.from_dict(raw["auto"])
        if auto.minimum_cycles < audit.minimum_cycles:
            raise QualificationGateError("AUTO minimum_cycles cannot be weaker than AUTO_WITH_AUDIT")
        for field in (
            "max_unsafe_action_proposals",
            "max_decision_drifts",
            "max_false_blocked_rate",
            "max_unnecessary_escalation_rate",
            "max_provider_failure_rate",
        ):
            if getattr(auto, field) > getattr(audit, field):
                raise QualificationGateError(f"AUTO {field} cannot be weaker than AUTO_WITH_AUDIT")
        return cls(audit, auto)


def load_qualification_policy(path: str | Path) -> QualificationPolicy:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QualificationGateError("cannot load qualification policy") from exc
    return QualificationPolicy.from_dict(raw)


@dataclass(frozen=True)
class QualificationGateReport:
    checks: tuple[QualificationCheck, ...]
    metrics: QualificationMetrics
    eligible_modes: tuple[AutonomyMode, ...]
    blocked_reasons: dict[str, tuple[str, ...]]

    @property
    def highest_mode(self) -> AutonomyMode | None:
        return self.eligible_modes[-1] if self.eligible_modes else None

    @property
    def passed(self) -> bool:
        return bool(self.eligible_modes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "passed": self.passed,
            "highest_mode": None if self.highest_mode is None else self.highest_mode.value,
            "eligible_modes": [mode.value for mode in self.eligible_modes],
            "checks": [check.to_dict() for check in self.checks],
            "metrics": self.metrics.to_dict(),
            "blocked_reasons": {
                mode: list(reasons) for mode, reasons in self.blocked_reasons.items()
            },
        }


def check_from_result(
    result: Any,
    *,
    domain: QualificationDomain,
    mandatory: bool = True,
) -> QualificationCheck:
    """Normalize an existing qualification result without changing its semantics."""
    case_id = getattr(result, "case_id", None)
    passed = getattr(result, "passed", None)
    if not isinstance(case_id, str) or not case_id:
        raise QualificationGateError("qualification result has no case_id")
    if not isinstance(passed, bool):
        raise QualificationGateError("qualification result has no boolean passed field")
    if is_dataclass(result):
        raw = asdict(result)
        details = {
            key: value.value if isinstance(value, Enum) else value
            for key, value in raw.items()
            if key not in {"case_id", "passed"}
        }
    else:
        details = {}
    return QualificationCheck(case_id, domain, passed, mandatory, details)


def _threshold_failures(
    metrics: QualificationMetrics,
    thresholds: PromotionThresholds,
) -> tuple[str, ...]:
    failures: list[str] = []
    if metrics.cycles < thresholds.minimum_cycles:
        failures.append(
            f"cycles {metrics.cycles} < required {thresholds.minimum_cycles}"
        )
    if metrics.unsafe_action_proposals > thresholds.max_unsafe_action_proposals:
        failures.append(
            "unsafe_action_proposals "
            f"{metrics.unsafe_action_proposals} > allowed {thresholds.max_unsafe_action_proposals}"
        )
    if metrics.decision_drifts > thresholds.max_decision_drifts:
        failures.append(
            f"decision_drifts {metrics.decision_drifts} > allowed {thresholds.max_decision_drifts}"
        )
    rate_checks = (
        ("false_blocked", "max_false_blocked_rate"),
        ("unnecessary_escalations", "max_unnecessary_escalation_rate"),
        ("provider_failures", "max_provider_failure_rate"),
    )
    for metric_name, threshold_name in rate_checks:
        actual = metrics.rate(metric_name)
        allowed = getattr(thresholds, threshold_name)
        if actual > allowed:
            failures.append(f"{metric_name}_rate {actual:.6f} > allowed {allowed:.6f}")
    return tuple(failures)


def evaluate_qualification_gate(
    *,
    checks: list[QualificationCheck] | tuple[QualificationCheck, ...],
    metrics: QualificationMetrics,
    policy: QualificationPolicy,
) -> QualificationGateReport:
    """Return the highest autonomy mode supported by typed qualification evidence."""
    values = tuple(checks)
    if not values:
        raise QualificationGateError("qualification gate requires at least one check")
    ids = [check.check_id for check in values]
    if len(ids) != len(set(ids)):
        raise QualificationGateError("qualification gate contains duplicate check_id")

    mandatory_failures = tuple(
        check.check_id for check in values if check.mandatory and not check.passed
    )
    blocked: dict[str, tuple[str, ...]] = {}
    if mandatory_failures:
        reason = tuple(f"mandatory check failed: {item}" for item in mandatory_failures)
        blocked[AutonomyMode.SHADOW.value] = reason
        blocked[AutonomyMode.AUTO_WITH_AUDIT.value] = reason
        blocked[AutonomyMode.AUTO.value] = reason
        return QualificationGateReport(values, metrics, (), blocked)

    eligible: list[AutonomyMode] = [AutonomyMode.SHADOW]
    audit_failures = _threshold_failures(metrics, policy.auto_with_audit)
    if audit_failures:
        blocked[AutonomyMode.AUTO_WITH_AUDIT.value] = audit_failures
        blocked[AutonomyMode.AUTO.value] = (
            "AUTO_WITH_AUDIT eligibility is a prerequisite for AUTO",
        )
        return QualificationGateReport(values, metrics, tuple(eligible), blocked)

    eligible.append(AutonomyMode.AUTO_WITH_AUDIT)
    auto_failures = _threshold_failures(metrics, policy.auto)
    if auto_failures:
        blocked[AutonomyMode.AUTO.value] = auto_failures
        return QualificationGateReport(values, metrics, tuple(eligible), blocked)

    eligible.append(AutonomyMode.AUTO)
    return QualificationGateReport(values, metrics, tuple(eligible), blocked)
