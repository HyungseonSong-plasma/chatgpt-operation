"""Deterministic throughput/liveness planning for scheduled work controllers."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


class ThroughputError(ValueError):
    """Raised when controller throughput evidence is malformed."""


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ThroughputError(f"{name} must be an object")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ThroughputError(f"{name} must be a non-empty string")
    return value


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ThroughputError(f"{name} must be a boolean")
    return value


def _count(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ThroughputError(f"{name} must be a non-negative integer")
    return value


def _resources(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ThroughputError(f"{name} must be an array")
    out: list[str] = []
    for index, item in enumerate(value):
        text = _text(item, f"{name}[{index}]")
        if text in out:
            raise ThroughputError(f"{name} contains duplicate resource {text!r}")
        out.append(text)
    return tuple(out)


def _result(
    status: str,
    *,
    can_progress: bool,
    next_action: str,
    reason: str,
    selected_tasks: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "can_progress": can_progress,
        "next_action": next_action,
        "reason": reason,
        "selected_tasks": selected_tasks or [],
    }


def evaluate(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Plan one controller work burst."""

    data = _mapping(snapshot, "snapshot")
    if data.get("schema_version") != 1:
        raise ThroughputError("schema_version must be 1")

    authority = _mapping(data.get("authority"), "authority")
    desired_state = _text(authority.get("desired_state"), "authority.desired_state")
    durable_state = _text(authority.get("durable_state"), "authority.durable_state")
    synchronized = _boolean(authority.get("synchronized"), "authority.synchronized")
    if desired_state not in {"ACTIVE", "PAUSED"}:
        raise ThroughputError("authority.desired_state must be ACTIVE or PAUSED")
    if durable_state not in {"ACTIVE", "PAUSED"}:
        raise ThroughputError("authority.durable_state must be ACTIVE or PAUSED")

    if desired_state == "PAUSED":
        return _result(
            "PAUSED",
            can_progress=False,
            next_action="remain_paused",
            reason="desired controller authority is paused",
        )

    if durable_state != desired_state or not synchronized:
        return _result(
            "SYNC_AUTHORITY",
            can_progress=False,
            next_action="synchronize_durable_authority",
            reason="scheduled controller authority and durable work state disagree",
        )

    validation = _mapping(data.get("validation"), "validation")
    required = _boolean(validation.get("required"), "validation.required")
    launch_expected = _boolean(
        validation.get("launch_expected"), "validation.launch_expected"
    )
    exact_head_runs = _count(
        validation.get("exact_head_runs"), "validation.exact_head_runs"
    )
    active_runs = _count(validation.get("active_runs"), "validation.active_runs")
    terminal_runs = _count(
        validation.get("terminal_runs"), "validation.terminal_runs"
    )
    lock_scope = _text(validation.get("lock_scope"), "validation.lock_scope")
    if lock_scope not in {"NONE", "SCOPED", "GLOBAL"}:
        raise ThroughputError("validation.lock_scope must be NONE, SCOPED, or GLOBAL")
    locked_resources = set(
        _resources(validation.get("locked_resources", []), "validation.locked_resources")
    )

    if active_runs > exact_head_runs or terminal_runs > exact_head_runs:
        raise ThroughputError("active/terminal run counts exceed exact_head_runs")
    if active_runs + terminal_runs > exact_head_runs:
        raise ThroughputError("active_runs + terminal_runs exceeds exact_head_runs")

    if required and launch_expected and exact_head_runs == 0:
        return _result(
            "MISSING_VALIDATION_ROUTE",
            can_progress=False,
            next_action="repair_or_explicitly_trigger_validation_route",
            reason="required exact-head validation was expected but no run exists",
        )

    max_lanes = _count(data.get("max_lanes", 1), "max_lanes")
    if max_lanes < 1 or max_lanes > 4:
        raise ThroughputError("max_lanes must be between 1 and 4")

    tasks_raw = data.get("tasks")
    if not isinstance(tasks_raw, Sequence) or isinstance(tasks_raw, (str, bytes)):
        raise ThroughputError("tasks must be an array")

    tasks: list[tuple[str, bool, bool, tuple[str, ...]]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(tasks_raw):
        task = _mapping(raw, f"tasks[{index}]")
        task_id = _text(task.get("id"), f"tasks[{index}].id")
        if task_id in seen_ids:
            raise ThroughputError(f"duplicate task id {task_id!r}")
        seen_ids.add(task_id)
        ready = _boolean(task.get("ready"), f"tasks[{index}].ready")
        needs_mutation = _boolean(
            task.get("needs_mutation"), f"tasks[{index}].needs_mutation"
        )
        resources = _resources(task.get("resources", []), f"tasks[{index}].resources")
        tasks.append((task_id, ready, needs_mutation, resources))

    if active_runs > 0 and lock_scope == "GLOBAL":
        return _result(
            "WAIT_EXTERNAL",
            can_progress=False,
            next_action="wait_for_active_validation",
            reason="active validation holds a global mutation lock",
        )

    selected: list[str] = []
    selected_mutation_resources: set[str] = set()
    for task_id, ready, needs_mutation, resources in tasks:
        if not ready:
            continue
        resource_set = set(resources)

        if needs_mutation and active_runs > 0 and lock_scope == "SCOPED":
            if resource_set & locked_resources:
                continue

        if needs_mutation and resource_set & selected_mutation_resources:
            continue

        selected.append(task_id)
        if needs_mutation:
            selected_mutation_resources.update(resource_set)
        if len(selected) >= max_lanes:
            break

    if selected:
        status = "PARALLEL_ADVANCE" if len(selected) > 1 else "BURST_ADVANCE"
        reason = (
            "dependency-ready work exists outside active scoped locks"
            if active_runs > 0
            else "dependency-ready work can continue until the next external wait boundary"
        )
        return _result(
            status,
            can_progress=True,
            next_action="execute_selected_work_burst",
            reason=reason,
            selected_tasks=selected,
        )

    if active_runs > 0:
        return _result(
            "WAIT_EXTERNAL",
            can_progress=False,
            next_action="wait_for_active_validation",
            reason="no dependency-independent ready work exists outside the active lock",
        )

    return _result(
        "IDLE",
        can_progress=False,
        next_action="refresh_dependency_state",
        reason="no ready work is currently declared",
    )


def self_test() -> int:
    """Run minimal invariants for throughput planning."""
    base = {
        "schema_version": 1,
        "authority": {
            "desired_state": "ACTIVE",
            "durable_state": "ACTIVE",
            "synchronized": True,
        },
        "validation": {
            "required": True,
            "launch_expected": True,
            "exact_head_runs": 0,
            "active_runs": 0,
            "terminal_runs": 0,
            "lock_scope": "NONE",
            "locked_resources": [],
        },
        "max_lanes": 2,
        "tasks": [],
    }
    missing = evaluate(base)
    if missing["status"] != "MISSING_VALIDATION_ROUTE":
        raise ThroughputError("self-test missed absent validation route")
    scoped = dict(base)
    scoped["validation"] = {
        "required": True,
        "launch_expected": True,
        "exact_head_runs": 1,
        "active_runs": 1,
        "terminal_runs": 0,
        "lock_scope": "SCOPED",
        "locked_resources": ["branch:a"],
    }
    scoped["tasks"] = [
        {"id": "blocked", "ready": True, "needs_mutation": True, "resources": ["branch:a"]},
        {"id": "independent", "ready": True, "needs_mutation": True, "resources": ["branch:b"]},
    ]
    planned = evaluate(scoped)
    if planned["selected_tasks"] != ["independent"]:
        raise ThroughputError("self-test failed scoped-lock parallelism")
    return 0
