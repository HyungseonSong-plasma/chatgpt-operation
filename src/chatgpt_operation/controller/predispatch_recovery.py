"""Durable pre-dispatch controller failure classification and bounded recovery."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .research import ResearchState, ResearchStateError


ACTIVE_STATUSES = frozenset({"retryable", "escalated", "blocked"})
TERMINAL_STATUSES = frozenset({"resolved", "escalated", "blocked"})


def _normalized_error(error: str) -> str:
    return " ".join(str(error).strip().split())


def classify_predispatch_failure(error: str) -> str:
    """Classify typed validation failures without inventing capability evidence."""
    text = _normalized_error(error).lower()
    authority_markers = (
        "repository mutation policy rejected actionplan",
        "policy denied",
        "not authorized",
        "forbidden authority",
    )
    if any(marker in text for marker in authority_markers):
        return "authority_policy"
    planning_markers = (
        "implement_gap is invalid because implementation_gaps is empty",
        "completion reconciliation for an open workload requires one executable actionplan",
        "progress.criterion must equal the controller-selected",
        "decision_id must be null or reference an existing locked decision",
        "propose_revision must reference an existing locked decision",
    )
    if any(marker in text for marker in planning_markers):
        return "planning_validation"
    return "reasoning_validation"


def _visible_branch_names(repository_context: dict[str, Any] | None) -> tuple[str, ...]:
    raw = (repository_context or {}).get("samuel_branches", [])
    if not isinstance(raw, list):
        return ()
    names: set[str] = set()
    for item in raw:
        if isinstance(item, str) and item.strip():
            names.add(item.strip())
        elif isinstance(item, dict):
            value = item.get("name") or item.get("ref") or item.get("branch")
            if isinstance(value, str) and value.strip():
                names.add(value.strip())
    return tuple(sorted(names))


def workload_branch_identity(
    work_id: str,
    repository_context: dict[str, Any] | None,
) -> str | None:
    """Return the visible branch that is structurally owned by one Issue workload."""
    token = work_id.replace(":", "-")
    candidates = [name for name in _visible_branch_names(repository_context) if token in name]
    return candidates[0] if candidates else None


def failure_fingerprint(
    *,
    work_id: str,
    target_acceptance_criterion: str | None,
    failure_class: str,
    error: str,
) -> str:
    semantic = {
        "work_id": work_id,
        "target_acceptance_criterion": target_acceptance_criterion,
        "failure_class": failure_class,
        "error": _normalized_error(error),
    }
    return hashlib.sha256(
        json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def unresolved_predispatch_failure(
    state: ResearchState,
    target_acceptance_criterion: str | None,
) -> dict[str, Any] | None:
    """Return the one active failure for the controller-owned target, if present."""
    matches = [
        item
        for item in state.predispatch_failures.values()
        if isinstance(item, dict)
        and item.get("status") in ACTIVE_STATUSES
        and item.get("target_acceptance_criterion") == target_acceptance_criterion
    ]
    if len(matches) > 1:
        raise ResearchStateError("multiple active pre-dispatch failures for one acceptance target")
    return matches[0] if matches else None


def record_predispatch_failure(
    state: ResearchState,
    *,
    work_id: str,
    target_acceptance_criterion: str | None,
    error: str,
    node_attempts: int | None,
    repository_context: dict[str, Any] | None,
    capability_exhaustion_proven: bool = False,
) -> dict[str, Any]:
    """Persist one failure; an identical unresolved recurrence escalates deterministically."""
    if state.research_id != work_id:
        raise ResearchStateError("pre-dispatch failure belongs to a different workload")
    failure_class = classify_predispatch_failure(error)
    normalized = _normalized_error(error)
    if not normalized:
        raise ResearchStateError("pre-dispatch failure requires an error message")
    if failure_class == "capability_exhaustion" and not capability_exhaustion_proven:
        raise ResearchStateError("capability exhaustion requires resolver-backed evidence")
    fingerprint = failure_fingerprint(
        work_id=work_id,
        target_acceptance_criterion=target_acceptance_criterion,
        failure_class=failure_class,
        error=normalized,
    )
    branch_identity = workload_branch_identity(work_id, repository_context)
    existing = state.predispatch_failures.get(fingerprint)
    if existing is not None:
        if not isinstance(existing, dict):
            raise ResearchStateError("invalid durable pre-dispatch failure record")
        if existing.get("status") == "retryable":
            existing["status"] = "escalated"
            existing["occurrences"] = int(existing.get("occurrences", 1)) + 1
            existing["last_error"] = normalized
            existing["node_attempts"] = node_attempts
            if branch_identity is not None:
                existing["branch_identity"] = branch_identity
            state.revision += 1
        return existing

    status = "blocked" if failure_class == "authority_policy" else "retryable"
    record = {
        "schema_version": 1,
        "fingerprint": fingerprint,
        "work_id": work_id,
        "target_acceptance_criterion": target_acceptance_criterion,
        "failure_class": failure_class,
        "status": status,
        "occurrences": 1,
        "last_error": normalized,
        "node_attempts": node_attempts,
        "branch_identity": branch_identity,
        "capability_exhaustion_proven": capability_exhaustion_proven,
    }
    state.predispatch_failures[fingerprint] = record
    state.revision += 1
    return record


def resolve_predispatch_failure(
    state: ResearchState,
    target_acceptance_criterion: str | None,
) -> tuple[str, ...]:
    """Mark retryable failures resolved after typed reasoning succeeds for the same target."""
    resolved: list[str] = []
    for fingerprint, item in state.predispatch_failures.items():
        if (
            isinstance(item, dict)
            and item.get("status") == "retryable"
            and item.get("target_acceptance_criterion") == target_acceptance_criterion
        ):
            item["status"] = "resolved"
            resolved.append(fingerprint)
    if resolved:
        state.revision += 1
    return tuple(sorted(resolved))


def has_unresolved_predispatch_failure(state: ResearchState) -> bool:
    return any(
        isinstance(item, dict) and item.get("status") in ACTIVE_STATUSES
        for item in state.predispatch_failures.values()
    )
