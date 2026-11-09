"""Read-only fail-closed scope preflight for a dedicated Samuel work cycle.

This module is a candidate for repository-owned Bootstrap composition.  It
does not dispatch GitHub workflows, admit Issues, mutate a ResearchState, or
grant the external ChatGPT scheduler permission to select work.

A successful snapshot check alone is NOT an authorization to dispatch:
the exact expected work ID must additionally be bound and enforced by the
trusted Bootstrap root at execution time.  The existing production workflow
does not yet pass such a binding.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .durable_state import load_state_comment
from .issue_ingestion import ADMISSION_MARKER, decode_admission_ledger

_WORK_ID = re.compile(r"issue:[1-9][0-9]*\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_NONTERMINAL = frozenset({
    "admitted", "reasoning_required", "planned", "active",
    "blocked", "revision_required",
})


@dataclass(frozen=True)
class ScopedWorkDecision:
    requested_work_id: str
    status: str
    reason: str

    @property
    def allowed(self) -> bool:
        return self.status == "SCOPE_CANDIDATE"


def assess_scoped_work_snapshot(
    *,
    requested_work_id: str,
    comments: list[dict[str, Any]],
    repository_context: dict[str, Any] | None,
) -> ScopedWorkDecision:
    """Validate an immutable-invocation snapshot without proposing any write.

    SCOPE_CANDIDATE means only that this snapshot contains no detected
    cross-work conflict; it must never be treated as dispatch permission.
    The caller must bind the requested ID through a trusted root and refresh
    all mutable state immediately before any repository-owned mutation.
    """
    def blocked(reason: str) -> ScopedWorkDecision:
        return ScopedWorkDecision(
            requested_work_id=str(requested_work_id),
            status="BLOCKED_SCOPE", reason=reason,
        )

    if not isinstance(requested_work_id, str) or not _WORK_ID.fullmatch(requested_work_id):
        return blocked("invalid or absent typed work ID")
    if not isinstance(repository_context, dict):
        return blocked("authenticated repository context missing")
    if repository_context.get("open_issues_complete") is not True:
        return blocked("open Issue inventory is incomplete")
    repository = repository_context.get("repository")
    head = repository_context.get("observed_head_sha")
    if (
        not isinstance(repository, str)
        or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
        or not isinstance(head, str)
        or not _SHA.fullmatch(head)
    ):
        return blocked("repository identity or exact HEAD is not pinned")
    issues = repository_context.get("open_issues")
    if not isinstance(issues, list):
        return blocked("open Issue snapshot missing")

    issue_number = int(requested_work_id.split(":")[1])
    matches: list[dict[str, Any]] = []
    for issue in issues:
        if not isinstance(issue, dict) or type(issue.get("number")) is not int:
            return blocked("malformed open Issue snapshot")
        if issue.get("number") == issue_number:
            matches.append(issue)
        labels = issue.get("labels", [])
        if not isinstance(labels, list):
            return blocked("malformed Issue label inventory")
        names = {
            item if isinstance(item, str) else item.get("name")
            for item in labels
            if isinstance(item, (str, dict))
        }
        if "samuel" in names and issue.get("number") != issue_number:
            return blocked("another open Samuel Issue is still eligible")
    if len(matches) != 1:
        return blocked("requested Issue is missing or duplicated in live snapshot")
    issue = matches[0]
    labels = issue.get("labels", [])
    if (
        issue.get("state") != "open"
        or issue.get("pull_request") is not None
        or not any(
            label == "samuel"
            or isinstance(label, dict) and label.get("name") == "samuel"
            for label in labels
        )
    ):
        return blocked("requested task Parent is not an open admitted Issue")

    if not isinstance(comments, list):
        return blocked("global durable ledger comments missing")
    admission = [
        item for item in comments
        if isinstance(item, dict)
        and ADMISSION_MARKER in str(item.get("body", ""))
    ]
    if len(admission) != 1:
        return blocked("global Admission ledger is absent or ambiguous")
    try:
        ledger = decode_admission_ledger(str(admission[0]["body"]))
        state = load_state_comment(comments)
    except (ValueError, TypeError, KeyError) as exc:
        return blocked("global durable ledger invalid: " + type(exc).__name__)
    if not isinstance(ledger, dict):
        return blocked("global Admission ledger malformed")
    current = ledger.get(requested_work_id)
    if (
        not isinstance(current, dict)
        or current.get("work_id") != requested_work_id
        or current.get("issue_number") != issue_number
        or current.get("status") not in {"admitted", "reasoning_required", "planned", "active"}
        or current.get("title") != issue.get("title")
        or current.get("body") != issue.get("body")
        or current.get("html_url") !=
            f"https://github.com/{repository}/issues/{issue_number}"
    ):
        return blocked("requested Issue is not durably admitted at exact identity")
    for work_id, work in ledger.items():
        if work_id == requested_work_id:
            continue
        if not isinstance(work, dict):
            return blocked("malformed competing ledger work")
        if work.get("status") in _NONTERMINAL:
            return blocked("another durable work item is nonterminal: " + work_id)
    if state is not None:
        if state.research_id != requested_work_id:
            return blocked("global ResearchState is owned by " + state.research_id)
        if any(
            isinstance(failure, dict)
            and failure.get("status") in {"blocked", "escalated", "retryable"}
            for failure in state.predispatch_failures.values()
        ):
            return blocked("requested work has an unresolved predispatch blocker")
    return ScopedWorkDecision(
        requested_work_id=requested_work_id,
        status="SCOPE_CANDIDATE",
        reason="single candidate only; trusted Bootstrap binding still required",
    )
