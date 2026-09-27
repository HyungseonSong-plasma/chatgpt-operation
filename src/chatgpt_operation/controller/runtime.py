"""Production composition root for one Samuel controller cycle.

The root owns deterministic state loading, work selection, and reasoning preflight.
It does not execute repository side effects; execution remains behind typed gateways.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .bootstrap import BootstrapWork, select_controller_work
from .decisions import DecisionRegistry
from .durable_state import load_state_comment
from .issue_ingestion import ADMISSION_MARKER, decode_admission_ledger
from .issue_planning import plan_admitted_issue
from .reasoning_provider import ReasoningProviderRegistry


class ControllerCompositionError(ValueError):
    pass


class TriggerKind(str, Enum):
    SCHEDULE = "schedule"
    WORKFLOW_DISPATCH = "workflow_dispatch"
    ISSUES = "issues"
    PULL_REQUEST = "pull_request"
    ISSUE_COMMENT = "issue_comment"
    RETRY = "retry"
    BOOTSTRAP = "bootstrap"


@dataclass(frozen=True)
class ControllerTrigger:
    kind: TriggerKind
    action: str = ""
    head_sha: str = ""
    ref: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ControllerTrigger":
        required = {"kind", "action", "head_sha", "ref"}
        if not isinstance(raw, dict) or set(raw) != required:
            raise ControllerCompositionError("invalid controller trigger schema")
        try:
            kind = TriggerKind(raw["kind"])
        except (TypeError, ValueError) as exc:
            raise ControllerCompositionError("unsupported controller trigger") from exc
        values: dict[str, str] = {}
        for key in ("action", "head_sha", "ref"):
            value = raw[key]
            if not isinstance(value, str):
                raise ControllerCompositionError(f"trigger {key} must be a string")
            values[key] = value
        return cls(kind=kind, **values)

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "action": self.action,
            "head_sha": self.head_sha,
            "ref": self.ref,
        }


@dataclass(frozen=True)
class ControllerCycle:
    trigger: ControllerTrigger
    selected_work: dict[str, Any]
    issue_planning: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "trigger": self.trigger.to_dict(),
            "selected_work": self.selected_work,
            "issue_planning": self.issue_planning,
        }


def _admitted_work(comments: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    matches = [
        comment for comment in comments
        if ADMISSION_MARKER in str(comment.get("body", ""))
    ]
    if len(matches) > 1:
        raise ControllerCompositionError("multiple admission ledgers")
    return {} if not matches else decode_admission_ledger(str(matches[0]["body"]))


def _selected_payload(selected: tuple[str, Any] | None) -> dict[str, Any]:
    if selected is None:
        return {"kind": "idle"}
    kind, value = selected
    if kind == "pending":
        if not isinstance(value, BootstrapWork):
            raise ControllerCompositionError("pending work has invalid type")
        return {
            "kind": "pending",
            "work_id": value.work_id,
            "workflow": value.workflow,
            "ref": value.ref,
        }
    if not isinstance(value, dict):
        raise ControllerCompositionError("selected work payload must be an object")
    return {"kind": kind, **value}


class SamuelController:
    """Single deterministic root for selecting and preflighting one controller cycle."""

    def __init__(
        self,
        *,
        decisions: DecisionRegistry,
        reasoning: ReasoningProviderRegistry | None = None,
    ):
        self.decisions = decisions
        self.reasoning = reasoning or ReasoningProviderRegistry()

    def run_cycle(
        self,
        trigger: ControllerTrigger,
        *,
        comments: list[dict[str, Any]],
        pending: list[BootstrapWork],
    ) -> ControllerCycle:
        if not isinstance(comments, list) or any(
            not isinstance(item, dict) for item in comments
        ):
            raise ControllerCompositionError("comments must be a list of objects")

        state = load_state_comment(comments)
        admitted = _admitted_work(comments)
        selected = select_controller_work(
            pending,
            diagnostic_recoveries={} if state is None else state.diagnostic_recoveries,
            action_queue={} if state is None else state.action_queue,
            admitted_work=admitted,
        )
        payload = _selected_payload(selected)
        planning = None
        if payload["kind"] == "issue":
            result = plan_admitted_issue(payload, registry=self.decisions)
            provider = self.reasoning.status()
            planning = {
                "schema_version": 1,
                "work_id": result.work_id,
                "outcome": "reasoning_required",
                "reason": (
                    "semantic reasoning provider available; reasoning step required"
                    if provider.available
                    else "external semantic reasoning worker required"
                ),
                "blocker": None,
                "semantic_provider": {
                    "available": provider.available,
                    "provider": provider.provider,
                },
                "action_plan": None,
                "reasoning_context": result.envelope.as_reasoning_context(),
            }
        return ControllerCycle(trigger, payload, planning)
