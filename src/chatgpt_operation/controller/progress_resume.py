"""Evidence-preserving, read-only resume planning for bounded work units.

This is an extension of ResearchState, not an independent cookie store.
It never dispatches work or commits a reconciled state to GitHub.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import asdict
from typing import Any, Mapping

from .research import ResearchState


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_UNITS = 4096
_MAX_DETAIL_BYTES = 200_000


class ProgressResumeError(ValueError):
    """The checkpoint or its proposed continuation is not trustworthy."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ProgressResumeError("progress detail is not canonical JSON") from exc


def detail_digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ProgressResumeError(field + " must be lowercase SHA-256")
    return value


def _name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ProgressResumeError(field + " must be a short nonempty string")
    return value


def validate_checkpoint(raw: Any) -> dict[str, Any]:
    """Validate all stored details, not only the compact completion index."""
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version", "work_id", "plan_sha256", "policy_sha256",
        "units", "receipts",
    }:
        raise ProgressResumeError("invalid progress checkpoint envelope")
    if raw["schema_version"] != 1:
        raise ProgressResumeError("unsupported progress checkpoint version")
    _name(raw["work_id"], "work_id")
    _sha(raw["plan_sha256"], "plan_sha256")
    _sha(raw["policy_sha256"], "policy_sha256")

    units = raw["units"]
    if not isinstance(units, list) or not 0 < len(units) <= _MAX_UNITS:
        raise ProgressResumeError("progress units must be a bounded nonempty list")
    names: set[str] = set()
    for index, unit in enumerate(units):
        if not isinstance(unit, dict) or set(unit) != {
            "id", "input_sha256", "requires", "gates",
        }:
            raise ProgressResumeError("invalid progress unit")
        name = _name(unit["id"], "unit.id")
        if name in names:
            raise ProgressResumeError("duplicate progress unit")
        names.add(name)
        _sha(unit["input_sha256"], "unit.input_sha256")
        required = unit["requires"]
        if (
            not isinstance(required, list)
            or any(type(dep) is not int or dep < 0 or dep >= index for dep in required)
            or len(required) != len(set(required))
        ):
            raise ProgressResumeError("unit dependency must reference earlier unique units")
        gates = unit["gates"]
        if (
            not isinstance(gates, list)
            or any(not isinstance(g, str) or not g.strip() for g in gates)
            or len(gates) != len(set(gates))
        ):
            raise ProgressResumeError("unit gates must be unique names")

    receipts = raw["receipts"]
    if not isinstance(receipts, dict) or len(receipts) > len(units):
        raise ProgressResumeError("invalid completed-unit receipts")
    for key, receipt in receipts.items():
        if (
            not isinstance(key, str)
            or not key.isascii()
            or not key.isdecimal()
            or str(int(key)) != key
            or int(key) >= len(units)
        ):
            raise ProgressResumeError("invalid completed-unit index")
        if not isinstance(receipt, dict) or set(receipt) != {
            "input_sha256", "outcome", "detail_sha256", "detail",
        }:
            raise ProgressResumeError("invalid completed-unit receipt")
        if receipt["outcome"] not in {"PASS", "NOOP"}:
            raise ProgressResumeError("only verified successful units may be completed")
        if _sha(receipt["input_sha256"], "receipt.input_sha256") != units[int(key)]["input_sha256"]:
            raise ProgressResumeError("completed-unit input differs from checkpoint plan")
        if len(_canonical(receipt["detail"])) > _MAX_DETAIL_BYTES:
            raise ProgressResumeError("inline progress detail exceeds limit")
        if _sha(receipt["detail_sha256"], "receipt.detail_sha256") != detail_digest(receipt["detail"]):
            raise ProgressResumeError("completed-unit detail digest mismatch")
        for dep in units[int(key)]["requires"]:
            if str(dep) not in receipts:
                raise ProgressResumeError("completed unit has missing dependency receipt")

    # Return a copy to make validation usable at trust boundaries.
    return copy.deepcopy(raw)


def create_checkpoint(
    *, work_id: str, plan_sha256: str, policy_sha256: str,
    units: list[dict[str, Any]],
) -> dict[str, Any]:
    return validate_checkpoint({
        "schema_version": 1,
        "work_id": work_id,
        "plan_sha256": plan_sha256,
        "policy_sha256": policy_sha256,
        "units": copy.deepcopy(units),
        "receipts": {},
    })


def attach_checkpoint(state: ResearchState, checkpoint: dict[str, Any]) -> ResearchState:
    verified = validate_checkpoint(checkpoint)
    if verified["work_id"] != state.research_id:
        raise ProgressResumeError("checkpoint belongs to a different research state")
    if state.progress_checkpoint is not None:
        raise ProgressResumeError("existing checkpoint cannot be overwritten")
    result = copy.deepcopy(state)
    result.progress_checkpoint = verified
    result.revision += 1
    return result


def record_verified_unit(
    state: ResearchState, *, unit_id: str, input_sha256: str,
    outcome: str, detail: Any, gate_states: Mapping[str, str],
) -> ResearchState:
    checkpoint = validate_checkpoint(state.progress_checkpoint)
    if checkpoint["work_id"] != state.research_id:
        raise ProgressResumeError("progress state identity changed")
    matches = [i for i, unit in enumerate(checkpoint["units"]) if unit["id"] == unit_id]
    if len(matches) != 1:
        raise ProgressResumeError("unknown progress unit")
    index = matches[0]
    unit = checkpoint["units"][index]
    if _sha(input_sha256, "input_sha256") != unit["input_sha256"]:
        raise ProgressResumeError("input identity changed before completion")
    if any(gate_states.get(gate) != "PASS" for gate in unit["gates"]):
        raise ProgressResumeError("required gate is not PASS")
    if any(str(dep) not in checkpoint["receipts"] for dep in unit["requires"]):
        raise ProgressResumeError("prerequisite unit is not complete")
    if outcome not in {"PASS", "NOOP"}:
        raise ProgressResumeError("unverified unit cannot be marked complete")
    if len(_canonical(detail)) > _MAX_DETAIL_BYTES:
        raise ProgressResumeError("inline progress detail exceeds limit")
    receipt = {
        "input_sha256": input_sha256,
        "outcome": outcome,
        "detail_sha256": detail_digest(detail),
        "detail": copy.deepcopy(detail),
    }
    key = str(index)
    if key in checkpoint["receipts"]:
        if checkpoint["receipts"][key] != receipt:
            raise ProgressResumeError("conflicting replay of a completed unit")
        return copy.deepcopy(state)  # idempotent replay: no new revision
    checkpoint["receipts"][key] = receipt
    validate_checkpoint(checkpoint)
    result = copy.deepcopy(state)
    result.progress_checkpoint = checkpoint
    result.revision += 1
    return result


def evaluate_resume(
    state: ResearchState, *, plan_sha256: str, policy_sha256: str,
    live_inputs: Mapping[str, str], gate_states: Mapping[str, str],
) -> dict[str, Any]:
    """Derive the next units; never trust a saved 'next_action' string."""
    checkpoint = validate_checkpoint(state.progress_checkpoint)
    if checkpoint["work_id"] != state.research_id:
        raise ProgressResumeError("progress state identity changed")
    if checkpoint["plan_sha256"] != _sha(plan_sha256, "plan_sha256"):
        return {"status": "PLAN_CHANGED", "ready": [], "completed": [], "stale": []}
    if checkpoint["policy_sha256"] != _sha(policy_sha256, "policy_sha256"):
        return {"status": "POLICY_CHANGED", "ready": [], "completed": [], "stale": []}

    units = checkpoint["units"]
    names = {u["id"] for u in units}
    if set(live_inputs) != names:
        raise ProgressResumeError("live input inventory is incomplete or expanded")
    stale = [
        i for i, u in enumerate(units)
        if _sha(live_inputs[u["id"]], "live input") != u["input_sha256"]
    ]
    if stale:
        return {
            "status": "REFRESH_REQUIRED", "ready": [],
            "completed": sorted(int(k) for k in checkpoint["receipts"]),
            "stale": stale,
        }

    complete = set(int(k) for k in checkpoint["receipts"])
    ready = []
    waiting_gates = []
    for index, unit in enumerate(units):
        if index in complete or not set(unit["requires"]).issubset(complete):
            continue
        if any(gate_states.get(gate) != "PASS" for gate in unit["gates"]):
            waiting_gates.append(index)
        else:
            ready.append(index)
    status = (
        "COMPLETE" if len(complete) == len(units)
        else "READY" if ready else "WAIT_GATES" if waiting_gates else "WAIT_DEPENDENCIES"
    )
    return {
        "status": status, "ready": ready,
        "completed": sorted(complete), "stale": [],
        "waiting_gates": waiting_gates,
    }


def refresh_unit_inputs(
    state: ResearchState, *, live_inputs: Mapping[str, str],
) -> ResearchState:
    """Invalidate only changed inputs and their transitive dependents."""
    checkpoint = validate_checkpoint(state.progress_checkpoint)
    units = checkpoint["units"]
    if set(live_inputs) != {u["id"] for u in units}:
        raise ProgressResumeError("live input inventory mismatch")
    changed = set()
    for index, unit in enumerate(units):
        fresh = _sha(live_inputs[unit["id"]], "live input")
        if fresh != unit["input_sha256"]:
            changed.add(index)
            unit["input_sha256"] = fresh
        if any(dep in changed for dep in unit["requires"]):
            changed.add(index)
    if not changed:
        return copy.deepcopy(state)
    for index in changed:
        checkpoint["receipts"].pop(str(index), None)
    validate_checkpoint(checkpoint)
    result = copy.deepcopy(state)
    result.progress_checkpoint = checkpoint
    result.revision += 1
    return result


def reconcile_progress_conflict(
    base: ResearchState, current: ResearchState, proposed: ResearchState,
) -> tuple[str, ResearchState | None]:
    """Create an *uncommitted* proposal after a stale revision. No GitHub writes.

    Safe only for disjoint append-only verified progress. The caller MUST
    serialize actual writes and re-read the authoritative state before storing.
    GitHub Issue comment PATCH does not provide atomic compare-and-swap.
    """
    states = (base, current, proposed)
    checkpoints = [validate_checkpoint(s.progress_checkpoint) for s in states]
    if any(c["work_id"] != s.research_id for c, s in zip(checkpoints, states)):
        return "BLOCK_IDENTITY", None
    base_cp, cur_cp, prop_cp = checkpoints
    identity = ("work_id", "plan_sha256", "policy_sha256", "units")
    if any(cur_cp[k] != base_cp[k] or prop_cp[k] != base_cp[k] for k in identity):
        return "BLOCK_SCOPE_CHANGED", None
    if any(s.research_id != base.research_id for s in states):
        return "BLOCK_IDENTITY", None
    # Do not merge action_queue, live execution, scientific stage or other
    # authoritative state under the guise of merging read-only units.
    def other_state(s: ResearchState) -> dict[str, Any]:
        x = asdict(s)
        x.pop("revision")
        x.pop("progress_checkpoint")
        return x
    if other_state(current) != other_state(base) or other_state(proposed) != other_state(base):
        return "BLOCK_OTHER_STATE_CHANGED", None
    if current.revision < base.revision or proposed.revision <= base.revision:
        return "BLOCK_REVISION", None
    originals = base_cp["receipts"]
    for cp in (cur_cp, prop_cp):
        if any(cp["receipts"].get(k) != v for k, v in originals.items()):
            return "BLOCK_REWRITTEN_RECEIPT", None
    additions = {
        k: v for k, v in prop_cp["receipts"].items() if k not in originals
    }
    if not additions:
        return "NOOP", None
    merged = copy.deepcopy(cur_cp)
    for key, receipt in additions.items():
        existing = merged["receipts"].get(key)
        if existing is not None and existing != receipt:
            return "BLOCK_CONFLICTING_RECEIPT", None
        merged["receipts"][key] = receipt
    validate_checkpoint(merged)
    if merged["receipts"] == cur_cp["receipts"]:
        return "ALREADY_APPLIED", None
    result = copy.deepcopy(current)
    result.progress_checkpoint = merged
    result.revision = current.revision + 1
    return "MERGE_DISJOINT_PROPOSAL", result
