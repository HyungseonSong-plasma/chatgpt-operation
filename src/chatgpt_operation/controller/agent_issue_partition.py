"""Agent-owned Child Issue partitions: immutable receipts, read-only parent reduce.

The parent Issue #44 owns allocation and final decisions. Agents append ONLY
to their allocated Child Issues. No child edits the parent's ResearchState.
These objects are proposals/observations; none of their bytes alone grant
execution, merge, or state-write authority.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, Callable, Mapping, Sequence

from .progress_resume import (
    ProgressResumeError, create_checkpoint, detail_digest,
    record_verified_unit, validate_checkpoint,
)
from .research import ResearchState

ASSIGNMENT_MARKER = "<!-- samuel-agent-child-assignment-v1:"
RECEIPT_MARKER = "<!-- samuel-agent-progress-receipt-v1:"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_NAME = re.compile(r"^[a-zA-Z0-9_.:/-]{1,128}$")
_MAX_DETAIL_BYTES = 180_000
_MAX_CHILD_COMMENTS = 500
_MAX_AGENTS = 50


class AgentIssueError(ValueError):
    """Invalid ownership, missing provenance, or contradictory agent proof."""


def _json(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        if json.loads(encoded.decode("utf-8")) != value:
            raise AgentIssueError("lossy JSON round-trip")
        return encoded
    except (TypeError, ValueError, UnicodeError) as exc:
        raise AgentIssueError("invalid canonical JSON") from exc


def _sha(value: Any, name: str, pattern: re.Pattern[str] = _SHA256) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise AgentIssueError(name + " must be a pinned lowercase hash")
    return value


def _name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise AgentIssueError("invalid " + field)
    return value


def _positive(value: Any, field: str) -> int:
    if type(value) is not int or value < 1:
        raise AgentIssueError(field + " must be a positive integer")
    return value


def _identify(payload: dict[str, Any], field: str) -> str:
    return hashlib.sha256(_json({k: v for k, v in payload.items() if k != field})).hexdigest()


def validate_assignment(raw: Any) -> dict[str, Any]:
    required = {
        "schema_version", "assignment_id", "repository", "parent_issue",
        "child_issue", "agent_id", "work_id", "plan_sha256", "policy_sha256",
        "source_head_sha", "units",
    }
    if not isinstance(raw, dict) or set(raw) != required or raw["schema_version"] != 1:
        raise AgentIssueError("invalid child assignment schema")
    _name(raw["agent_id"], "agent_id")
    _name(raw["work_id"], "work_id")
    repo = raw["repository"]
    if (
        not isinstance(repo, str) or not re.fullmatch(
            r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo
        )
    ):
        raise AgentIssueError("invalid repository")
    parent = _positive(raw["parent_issue"], "parent_issue")
    child = _positive(raw["child_issue"], "child_issue")
    if parent == child:
        raise AgentIssueError("parent and child must be distinct Issues")
    for name in ("plan_sha256", "policy_sha256"):
        _sha(raw[name], name)
    _sha(raw["source_head_sha"], "source_head_sha", _SHA40)
    validate_checkpoint(create_checkpoint(
        work_id=raw["work_id"],
        plan_sha256=raw["plan_sha256"],
        policy_sha256=raw["policy_sha256"],
        units=raw["units"],
    ))
    if _sha(raw["assignment_id"], "assignment_id") != _identify(raw, "assignment_id"):
        raise AgentIssueError("immutable assignment digest mismatch")
    return copy.deepcopy(raw)


def make_assignment(
    *, repository: str, parent_issue: int, child_issue: int, agent_id: str,
    work_id: str, plan_sha256: str, policy_sha256: str,
    source_head_sha: str, units: list[dict[str, Any]],
) -> dict[str, Any]:
    raw = {
        "schema_version": 1, "repository": repository,
        "parent_issue": parent_issue, "child_issue": child_issue,
        "agent_id": agent_id, "work_id": work_id,
        "plan_sha256": plan_sha256, "policy_sha256": policy_sha256,
        "source_head_sha": source_head_sha, "units": copy.deepcopy(units),
    }
    raw["assignment_id"] = _identify(raw, "assignment_id")
    return validate_assignment(raw)


def validate_parent_registry(assignments: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parent-owned assignments, independently obtained from trusted authority."""
    if not isinstance(assignments, (tuple, list)) or len(assignments) > _MAX_AGENTS:
        raise AgentIssueError("bounded authoritative parent registry required")
    checked = [validate_assignment(item) for item in assignments]
    if len({x["assignment_id"] for x in checked}) != len(checked):
        raise AgentIssueError("duplicate parent assignment")
    if len({x["child_issue"] for x in checked}) != len(checked):
        raise AgentIssueError("two agents own the same Child Issue")
    scope = {(x["repository"], x["parent_issue"], x["work_id"]) for x in checked}
    if len(scope) > 1:
        raise AgentIssueError("multiple parent work scopes cannot share a registry")
    if len({x["agent_id"] for x in checked}) != len(checked):
        raise AgentIssueError("duplicate active agent identity")
    return checked


def _envelope(marker: str, identity: str, body: dict[str, Any]) -> str:
    return marker + identity + " -->\n```json\n" + _json(body).decode("utf-8") + "\n```"


def _decode(body: Any, marker: str) -> dict[str, Any]:
    if not isinstance(body, str):
        raise AgentIssueError("comment/body must be text")
    expression = r"\A" + re.escape(marker) + r"([0-9a-f]{64}) -->\n```json\n(.*?)\n```\Z"
    match = re.fullmatch(expression, body, re.DOTALL)
    if match is None:
        raise AgentIssueError("invalid immutable Issue marker or JSON fence")
    try:
        raw = json.loads(match.group(2))
    except json.JSONDecodeError as exc:
        raise AgentIssueError("invalid Issue payload JSON") from exc
    if not isinstance(raw, dict):
        raise AgentIssueError("Issue payload must be an object")
    expected = "assignment_id" if marker == ASSIGNMENT_MARKER else "receipt_id"
    if raw.get(expected) != match.group(1):
        raise AgentIssueError("Issue marker digest mismatch")
    if _json(raw).decode("utf-8") != match.group(2):
        raise AgentIssueError("non-canonical Issue envelope")
    return raw


def child_issue_body(assignment: dict[str, Any]) -> str:
    raw = validate_assignment(assignment)
    return _envelope(ASSIGNMENT_MARKER, raw["assignment_id"], raw)


def validate_child_ownership(
    issue: Mapping[str, Any],
    assignment: dict[str, Any],
    *,
    parent_registry: Sequence[dict[str, Any]],
) -> None:
    """Child body is untrusted; parent registry is the allocation authority."""
    expected = validate_assignment(assignment)
    registered = validate_parent_registry(parent_registry)
    if expected not in registered:
        raise AgentIssueError("Child allocation absent from authoritative parent registry")
    if (
        not isinstance(issue, Mapping)
        or type(issue.get("number")) is not int
        or issue["number"] != expected["child_issue"]
        or issue.get("pull_request") is not None
        or issue.get("state") != "open"
        or issue.get("url") != "https://api.github.com/repos/" + expected["repository"]
            + "/issues/" + str(expected["child_issue"])
    ):
        raise AgentIssueError("live Child Issue identity mismatch")
    observed = validate_assignment(_decode(issue.get("body"), ASSIGNMENT_MARKER))
    if observed != expected:
        raise AgentIssueError("Child body differs from parent-approved assignment")
    labels = issue.get("labels", [])
    if not isinstance(labels, list) or any(
        x == "samuel" or isinstance(x, dict) and x.get("name") == "samuel"
        for x in labels
    ):
        raise AgentIssueError("Child Issue must not enter parent Samuel admission queue")


_RECEIPT_FIELDS = {
    "schema_version", "receipt_id", "assignment_id", "parent_issue",
    "child_issue", "agent_id", "work_id", "unit_id", "input_sha256",
    "outcome", "detail", "detail_sha256", "source_run_id",
    "source_head_sha",
}


def validate_receipt(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != _RECEIPT_FIELDS:
        raise AgentIssueError("invalid immutable receipt schema")
    if raw["schema_version"] != 1:
        raise AgentIssueError("unsupported child receipt version")
    for field in ("assignment_id", "input_sha256", "detail_sha256"):
        _sha(raw[field], field)
    _sha(raw["source_head_sha"], "source_head_sha", _SHA40)
    for field in ("parent_issue", "child_issue", "source_run_id"):
        _positive(raw[field], field)
    for field in ("agent_id", "work_id", "unit_id"):
        _name(raw[field], field)
    if raw["outcome"] not in ("PASS", "NOOP", "FAIL"):
        raise AgentIssueError("invalid agent outcome")
    if len(_json(raw["detail"])) > _MAX_DETAIL_BYTES:
        raise AgentIssueError("lossless evidence exceeds bounded receipt")
    if detail_digest(raw["detail"]) != raw["detail_sha256"]:
        raise AgentIssueError("agent detail hash mismatch")
    if _sha(raw["receipt_id"], "receipt_id") != _identify(raw, "receipt_id"):
        raise AgentIssueError("immutable receipt ID mismatch")
    return copy.deepcopy(raw)


def make_receipt(
    assignment: dict[str, Any], *, unit_id: str, input_sha256: str,
    outcome: str, detail: Any, source_run_id: int,
) -> dict[str, Any]:
    a = validate_assignment(assignment)
    raw = {
        "schema_version": 1, "assignment_id": a["assignment_id"],
        "parent_issue": a["parent_issue"], "child_issue": a["child_issue"],
        "agent_id": a["agent_id"], "work_id": a["work_id"],
        "unit_id": unit_id, "input_sha256": input_sha256,
        "outcome": outcome, "detail": copy.deepcopy(detail),
        "detail_sha256": detail_digest(detail),
        "source_run_id": source_run_id, "source_head_sha": a["source_head_sha"],
    }
    raw["receipt_id"] = _identify(raw, "receipt_id")
    return validate_receipt(raw)


def receipt_comment_body(receipt: dict[str, Any]) -> str:
    r = validate_receipt(receipt)
    return _envelope(RECEIPT_MARKER, r["receipt_id"], r)


def _check_attestation(
    receipt: dict[str, Any],
    *,
    verify_source: Callable[[dict[str, Any]], Mapping[str, Any]],
) -> None:
    if not callable(verify_source):
        raise AgentIssueError("independent source verifier required")
    verified = verify_source(copy.deepcopy(receipt))
    if not isinstance(verified, Mapping):
        raise AgentIssueError("missing independently verified source evidence")
    # The response MUST be constructed from independent GitHub run/artifact
    # reads, never copied from the submitted comment by the production caller.
    expected = {
        "receipt_id": receipt["receipt_id"],
        "source_run_id": receipt["source_run_id"],
        "source_head_sha": receipt["source_head_sha"],
        "detail_sha256": receipt["detail_sha256"],
        "outcome": receipt["outcome"],
        "verified": True,
    }
    if any(verified.get(k) != v for k, v in expected.items()):
        raise AgentIssueError("external run and evidence attestation mismatch")


def reduce_child_progress(
    issue: Mapping[str, Any], comments: Sequence[dict[str, Any]],
    assignment: dict[str, Any], *,
    parent_registry: Sequence[dict[str, Any]],
    trusted_comment_authors: frozenset[str],
    live_gate_states: Mapping[str, str],
    verify_source: Callable[[dict[str, Any]], Mapping[str, Any]],
) -> dict[str, Any]:
    """Reduce append-only Child Issue receipts; NEVER write the parent Issue.

    Caller must independently enumerate ALL comment pages from GitHub.
    One agent owns one Issue. Replayed identical comments are logical NOOPs;
    conflicting results for one unit always BLOCK and preserve raw evidence.
    """
    validate_child_ownership(issue, assignment, parent_registry=parent_registry)
    a = validate_assignment(assignment)
    if not trusted_comment_authors:
        raise AgentIssueError("trusted authors required")
    if not isinstance(comments, (list, tuple)) or len(comments) > _MAX_CHILD_COMMENTS:
        raise AgentIssueError("complete bounded Child comment inventory required")
    if not isinstance(live_gate_states, Mapping):
        raise AgentIssueError("independent gate states required")
    receipts: dict[str, tuple[dict[str, Any], int]] = {}
    by_unit: dict[str, str] = {}
    for comment in comments:
        if not isinstance(comment, dict) or type(comment.get("id")) is not int:
            raise AgentIssueError("malformed Child comment")
        body = comment.get("body")
        if not isinstance(body, str) or RECEIPT_MARKER not in body:
            continue
        user = comment.get("user")
        if not isinstance(user, dict) or user.get("login") not in trusted_comment_authors:
            raise AgentIssueError("unauthorized Child receipt author")
        receipt = validate_receipt(_decode(body, RECEIPT_MARKER))
        if any(receipt[k] != a[k] for k in (
            "assignment_id", "parent_issue", "child_issue", "agent_id",
            "work_id", "source_head_sha",
        )):
            raise AgentIssueError("receipt crosses agent/Issue ownership boundary")
        unit = next((u for u in a["units"] if u["id"] == receipt["unit_id"]), None)
        if unit is None or unit["input_sha256"] != receipt["input_sha256"]:
            raise AgentIssueError("receipt input unit is not parent-approved")
        existing_id = by_unit.get(receipt["unit_id"])
        if existing_id is not None and existing_id != receipt["receipt_id"]:
            raise AgentIssueError("contradictory receipts for a single unit")
        by_unit[receipt["unit_id"]] = receipt["receipt_id"]
        existing = receipts.get(receipt["receipt_id"])
        if existing is None:
            receipts[receipt["receipt_id"]] = (receipt, comment["id"])
        elif existing[0] != receipt:
            raise AgentIssueError("conflicting immutable receipt replay")
    state = ResearchState(a["work_id"], "Child Issue read-only reducer")
    state.progress_checkpoint = create_checkpoint(
        work_id=a["work_id"], plan_sha256=a["plan_sha256"],
        policy_sha256=a["policy_sha256"], units=a["units"],
    )
    failures: list[dict[str, Any]] = []
    verified_refs: list[dict[str, Any]] = []
    for index, unit in enumerate(a["units"]):
        identifier = by_unit.get(unit["id"])
        if identifier is None:
            continue
        receipt, comment_id = receipts[identifier]
        _check_attestation(receipt, verify_source=verify_source)
        ref = {
            "unit_id": unit["id"], "receipt_id": identifier,
            "child_issue": a["child_issue"], "comment_id": comment_id,
            "detail_sha256": receipt["detail_sha256"],
            "outcome": receipt["outcome"],
        }
        verified_refs.append(ref)
        if receipt["outcome"] == "FAIL":
            failures.append(ref)
            continue
        try:
            state = record_verified_unit(
                state, unit_id=unit["id"], input_sha256=unit["input_sha256"],
                outcome=receipt["outcome"], detail=receipt["detail"],
                gate_states=live_gate_states,
            )
        except ProgressResumeError as exc:
            raise AgentIssueError("Child unit dependencies/gates not satisfied") from exc
    cp = validate_checkpoint(state.progress_checkpoint)
    return {
        "schema_version": 1, "status": (
            "BLOCKED" if failures
            else "COMPLETE" if len(cp["receipts"]) == len(a["units"])
            else "IN_PROGRESS"
        ),
        "agent_id": a["agent_id"],
        "child_issue": a["child_issue"],
        "assignment_id": a["assignment_id"],
        "completed_units": len(cp["receipts"]),
        "total_units": len(a["units"]),
        "failed_receipts": failures,
        "verified_refs": verified_refs,
        "parent_mutation": None,
        "merge_authorized": False,
    }


def reduce_parent_children(
    children: Sequence[dict[str, Any]],
    *,
    registry: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Review-only aggregation: return references, never a parent write."""
    assignments = validate_parent_registry(registry)
    if len(children) != len(assignments):
        raise AgentIssueError("incomplete set of Child agent outcomes")
    by_issue: dict[int, dict[str, Any]] = {}
    for child in children:
        if not isinstance(child, dict) or type(child.get("child_issue")) is not int:
            raise AgentIssueError("invalid Child summary")
        number = child["child_issue"]
        if number in by_issue:
            raise AgentIssueError("duplicate Child summary")
        by_issue[number] = child
    for assignment in assignments:
        item = by_issue.get(assignment["child_issue"])
        if (
            item is None or item.get("assignment_id") != assignment["assignment_id"]
            or item.get("agent_id") != assignment["agent_id"]
            or item.get("status") not in {"COMPLETE", "BLOCKED", "IN_PROGRESS"}
            or item.get("parent_mutation", "invalid") is not None
            or item.get("merge_authorized") is not False
        ):
            raise AgentIssueError("untrusted or missing Child summary")
    completed = all(x["status"] == "COMPLETE" for x in by_issue.values())
    blocked = any(x["status"] == "BLOCKED" for x in by_issue.values())
    return {
        "status": "BLOCKED" if blocked else "READY_FOR_PARENT_REVIEW" if completed
                  else "WAIT_CHILDREN",
        "children": sorted(by_issue.values(), key=lambda x: x["child_issue"]),
        "parent_mutation": None,
        "merge_authorized": False,
    }
