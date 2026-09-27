"""Deterministic root entrypoint for waking Samuel from persistent pending work."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Any

from chatgpt_operation.controller.action_lifecycle import ActionLifecycle
from chatgpt_operation.skills.capability_registry import (
    RegisteredProvider,
    resolve_providers,
)


class BootstrapError(ValueError):
    pass


class BootstrapKind(str, Enum):
    WORKFLOW = "workflow"


@dataclass(frozen=True)
class BootstrapWork:
    work_id: str
    kind: BootstrapKind
    workflow: str
    ref: str = "main"
    status: str = "pending"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "BootstrapWork":
        allowed={"work_id","kind","workflow","ref","status"}
        if set(raw) - allowed:
            raise BootstrapError("bootstrap work contains unknown fields")
        if not isinstance(raw.get("work_id"),str) or not raw["work_id"]:
            raise BootstrapError("work_id is required")
        if raw.get("status","pending") not in {"pending","complete","blocked"}:
            raise BootstrapError("invalid bootstrap status")
        return cls(
            work_id=raw["work_id"],
            kind=BootstrapKind(raw["kind"]),
            workflow=raw["workflow"],
            ref=raw.get("ref","main"),
            status=raw.get("status","pending"),
        )


def load_pending(path: str | Path) -> list[BootstrapWork]:
    raw=json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1 or not isinstance(raw.get("work"),list):
        raise BootstrapError("invalid bootstrap queue")
    items=[BootstrapWork.from_dict(x) for x in raw["work"]]
    ids=[x.work_id for x in items]
    if len(ids) != len(set(ids)):
        raise BootstrapError("duplicate bootstrap work_id")
    return [x for x in items if x.status == "pending"]


def resolve_bootstrap_provider(
    work: BootstrapWork,
    *,
    registry_path: str | Path = "skills/capability-registry.json",
) -> RegisteredProvider:
    """Resolve bootstrap dispatch from repository-owned capability truth."""
    if work.kind is not BootstrapKind.WORKFLOW:
        raise BootstrapError(f"unsupported bootstrap kind: {work.kind}")
    providers = resolve_providers("GITHUB_WORKFLOW_DISPATCH", path=registry_path)
    eligible = tuple(
        provider
        for provider in providers
        if provider.kind in {"skill", "workflow"}
        and provider.contract == "github-native-dispatch"
    )
    if not eligible:
        raise BootstrapError(
            "GITHUB_WORKFLOW_DISPATCH has no repository-executable provider"
        )
    return eligible[0]


def select_controller_work(
    pending: list[BootstrapWork],
    *,
    diagnostic_recoveries: dict[str, dict[str, Any]] | None = None,
    action_queue: dict[str, dict[str, Any]] | None = None,
    admitted_work: dict[str, dict[str, Any]] | None = None,
) -> tuple[str, Any] | None:
    """Prioritize unresolved recovery work over ordinary pending work."""
    actions = action_queue or {}
    valid_action_statuses = {
        ActionLifecycle.PENDING.value,
        ActionLifecycle.DISPATCH_INTENT.value,
        ActionLifecycle.DISPATCHED.value,
        ActionLifecycle.SUSPENDED.value,
        ActionLifecycle.COMPLETE.value,
        ActionLifecycle.RETIRED.value,
    }
    invalid = sorted(
        action_id for action_id, item in actions.items()
        if item.get("status") not in valid_action_statuses
    )
    if invalid:
        raise BootstrapError("durable action has unsupported lifecycle status: " + invalid[0])

    recoveries = diagnostic_recoveries or {}
    in_flight = sorted(
        action_id for action_id, item in actions.items()
        if item.get("status") in {
            ActionLifecycle.DISPATCH_INTENT.value,
            ActionLifecycle.DISPATCHED.value,
        }
    )
    evidence_in_flight: list[tuple[str, str, dict[str, Any]]] = []
    diagnostic_in_flight: list[tuple[str, str, dict[str, Any]]] = []
    corrective_in_flight: list[tuple[str, str, dict[str, Any]]] = []
    for action_id, recovery in recoveries.items():
        if recovery.get("status") == "needs_evidence":
            dispatch = recovery.get("evidence_dispatch")
            if dispatch is not None:
                if not isinstance(dispatch, dict) or dispatch.get("status") not in {
                    ActionLifecycle.DISPATCH_INTENT.value,
                    ActionLifecycle.DISPATCHED.value,
                }:
                    raise BootstrapError("evidence dispatch has unsupported lifecycle status")
                evidence_in_flight.append((action_id, dispatch["status"], dispatch))
        if recovery.get("status") == "open":
            dispatch = recovery.get("diagnostic_dispatch")
            if dispatch is not None:
                if not isinstance(dispatch, dict) or dispatch.get("status") not in {
                    ActionLifecycle.DISPATCH_INTENT.value,
                    ActionLifecycle.DISPATCHED.value,
                }:
                    raise BootstrapError("diagnostic dispatch has unsupported lifecycle status")
                diagnostic_in_flight.append((action_id, dispatch["status"], dispatch))
            corrective = recovery.get("corrective_dispatch")
            if corrective is not None:
                if not isinstance(corrective, dict) or corrective.get("status") not in {
                    ActionLifecycle.DISPATCH_INTENT.value,
                    ActionLifecycle.DISPATCHED.value,
                }:
                    raise BootstrapError("corrective dispatch has unsupported lifecycle status")
                corrective_in_flight.append(
                    (action_id, corrective["status"], corrective)
                )

    if (
        len(in_flight)
        + len(evidence_in_flight)
        + len(diagnostic_in_flight)
        + len(corrective_in_flight)
        > 1
    ):
        raise BootstrapError("multiple in-flight durable workflows")
    if in_flight:
        action_id = in_flight[0]
        item = actions[action_id]
        if not isinstance(item.get("plan"), dict):
            raise BootstrapError("in-flight durable action has no typed plan")
        if item.get("status") == ActionLifecycle.DISPATCH_INTENT.value:
            if not isinstance(item.get("dispatch_intent"), dict):
                raise BootstrapError("dispatch intent lifecycle has no typed intent")
            return ("action_intent", {
                "action_id": action_id,
                "plan": item["plan"],
                "dispatch_intent": item["dispatch_intent"],
            })
        if not isinstance(item.get("dispatch_receipt"), dict):
            raise BootstrapError("dispatched lifecycle has no typed receipt")
        return ("action_observation", {
            "action_id": action_id,
            "plan": item["plan"],
            "dispatch_receipt": item["dispatch_receipt"],
        })
    if corrective_in_flight:
        action_id, status, dispatch = corrective_in_flight[0]
        if not isinstance(dispatch.get("intent"), dict):
            raise BootstrapError("corrective dispatch lifecycle has no typed intent")
        if status == ActionLifecycle.DISPATCH_INTENT.value:
            return ("corrective_intent", {
                "action_id": action_id,
                "recovery": recoveries[action_id],
            })
        if not isinstance(dispatch.get("receipt"), dict):
            raise BootstrapError("dispatched corrective lifecycle has no typed receipt")
        return ("corrective_observation", {
            "action_id": action_id,
            "recovery": recoveries[action_id],
        })

    if evidence_in_flight:
        action_id, status, dispatch = evidence_in_flight[0]
        if not isinstance(dispatch.get("intent"), dict):
            raise BootstrapError("evidence dispatch lifecycle has no typed intent")
        if status == ActionLifecycle.DISPATCH_INTENT.value:
            return ("evidence_intent", {
                "action_id": action_id,
                "recovery": recoveries[action_id],
            })
        if not isinstance(dispatch.get("receipt"), dict):
            raise BootstrapError("dispatched evidence lifecycle has no typed receipt")
        return ("evidence_observation", {
            "action_id": action_id,
            "recovery": recoveries[action_id],
        })

    if diagnostic_in_flight:
        action_id, status, dispatch = diagnostic_in_flight[0]
        if not isinstance(dispatch.get("intent"), dict):
            raise BootstrapError("diagnostic dispatch lifecycle has no typed intent")
        if status == ActionLifecycle.DISPATCH_INTENT.value:
            return ("diagnostic_intent", {
                "action_id": action_id,
                "recovery": recoveries[action_id],
            })
        if not isinstance(dispatch.get("receipt"), dict):
            raise BootstrapError("dispatched diagnostic lifecycle has no typed receipt")
        return ("diagnostic_observation", {
            "action_id": action_id,
            "recovery": recoveries[action_id],
        })

    corrective_ids = sorted(
        action_id
        for action_id, recovery in recoveries.items()
        if recovery.get("status") == "open"
        and recovery.get("root_cause")
        and recovery.get("corrective_action")
        and recovery.get("corrective_provider")
        and not recovery.get("resolution_evidence")
        and recovery.get("corrective_dispatch") is None
        and recovery.get("diagnostic_dispatch") is None
    )
    if corrective_ids:
        action_id = corrective_ids[0]
        return ("corrective", {
            "action_id": action_id,
            "recovery": recoveries[action_id],
        })

    open_ids = sorted(
        action_id
        for action_id, recovery in recoveries.items()
        if recovery.get("status") == "open"
    )
    if open_ids:
        action_id = open_ids[0]
        return ("diagnostic", {"action_id": action_id, "recovery": recoveries[action_id]})
    evidence_ids = sorted(
        action_id for action_id, recovery in recoveries.items()
        if recovery.get("status") == "needs_evidence"
        and recovery.get("evidence_dispatch") is None
    )
    if evidence_ids:
        action_id = evidence_ids[0]
        return ("evidence", {"action_id": action_id, "recovery": recoveries[action_id]})
    pending_actions = sorted(
        action_id for action_id, item in actions.items()
        if item.get("status") == "pending"
    )
    if pending_actions:
        action_id = pending_actions[0]
        item = actions[action_id]
        if not isinstance(item.get("plan"), dict):
            raise BootstrapError("pending durable action has no typed plan")
        return ("action", {"action_id": action_id, "plan": item["plan"]})
    admitted = admitted_work or {}
    admitted_ids = sorted(
        work_id for work_id, item in admitted.items()
        if item.get("status") == "admitted"
    )
    if admitted_ids:
        work_id = admitted_ids[0]
        item = admitted[work_id]
        if item.get("work_id") != work_id:
            raise BootstrapError("admitted work identity mismatch")
        return ("issue", dict(item))
    if pending:
        return ("pending", pending[0])
    return None
