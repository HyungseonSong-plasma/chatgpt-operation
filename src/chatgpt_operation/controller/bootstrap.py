"""Deterministic root entrypoint for waking Samuel from persistent pending work."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Any

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
) -> tuple[str, Any] | None:
    """Prioritize unresolved recovery work over ordinary pending work."""
    recoveries = diagnostic_recoveries or {}
    open_ids = sorted(
        action_id
        for action_id, recovery in recoveries.items()
        if recovery.get("status") == "open"
    )
    if open_ids:
        action_id = open_ids[0]
        return ("diagnostic", {"action_id": action_id, "recovery": recoveries[action_id]})
    if pending:
        return ("pending", pending[0])
    return None
