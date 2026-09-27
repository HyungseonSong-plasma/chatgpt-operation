"""Production composition root for one Samuel controller cycle.

The root owns deterministic state loading, admission lifecycle, work selection,
reasoning preflight, and typed reasoning consumption. It returns write requests
but never performs repository side effects itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import copy
from typing import Any, Callable

from .bootstrap import BootstrapWork, select_controller_work
from .command import ControllerCommand, ControllerCommandKind
from .decisions import DecisionRegistry
from .durable_state import load_state_comment, state_write_request
from .diagnostic import (
    record_action_dispatch_intent,
    record_corrective_dispatch_intent,
    record_diagnostic_dispatch_intent,
    record_evidence_dispatch_intent,
)
from .issue_ingestion import (
    ADMISSION_LABEL,
    ADMISSION_MARKER,
    admit_issue,
    decode_admission_ledger,
    encode_admission_ledger,
    transition_issue_status,
)
from .issue_planning import plan_admitted_issue
from .reasoning_consumption import consume_reasoning_submission
from .reasoning_provider import ReasoningProviderRegistry
from .research import ResearchState


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
    executor_ref: str = ""
    executor_head_sha: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ControllerTrigger":
        required = {
            "kind", "action", "head_sha", "ref",
            "executor_ref", "executor_head_sha",
        }
        if not isinstance(raw, dict) or set(raw) != required:
            raise ControllerCompositionError("invalid controller trigger schema")
        try:
            kind = TriggerKind(raw["kind"])
        except (TypeError, ValueError) as exc:
            raise ControllerCompositionError("unsupported controller trigger") from exc
        values: dict[str, str] = {}
        for key in (
            "action", "head_sha", "ref", "executor_ref", "executor_head_sha",
        ):
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
            "executor_ref": self.executor_ref,
            "executor_head_sha": self.executor_head_sha,
        }


@dataclass(frozen=True)
class ControllerCycle:
    trigger: ControllerTrigger
    selected_work: dict[str, Any]
    issue_planning: dict[str, Any] | None
    admission_write: dict[str, Any] | None = None
    state_write: dict[str, Any] | None = None
    execution_command: ControllerCommand | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 4,
            "trigger": self.trigger.to_dict(),
            "selected_work": self.selected_work,
            "issue_planning": self.issue_planning,
            "admission_write": self.admission_write,
            "state_write": self.state_write,
            "execution_command": (
                None if self.execution_command is None
                else self.execution_command.to_dict()
            ),
        }


def _admission_state(
    comments: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], int | None]:
    matches = [
        comment for comment in comments
        if ADMISSION_MARKER in str(comment.get("body", ""))
    ]
    if len(matches) > 1:
        raise ControllerCompositionError("multiple admission ledgers")
    if not matches:
        return {}, None
    comment_id = matches[0].get("id")
    if not isinstance(comment_id, int) or isinstance(comment_id, bool):
        raise ControllerCompositionError("admission ledger comment id is invalid")
    return decode_admission_ledger(str(matches[0]["body"])), comment_id


def _admission_write(
    comment_id: int | None,
    work: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "method": "POST" if comment_id is None else "PATCH",
        "comment_id": comment_id,
        "body": encode_admission_ledger(work),
    }


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


def _initial_state(work_id: str, item: dict[str, Any]) -> ResearchState:
    return ResearchState(
        work_id,
        str(item.get("title") or item.get("body") or work_id),
    )


class SamuelController:
    """Single deterministic root for selecting and preflighting one controller cycle."""

    def __init__(
        self,
        *,
        decisions: DecisionRegistry,
        reasoning: ReasoningProviderRegistry | None = None,
        now: Callable[[], datetime] | None = None,
    ):
        self.decisions = decisions
        self.reasoning = reasoning or ReasoningProviderRegistry()
        self.now = now or (lambda: datetime.now(timezone.utc))

    def _requested_at(self) -> str:
        value = self.now()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _require_executor_identity(trigger: ControllerTrigger) -> tuple[str, str]:
        if not trigger.executor_ref.strip() or not trigger.executor_head_sha.strip():
            raise ControllerCompositionError(
                "dispatch intent requires executor_ref and executor_head_sha"
            )
        return trigger.executor_ref.strip(), trigger.executor_head_sha.strip()

    def _prepare_dispatch_intent(
        self,
        *,
        trigger: ControllerTrigger,
        comments: list[dict[str, Any]],
        state: ResearchState,
        payload: dict[str, Any],
        admission_write: dict[str, Any] | None = None,
        planning: dict[str, Any] | None = None,
    ) -> ControllerCycle:
        kind = payload.get("kind")
        if kind not in {"action", "evidence", "diagnostic", "corrective"}:
            return ControllerCycle(
                trigger, payload, planning, admission_write, None
            )
        action_id = payload.get("action_id")
        if not isinstance(action_id, str) or not action_id:
            raise ControllerCompositionError("dispatch work has no action_id")
        executor_ref, executor_head_sha = self._require_executor_identity(trigger)
        proposed = copy.deepcopy(state)
        requested_at = self._requested_at()
        if kind == "action":
            record_action_dispatch_intent(
                proposed,
                action_id,
                workflow="samuel-native-github.yml",
                ref=executor_ref,
                requested_at=requested_at,
                expected_head_sha=executor_head_sha,
            )
        elif kind == "evidence":
            record_evidence_dispatch_intent(
                proposed,
                action_id,
                workflow="samuel-evidence-acquisition.yml",
                ref=executor_ref,
                requested_at=requested_at,
                expected_head_sha=executor_head_sha,
            )
        elif kind == "diagnostic":
            record_diagnostic_dispatch_intent(
                proposed,
                action_id,
                workflow="samuel-diagnostic-recovery.yml",
                ref=executor_ref,
                requested_at=requested_at,
                expected_head_sha=executor_head_sha,
            )
        else:
            record_corrective_dispatch_intent(
                proposed,
                action_id,
                workflow="samuel-native-github.yml",
                ref=executor_ref,
                requested_at=requested_at,
                expected_head_sha=executor_head_sha,
            )
        command_kind = {
            "action": ControllerCommandKind.DISPATCH_ACTION,
            "evidence": ControllerCommandKind.DISPATCH_EVIDENCE,
            "diagnostic": ControllerCommandKind.DISPATCH_DIAGNOSTIC,
            "corrective": ControllerCommandKind.DISPATCH_CORRECTIVE,
        }[kind]
        command = ControllerCommand(
            command_kind,
            action_id,
            proposed.research_id,
            proposed.revision,
        )
        return ControllerCycle(
            trigger,
            payload,
            planning,
            admission_write,
            state_write_request(comments, proposed),
            command,
        )

    @staticmethod
    def _command_for_in_flight(
        payload: dict[str, Any],
        state: ResearchState,
    ) -> ControllerCommand | None:
        mapping = {
            "action_intent": ControllerCommandKind.RECONCILE_ACTION,
            "action_observation": ControllerCommandKind.OBSERVE_ACTION,
            "evidence_intent": ControllerCommandKind.RECONCILE_EVIDENCE,
            "evidence_observation": ControllerCommandKind.OBSERVE_EVIDENCE,
            "diagnostic_intent": ControllerCommandKind.RECONCILE_DIAGNOSTIC,
            "diagnostic_observation": ControllerCommandKind.OBSERVE_DIAGNOSTIC,
            "corrective_intent": ControllerCommandKind.RECONCILE_CORRECTIVE,
            "corrective_observation": ControllerCommandKind.OBSERVE_CORRECTIVE,
        }
        command_kind = mapping.get(payload.get("kind"))
        if command_kind is None:
            return None
        action_id = payload.get("action_id")
        if not isinstance(action_id, str) or not action_id:
            raise ControllerCompositionError("in-flight work has no action_id")
        return ControllerCommand(
            command_kind,
            action_id,
            state.research_id,
            state.revision,
        )

    def _consume_waiting_reasoning(
        self,
        *,
        trigger: ControllerTrigger,
        comments: list[dict[str, Any]],
        work: dict[str, dict[str, Any]],
        work_id: str,
        state: ResearchState | None,
        admission_comment_id: int | None,
        planning: dict[str, Any] | None = None,
        prior_admission_write: dict[str, Any] | None = None,
    ) -> ControllerCycle:
        item = work.get(work_id)
        if item is None:
            raise ControllerCompositionError("reasoning work is missing from admission ledger")
        working_state = state or _initial_state(work_id, item)
        result = consume_reasoning_submission(
            comments,
            work,
            work_id,
            registry=self.decisions,
            state=working_state,
        )
        if result.outcome == "reasoning_required":
            return ControllerCycle(
                trigger,
                {"kind": "reasoning_required", "work_id": work_id},
                planning,
                prior_admission_write,
                None,
            )

        admission_write = _admission_write(admission_comment_id, result.work)
        if result.action_id is None:
            return ControllerCycle(
                trigger,
                {
                    "kind": "reasoning_consumed",
                    "work_id": work_id,
                    "outcome": result.outcome,
                    "action_id": None,
                },
                planning,
                admission_write,
                None,
            )
        queued = result.state.action_queue.get(result.action_id)
        if not isinstance(queued, dict) or not isinstance(queued.get("plan"), dict):
            raise ControllerCompositionError("planned reasoning produced no durable queued plan")
        payload = {
            "kind": "action",
            "action_id": result.action_id,
            "plan": queued["plan"],
            "reasoning_outcome": result.outcome,
            "work_id": work_id,
        }
        return self._prepare_dispatch_intent(
            trigger=trigger,
            comments=comments,
            state=result.state,
            payload=payload,
            admission_write=admission_write,
            planning=planning,
        )

    def run_cycle(
        self,
        trigger: ControllerTrigger,
        *,
        comments: list[dict[str, Any]],
        pending: list[BootstrapWork],
        issue: dict[str, Any] | None = None,
    ) -> ControllerCycle:
        if not isinstance(comments, list) or any(
            not isinstance(item, dict) for item in comments
        ):
            raise ControllerCompositionError("comments must be a list of objects")
        if issue is not None and trigger.kind is not TriggerKind.ISSUES:
            raise ControllerCompositionError(
                "issue payload is only valid for an issues trigger"
            )

        state = load_state_comment(comments)
        admitted, admission_comment_id = _admission_state(comments)
        if issue is not None:
            labels = {
                item.get("name")
                for item in issue.get("labels", [])
                if isinstance(item, dict)
            }
            if ADMISSION_LABEL in labels:
                admission = admit_issue(comments, issue)
                admitted = decode_admission_ledger(admission["body"])
                admission_comment_id = admission["comment_id"]

        waiting = sorted(
            work_id for work_id, item in admitted.items()
            if item.get("status") == "reasoning_required"
        )
        planned = sorted(
            work_id for work_id, item in admitted.items()
            if item.get("status") == "planned"
        )
        if len(waiting) > 1:
            raise ControllerCompositionError("multiple reasoning-required work items")
        if state is None and planned:
            if len(planned) != 1 or waiting:
                raise ControllerCompositionError(
                    "ambiguous planned work without durable controller state"
                )
            work_id = planned[0]
            admitted = transition_issue_status(admitted, work_id, "reasoning_required")
            recovery_write = _admission_write(admission_comment_id, admitted)
            return self._consume_waiting_reasoning(
                trigger=trigger,
                comments=comments,
                work=admitted,
                work_id=work_id,
                state=None,
                admission_comment_id=admission_comment_id,
                prior_admission_write=recovery_write,
            )
        if waiting:
            return self._consume_waiting_reasoning(
                trigger=trigger,
                comments=comments,
                work=admitted,
                work_id=waiting[0],
                state=state,
                admission_comment_id=admission_comment_id,
            )

        selected = select_controller_work(
            pending,
            diagnostic_recoveries={} if state is None else state.diagnostic_recoveries,
            action_queue={} if state is None else state.action_queue,
            admitted_work=admitted,
        )
        payload = _selected_payload(selected)
        if payload["kind"] in {"action", "evidence", "diagnostic", "corrective"}:
            if state is None:
                raise ControllerCompositionError(
                    "dispatchable work requires durable controller state"
                )
            return self._prepare_dispatch_intent(
                trigger=trigger,
                comments=comments,
                state=state,
                payload=payload,
            )
        if payload["kind"] == "pending":
            raise ControllerCompositionError(
                "legacy static workflow work is not supported by production controller"
            )
        if payload["kind"] != "issue":
            command = None if state is None else self._command_for_in_flight(
                payload, state
            )
            return ControllerCycle(
                trigger, payload, None, None, None, command
            )

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
        transitioned = transition_issue_status(
            admitted, result.work_id, "reasoning_required"
        )
        admission_write = _admission_write(admission_comment_id, transitioned)
        return self._consume_waiting_reasoning(
            trigger=trigger,
            comments=comments,
            work=transitioned,
            work_id=result.work_id,
            state=state,
            admission_comment_id=admission_comment_id,
            planning=planning,
            prior_admission_write=admission_write,
        )
