"""Append-only Child Issue transport plans with loss-of-ACK-safe readback.

No PATCH of any Issue comment. Caller supplies a complete stable GitHub
comment inventory and a trusted parent-approved assignment. A worker identity
is an application constraint, not an Issue-scoped GitHub credential.
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence

from .agent_issue_partition import (
    AgentIssueError, RECEIPT_MARKER, _decode, receipt_comment_body,
    validate_assignment, validate_child_ownership,
    validate_receipt,
)


class ChildWriteTransport(Protocol):
    def get(self, path: str, *, query: dict[str, str] | None = None) -> Any: ...
    def request(
        self, method: str, path: str, *,
        payload: dict[str, Any] | None = None,
    ) -> tuple[int, Any]: ...


def plan_child_append(
    issue: Mapping[str, Any],
    comments: Sequence[dict[str, Any]],
    assignment: dict[str, Any],
    receipt: dict[str, Any],
    *,
    parent_registry: Sequence[dict[str, Any]],
    trusted_authors: frozenset[str],
) -> dict[str, Any]:
    """Compute one safe child-only append; no state mutation."""
    validate_child_ownership(issue, assignment, parent_registry=parent_registry)
    a = validate_assignment(assignment)
    r = validate_receipt(receipt)
    if not trusted_authors:
        raise AgentIssueError("trusted authors required for Child append")
    if len(comments) > 500:
        raise AgentIssueError("Child inventory exceeds readback bound")
    if any(r[k] != a[k] for k in (
        "assignment_id", "parent_issue", "child_issue", "agent_id",
        "work_id", "source_head_sha",
    )):
        raise AgentIssueError("cannot append another Agent's receipt")
    unit = next((u for u in a["units"] if u["id"] == r["unit_id"]), None)
    if unit is None or unit["input_sha256"] != r["input_sha256"]:
        raise AgentIssueError("unapproved child unit or source input")
    observed = []
    for comment in comments:
        if not isinstance(comment, dict):
            raise AgentIssueError("invalid Child comment")
        body = comment.get("body")
        if not isinstance(body, str) or RECEIPT_MARKER not in body:
            continue
        user = comment.get("user")
        if not isinstance(user, dict) or user.get("login") not in trusted_authors:
            raise AgentIssueError("untrusted prior Child receipt author")
        previous = validate_receipt(_decode(body, RECEIPT_MARKER))
        if previous["assignment_id"] != a["assignment_id"]:
            raise AgentIssueError("foreign Child receipt in agent partition")
        observed.append(previous)
    if any(x["unit_id"] == r["unit_id"] and x["receipt_id"] != r["receipt_id"]
           for x in observed):
        raise AgentIssueError("conflicting evidence for same Child unit")
    if any(x["receipt_id"] == r["receipt_id"] for x in observed):
        return {
            "status": "ALREADY_PRESENT", "receipt_id": r["receipt_id"],
            "method": None, "path": None, "body": None,
        }
    return {
        "status": "APPEND_PROPOSAL", "receipt_id": r["receipt_id"],
        "method": "POST",
        "path": "/issues/" + str(a["child_issue"]) + "/comments",
        "body": receipt_comment_body(r),
    }


def reconcile_child_append_ack(
    comments_after: Sequence[dict[str, Any]],
    *,
    receipt: dict[str, Any], trusted_authors: frozenset[str],
) -> dict[str, Any]:
    """After POST or lost ACK: re-read until exact receipt is visible.

    Replaying a physically duplicate POST is unnecessary; all matching
    comments are logically one receipt, but distinct evidence BLOCKS.
    """
    r = validate_receipt(receipt)
    matches = []
    for c in comments_after:
        if not isinstance(c, dict) or type(c.get("id")) is not int:
            raise AgentIssueError("invalid child comment readback")
        body = c.get("body")
        if not isinstance(body, str) or RECEIPT_MARKER not in body:
            continue
        author = c.get("user")
        if not isinstance(author, dict) or author.get("login") not in trusted_authors:
            raise AgentIssueError("untrusted child receipt during postread")
        previous = validate_receipt(_decode(body, RECEIPT_MARKER))
        if previous["assignment_id"] != r["assignment_id"]:
            raise AgentIssueError("foreign receipt during postread")
        if previous["unit_id"] == r["unit_id"] and previous["receipt_id"] != r["receipt_id"]:
            raise AgentIssueError("conflicting append appeared during readback")
        if previous["receipt_id"] == r["receipt_id"]:
            matches.append(c["id"])
    if not matches:
        return {
            "status": "UNKNOWN_WRITE_RESULT", "receipt_id": r["receipt_id"],
            "comment_ids": [],
        }
    return {
        "status": "COMMITTED_APPEND",
        "receipt_id": r["receipt_id"],
        "comment_ids": sorted(set(matches)),
        "logical_receipts": 1,
    }
