"""Draft-only Bootstrap-owned durable Child provisioning executor.

Not wired to a production runner. The caller must supply independently
authenticated, exclusive Bootstrap writer authority, exact work Parent and
global StateKernel admission. The external scheduler must never call this
module. A remote absence after an uncertain POST is not proof that a create
did not happen; never blindly replay that operation.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Protocol

from .agent_issue_provision import (
    ProvisionError, _snapshot, plan_next_child_provision, validate_provision,
)

INTENT_MARKER = "<!-- samuel-child-operation-intent-v1:"
STAGES = ("CREATE_CHILD", "FINALIZE_CHILD", "LINK_CHILD",
          "RECORD_PARENT_ASSIGNMENT")
_CODES = {
    "CREATE_CHILD": {201}, "FINALIZE_CHILD": {200},
    "LINK_CHILD": {200, 201}, "RECORD_PARENT_ASSIGNMENT": {201},
}


class DurableChildError(ProvisionError):
    pass


class BootstrapTransport(Protocol):
    def get(self, path: str, *, query: dict[str, str] | None = None) -> Any: ...
    def request(self, method: str, path: str, *,
                payload: dict[str, Any] | None = None) -> tuple[int, Any]: ...


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _intent(spec: dict[str, Any], stage: str) -> dict[str, Any]:
    if stage not in STAGES:
        raise DurableChildError("unsupported Child operation")
    return {
        "schema_version": 1,
        "repository": spec["repository"], "parent_issue": spec["parent_issue"],
        "work_id": spec["work_id"], "agent_id": spec["agent_id"],
        "provision_id": spec["provision_id"],
        "source_head_sha": spec["source_head_sha"], "stage": stage,
    }


def _body(record: dict[str, Any]) -> str:
    text = _json(record)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return INTENT_MARKER + digest + " -->\n```json\n" + text + "\n```"


def _parse(body: str) -> dict[str, Any]:
    match = re.fullmatch(
        re.escape(INTENT_MARKER) + r"([0-9a-f]{64}) -->\n```json\n(.*?)\n```",
        body, flags=re.DOTALL,
    )
    if match is None:
        raise DurableChildError("malformed durable Child intent")
    try:
        record = json.loads(match.group(2))
    except json.JSONDecodeError as exc:
        raise DurableChildError("invalid durable Child intent JSON") from exc
    if (
        not isinstance(record, dict)
        or set(record) != {
            "schema_version", "repository", "parent_issue", "work_id",
            "agent_id", "provision_id", "source_head_sha", "stage",
        }
        or record.get("schema_version") != 1
        or record.get("stage") not in STAGES
        or match.group(2) != _json(record)
        or match.group(1) !=
            hashlib.sha256(match.group(2).encode("utf-8")).hexdigest()
    ):
        raise DurableChildError("untrusted durable Child intent")
    return record


def _read_intents(port: BootstrapTransport, *, parent: int,
                  trusted_author: str) -> list[dict[str, Any]]:
    comments = _snapshot(port, f"/issues/{parent}/comments", limit=500)
    result: list[dict[str, Any]] = []
    for comment in comments:
        body = comment.get("body")
        if not isinstance(body, str) or INTENT_MARKER not in body:
            continue
        author = comment.get("user")
        if (
            not isinstance(author, dict)
            or author.get("login") != trusted_author
            or not isinstance(comment.get("created_at"), str)
            or comment.get("created_at") != comment.get("updated_at")
        ):
            raise DurableChildError("untrusted or edited Child intent")
        result.append(_parse(body))
    return result


def _intents_for(records: list[dict[str, Any]],
                 spec: dict[str, Any]) -> set[str]:
    seen: set[str] = set()
    for row in records:
        if (
            row["repository"] != spec["repository"]
            or row["parent_issue"] != spec["parent_issue"]
        ):
            raise DurableChildError("foreign operation intent in task parent")
        if row["agent_id"] != spec["agent_id"]:
            continue
        if any(row[key] != spec[key] for key in
               ("provision_id", "work_id", "source_head_sha")):
            raise DurableChildError("conflicting Child intent for same agent")
        if row["stage"] in seen:
            raise DurableChildError("duplicate Child operation intent")
        seen.add(row["stage"])
    return seen


def _result(status: str, stage: str, next_stage: str | None = None) -> dict:
    return {
        "status": status, "stage": stage, "next_stage": next_stage,
        "global_state_write": False, "admission_write": False,
        "merge_authorized": False,
    }


def advance_durable_child(port: BootstrapTransport, spec: dict[str, Any], *,
                          parent_issue: Mapping[str, Any],
                          trusted_author: str = "github-actions[bot]") -> dict:
    """Stage only, not a callable production workflow.

    Caller MUST enforce its own authenticated, exclusive Bootstrap lease
    before entering. This function has no ability to grant that authority.
    Each call executes at most one Child operation, after an independently
    observed immutable intent. Unknown ACKs fail closed.
    """
    s = validate_provision(spec)
    if not trusted_author:
        raise DurableChildError("missing trusted comment author")
    step = plan_next_child_provision(
        port, s, parent_issue=parent_issue, trusted_author=trusted_author,
    )
    stages = _intents_for(
        _read_intents(port, parent=s["parent_issue"],
                      trusted_author=trusted_author), s,
    )
    phase = step["status"]
    if phase == "READY":
        if stages != set(STAGES):
            raise DurableChildError("ready without complete intent history")
        return _result("READY", phase)
    if phase not in STAGES:
        raise DurableChildError("unknown Child stage")
    idx = STAGES.index(phase)
    if not set(STAGES[:idx]).issubset(stages):
        raise DurableChildError("missing predecessor operation intent")
    if any(suffix in stages for suffix in STAGES[idx+1:]):
        raise DurableChildError("future stage intent conflicts with GitHub readback")
    if phase in stages:
        return _result("BLOCKED_UNCERTAIN_ACK", phase)

    # BEFORE attempting any target Child operation, persist and verify an
    # immutable intent under the work Parent, not under global state Issue #44.
    parent_comment_path = f"/issues/{s['parent_issue']}/comments"
    try:
        code, _ = port.request(
            "POST", parent_comment_path,
            payload={"body": _body(_intent(s, phase))},
        )
    except (RuntimeError, OSError, ValueError):
        return _result("BLOCKED_UNCERTAIN_INTENT", phase)
    if code != 201:
        return _result("BLOCKED_UNCERTAIN_INTENT", phase)
    reread = _intents_for(
        _read_intents(port, parent=s["parent_issue"],
                      trusted_author=trusted_author), s,
    )
    if reread != stages | {phase}:
        return _result("BLOCKED_UNCONFIRMED_INTENT", phase)
    if plan_next_child_provision(
        port, s, parent_issue=parent_issue, trusted_author=trusted_author,
    ) != step:
        return _result("BLOCKED_CONCURRENT_CHANGE", phase)

    if (
        step.get("method") not in {"POST", "PATCH"}
        or not isinstance(step.get("path"), str)
        or not isinstance(step.get("payload"), dict)
    ):
        raise DurableChildError("invalid typed next Child operation")
    try:
        code, _ = port.request(
            step["method"], step["path"], payload=step["payload"],
        )
    except (RuntimeError, OSError, ValueError):
        return _result("BLOCKED_UNCERTAIN_ACK", phase)
    if code not in _CODES[phase]:
        return _result("BLOCKED_UNCERTAIN_ACK", phase)

    # ACK alone never suffices. Stable inventory must show the next stage.
    after = plan_next_child_provision(
        port, s, parent_issue=parent_issue, trusted_author=trusted_author,
    )
    if after["status"] == phase:
        return _result("BLOCKED_UNCONFIRMED_POSTCONDITION", phase)
    next_expected = STAGES[idx+1] if idx+1 < len(STAGES) else "READY"
    if after["status"] != next_expected:
        raise DurableChildError("unexpected Child stage transition")
    return _result("OBSERVED_ADVANCE", phase, next_expected)
