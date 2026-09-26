"""Typed execution boundary between research reasoning and deterministic executors."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Any

from .research import DecisionRisk, EscalationPolicy, ResearchStage


class ActionPlanError(ValueError):
    """Raised when a proposed action plan is malformed or unsafe to dispatch."""


class ExecutorKind(str, Enum):
    REPOSITORY_MUTATION = "repository_mutation"
    GITHUB_ACTIONS = "github_actions"
    GITHUB_NATIVE = "github_native"


def _require_nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ActionPlanError(f"{field} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True)
class ActionPlan:
    """Validated, auditable handoff from research reasoning to an executor."""

    research_id: str
    stage: ResearchStage
    executor: ExecutorKind
    payload: dict[str, Any]
    expected_observation: str
    decision_risk: DecisionRisk | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ActionPlan":
        if not isinstance(raw, dict):
            raise ActionPlanError("action plan must be an object")

        allowed = {
            "schema_version",
            "research_id",
            "stage",
            "executor",
            "payload",
            "expected_observation",
            "decision_risk",
        }
        required = {
            "schema_version",
            "research_id",
            "stage",
            "executor",
            "payload",
            "expected_observation",
        }
        extra = sorted(set(raw) - allowed)
        missing = sorted(required - set(raw))
        if extra:
            raise ActionPlanError("action plan has unknown fields: " + ", ".join(extra))
        if missing:
            raise ActionPlanError("action plan missing fields: " + ", ".join(missing))
        if raw["schema_version"] != 1:
            raise ActionPlanError("schema_version must be 1")

        try:
            stage = ResearchStage(raw["stage"])
        except (TypeError, ValueError) as exc:
            raise ActionPlanError("stage must be a valid ResearchStage") from exc
        if stage in {ResearchStage.ESCALATE, ResearchStage.COMPLETE}:
            raise ActionPlanError(f"{stage.value} cannot originate an executable action plan")

        try:
            executor = ExecutorKind(raw["executor"])
        except (TypeError, ValueError) as exc:
            raise ActionPlanError("executor is unsupported") from exc

        payload = raw["payload"]
        if not isinstance(payload, dict) or not payload:
            raise ActionPlanError("payload must be a non-empty object")

        risk = raw.get("decision_risk")
        if risk is not None:
            try:
                risk = DecisionRisk.from_dict(risk)
            except (TypeError, ValueError) as exc:
                raise ActionPlanError(str(exc)) from exc

        return cls(
            research_id=_require_nonempty_string(raw["research_id"], "research_id"),
            stage=stage,
            executor=executor,
            payload=dict(payload),
            expected_observation=_require_nonempty_string(
                raw["expected_observation"], "expected_observation"
            ),
            decision_risk=risk,
        )

    @property
    def idempotency_key(self) -> str:
        """Stable execution identity independent of dict key ordering and risk metadata."""
        semantic = {
            "research_id": self.research_id,
            "stage": self.stage.value,
            "executor": self.executor.value,
            "payload": self.payload,
            "expected_observation": self.expected_observation,
        }
        encoded = json.dumps(
            semantic,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def requires_escalation(
        self, policy: EscalationPolicy | None = None
    ) -> bool:
        if self.decision_risk is None:
            return False
        return (policy or EscalationPolicy()).requires_escalation(self.decision_risk)
