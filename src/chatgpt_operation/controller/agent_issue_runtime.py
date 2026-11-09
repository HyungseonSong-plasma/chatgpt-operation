"""Read-only authenticated GitHub Child Issue inventory for parent aggregation.

This is the trusted reducer ENTRYPOINT. Never aggregate externally supplied
Child status summaries directly. All pages are read twice for stable bodies.
The source verifier callback MUST retrieve run/artifact facts independently.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Protocol, Sequence

from .agent_issue_partition import (
    AgentIssueError, RECEIPT_MARKER, reduce_child_progress,
    reduce_parent_children, validate_parent_registry,
)


class ChildIssueReader(Protocol):
    def get(self, path: str, *, query: dict[str, str] | None = None) -> Any: ...


_PAGE = 100
_LIMIT = 500


def read_stable_child_comments(
    reader: ChildIssueReader, *, child_issue: int,
) -> list[dict[str, Any]]:
    if type(child_issue) is not int or child_issue <= 0:
        raise AgentIssueError("invalid Child Issue identity")
    path = f"/issues/{child_issue}/comments"

    def collect() -> list[dict[str, Any]]:
        gathered = []
        ids = set()
        # One extra page is required to detect exact-limit overflow.
        for page in range(1, _LIMIT // _PAGE + 2):
            rows = reader.get(path, query={"per_page": str(_PAGE), "page": str(page)})
            if not isinstance(rows, list) or len(rows) > _PAGE:
                raise AgentIssueError("invalid or truncated Child comment page")
            for row in rows:
                if (
                    not isinstance(row, dict)
                    or type(row.get("id")) is not int
                    or row["id"] <= 0
                    or not isinstance(row.get("body"), str)
                    or not isinstance(row.get("user"), dict)
                ):
                    raise AgentIssueError("malformed Child GitHub comment")
                if row["id"] in ids:
                    raise AgentIssueError("duplicate Child comment ID across pages")
                ids.add(row["id"])
                if RECEIPT_MARKER in row["body"]:
                    # GitHub exposes the creation/last-edit timestamp. Existing
                    # receipts should never be edited after their first POST.
                    created = row.get("created_at")
                    modified = row.get("updated_at")
                    if (
                        not isinstance(created, str)
                        or not isinstance(modified, str)
                        or not created
                        or modified != created
                    ):
                        raise AgentIssueError("edited or untraceable Child receipt")
                gathered.append(row)
            if len(gathered) > _LIMIT:
                raise AgentIssueError("Child comment inventory exceeds safety bound")
            if len(rows) < _PAGE:
                return gathered
        raise AgentIssueError("Child comment pagination did not terminate")

    first = collect()
    second = collect()
    def key(rows: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
        return [
            (x["id"], x["body"], x["user"].get("login"),
             x.get("created_at"), x.get("updated_at"))
            for x in rows
        ]
    if key(first) != key(second):
        raise AgentIssueError("Child GitHub comments changed during inventory")
    return second


def reduce_verified_parent_children(
    reader: ChildIssueReader,
    *,
    registry: Sequence[dict[str, Any]],
    trusted_comment_authors: frozenset[str],
    live_gate_states: Mapping[str, str],
    verify_source: Callable[[dict[str, Any]], Mapping[str, Any]],
) -> dict[str, Any]:
    """Never accept purported complete summaries; always verify live Issues."""
    assignments = validate_parent_registry(registry)
    reports = []
    for assignment in assignments:
        number = assignment["child_issue"]
        observed_issue = reader.get(f"/issues/{number}")
        if not isinstance(observed_issue, dict):
            raise AgentIssueError("live Child Issue is missing")
        comments = read_stable_child_comments(reader, child_issue=number)
        reports.append(reduce_child_progress(
            observed_issue, comments, assignment,
            parent_registry=assignments,
            trusted_comment_authors=trusted_comment_authors,
            live_gate_states=live_gate_states,
            verify_source=verify_source,
        ))
    return reduce_parent_children(reports, registry=assignments)
