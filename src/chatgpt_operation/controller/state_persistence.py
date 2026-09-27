"""Single durable-state persistence boundary for Samuel controller writes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .durable_state import (
    load_state_comment,
    validate_state_write_precondition,
)


class StatePersistenceError(RuntimeError):
    pass


class IssueCommentTransport(Protocol):
    def get(self, path: str, *, query: dict[str, str] | None = None) -> Any: ...
    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> tuple[int, Any]: ...


@dataclass(frozen=True)
class StatePersistenceResult:
    research_id: str
    revision: int
    method: str
    comment_id: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "research_id": self.research_id,
            "revision": self.revision,
            "method": self.method,
            "comment_id": self.comment_id,
        }


def _comments(
    transport: IssueCommentTransport,
    issue_number: int,
) -> list[dict[str, Any]]:
    payload = transport.get(
        f"/issues/{issue_number}/comments",
        query={"per_page": "100"},
    )
    if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
        raise StatePersistenceError("GitHub comments readback is invalid")
    return payload


def persist_state_write(
    transport: IssueCommentTransport,
    *,
    issue_number: int,
    request: dict[str, Any],
) -> StatePersistenceResult:
    """Validate, persist, and verify one authoritative durable-state write."""
    if not isinstance(issue_number, int) or isinstance(issue_number, bool) or issue_number < 1:
        raise StatePersistenceError("issue_number must be positive")

    before = _comments(transport, issue_number)
    validate_state_write_precondition(before, request)

    method = request["method"]
    body = request["body"]
    comment_id = request["comment_id"]

    if method == "POST":
        status, response = transport.request(
            "POST",
            f"/issues/{issue_number}/comments",
            payload={"body": body},
        )
        if status != 201 or not isinstance(response, dict):
            raise StatePersistenceError("durable state create returned invalid response")
        persisted_comment_id = response.get("id")
    elif method == "PATCH":
        if not isinstance(comment_id, int) or isinstance(comment_id, bool):
            raise StatePersistenceError("durable state update comment_id is invalid")
        status, response = transport.request(
            "PATCH",
            f"/issues/comments/{comment_id}",
            payload={"body": body},
        )
        if status != 200 or not isinstance(response, dict):
            raise StatePersistenceError("durable state update returned invalid response")
        persisted_comment_id = response.get("id", comment_id)
    else:
        raise StatePersistenceError("unsupported durable state write method")

    if not isinstance(persisted_comment_id, int) or isinstance(persisted_comment_id, bool):
        raise StatePersistenceError("durable state write returned invalid comment identity")
    if method == "PATCH" and persisted_comment_id != comment_id:
        raise StatePersistenceError("durable state update changed comment identity")

    after = _comments(transport, issue_number)
    persisted = load_state_comment(after)
    if persisted is None:
        raise StatePersistenceError("durable state disappeared after write")
    if (
        persisted.research_id != request["research_id"]
        or persisted.revision != request["expected_revision"]
    ):
        raise StatePersistenceError("durable state readback mismatch")

    return StatePersistenceResult(
        research_id=persisted.research_id,
        revision=persisted.revision,
        method=method,
        comment_id=persisted_comment_id,
    )
