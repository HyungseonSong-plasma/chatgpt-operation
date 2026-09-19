"""Deterministic lifecycle guard for scheduled work controllers.

The evaluator is intentionally repository-agnostic. Callers collect current
repository evidence and pass a closed snapshot. The evaluator never queries a
remote system and never disables a scheduler itself.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


class LifecycleError(ValueError):
    """Raised when lifecycle evidence is malformed or not independently sourced."""


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LifecycleError(f"{name} must be an object")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LifecycleError(f"{name} must be a non-empty string")
    return value


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise LifecycleError(f"{name} must be a boolean")
    return value


def _count(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LifecycleError(f"{name} must be a non-negative integer")
    return value


def _scan(snapshot: Mapping[str, Any], name: str) -> tuple[bool, int, str, str]:
    scan = _mapping(snapshot.get(name), name)
    complete = _boolean(scan.get("complete"), f"{name}.complete")
    open_count = _count(scan.get("open_count"), f"{name}.open_count")
    method = _text(scan.get("method"), f"{name}.method")
    evidence_id = _text(scan.get("evidence_id"), f"{name}.evidence_id")
    return complete, open_count, method, evidence_id


def _candidate_token(controller_id: str) -> str:
    witness = {
        "schema_version": 1,
        "controller_id": controller_id,
        "terminal_predicate": {
            "primary_open_count": 0,
            "confirmation_open_count": 0,
            "active_work_open_count": 0,
            "sentinel_terminal": True,
        },
    }
    payload = json.dumps(witness, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _result(
    status: str,
    *,
    can_disable: bool,
    reason: str,
    next_action: str,
    candidate: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "can_disable": can_disable,
        "reason": reason,
        "next_action": next_action,
        "candidate": candidate,
    }


def evaluate(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate whether a scheduled controller may disable itself.

    Completion is deliberately two-phase. A first fully terminal observation
    returns TERMINAL_CANDIDATE. Only a later independent controller cycle that
    presents the matching candidate token may return VERIFIED_COMPLETE.
    """

    data = _mapping(snapshot, "snapshot")
    if data.get("schema_version") != 1:
        raise LifecycleError("schema_version must be 1")

    controller_id = _text(data.get("controller_id"), "controller_id")
    observation_id = _text(data.get("observation_id"), "observation_id")
    explicit_pause = _boolean(data.get("explicit_pause", False), "explicit_pause")

    if explicit_pause:
        return _result(
            "PAUSED",
            can_disable=True,
            reason="explicit pause authority is distinct from completion",
            next_action="disable_controller_for_pause",
        )

    primary = _scan(data, "primary_work_scan")
    confirmation = _scan(data, "confirmation_work_scan")
    active = _scan(data, "active_work_scan")
    sentinel = _mapping(data.get("sentinel"), "sentinel")
    sentinel_complete = _boolean(sentinel.get("complete"), "sentinel.complete")
    sentinel_terminal = _boolean(sentinel.get("terminal"), "sentinel.terminal")
    _text(sentinel.get("method"), "sentinel.method")
    _text(sentinel.get("evidence_id"), "sentinel.evidence_id")

    if primary[2] == confirmation[2]:
        raise LifecycleError(
            "primary_work_scan.method and confirmation_work_scan.method must differ"
        )
    if primary[3] == confirmation[3]:
        raise LifecycleError(
            "primary_work_scan.evidence_id and confirmation_work_scan.evidence_id must differ"
        )

    if not (primary[0] and confirmation[0] and active[0] and sentinel_complete):
        return _result(
            "WAIT",
            can_disable=False,
            reason="terminal evidence enumeration is incomplete",
            next_action="retry_without_disable",
        )

    if primary[1] != confirmation[1]:
        return _result(
            "WAIT",
            can_disable=False,
            reason="independent open-work scans disagree",
            next_action="retry_without_disable",
        )

    if primary[1] > 0:
        return _result(
            "ACTIVE",
            can_disable=False,
            reason="open governed work remains",
            next_action="continue_controller",
        )

    if active[1] > 0:
        return _result(
            "ACTIVE",
            can_disable=False,
            reason="active governed work remains",
            next_action="continue_controller",
        )

    if not sentinel_terminal:
        return _result(
            "ACTIVE",
            can_disable=False,
            reason="terminal sentinel is not terminal",
            next_action="continue_controller",
        )

    token = _candidate_token(controller_id)
    candidate = {"token": token, "observation_id": observation_id}
    previous_raw = data.get("previous_candidate")
    if previous_raw is None:
        return _result(
            "TERMINAL_CANDIDATE",
            can_disable=False,
            reason="first complete terminal observation requires a later independent cycle",
            next_action="persist_candidate_and_recheck",
            candidate=candidate,
        )

    previous = _mapping(previous_raw, "previous_candidate")
    previous_token = _text(previous.get("token"), "previous_candidate.token")
    previous_observation = _text(
        previous.get("observation_id"), "previous_candidate.observation_id"
    )

    if previous_token != token:
        return _result(
            "TERMINAL_CANDIDATE",
            can_disable=False,
            reason="previous terminal candidate does not match current terminal predicate",
            next_action="persist_candidate_and_recheck",
            candidate=candidate,
        )

    if previous_observation == observation_id:
        return _result(
            "TERMINAL_CANDIDATE",
            can_disable=False,
            reason="completion confirmation must come from a later controller cycle",
            next_action="persist_candidate_and_recheck",
            candidate=candidate,
        )

    return _result(
        "VERIFIED_COMPLETE",
        can_disable=True,
        reason="terminal predicate confirmed by a later independent controller cycle",
        next_action="disable_controller_complete",
        candidate=candidate,
    )


def self_test() -> int:
    """Run a minimal deterministic lifecycle sanity check."""
    base = {
        "schema_version": 1,
        "controller_id": "self-test",
        "observation_id": "cycle-1",
        "explicit_pause": False,
        "primary_work_scan": {
            "complete": True, "open_count": 0,
            "method": "primary", "evidence_id": "p1",
        },
        "confirmation_work_scan": {
            "complete": True, "open_count": 0,
            "method": "confirmation", "evidence_id": "c1",
        },
        "active_work_scan": {
            "complete": True, "open_count": 0,
            "method": "active", "evidence_id": "a1",
        },
        "sentinel": {
            "complete": True, "terminal": True,
            "method": "sentinel", "evidence_id": "s1",
        },
        "previous_candidate": None,
    }
    first = evaluate(base)
    if first["status"] != "TERMINAL_CANDIDATE" or first["can_disable"]:
        raise LifecycleError("self-test first-cycle candidate invariant failed")
    second = dict(base)
    second["observation_id"] = "cycle-2"
    second["previous_candidate"] = first["candidate"]
    verified = evaluate(second)
    if verified["status"] != "VERIFIED_COMPLETE" or not verified["can_disable"]:
        raise LifecycleError("self-test second-cycle completion invariant failed")
    return 0
