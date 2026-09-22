"""Connector-facing workflow_dispatch contract.

This module contains no GitHub credential handling.  It defines the data boundary
between a ChatGPT-hosted GitHub connector action and the deterministic Actions
observation runtime.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any


class ConnectorDispatchError(ValueError):
    """Raised when connector dispatch request/response evidence is unsafe."""


_FORBIDDEN_CREDENTIAL_KEYS = {
    "authorization",
    "credential",
    "credentials",
    "github_token",
    "access_token",
    "token",
}


def _contains_forbidden_credential_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in _FORBIDDEN_CREDENTIAL_KEYS:
                return True
            if _contains_forbidden_credential_key(child):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_credential_key(item) for item in value)
    return False


def _require_nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConnectorDispatchError(f"{field} must be a non-empty string")
    return value


def _validate_requested_at(value: Any) -> str:
    text = _require_nonempty_string(value, "requested_at")
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ConnectorDispatchError("requested_at must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ConnectorDispatchError("requested_at must include a timezone")
    return text


def build_dispatch_action_request(
    *,
    repository: str,
    workflow: str | int,
    ref: str,
    inputs: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    correlation_input: str | None = None,
    expected_head_sha: str | None = None,
) -> dict[str, Any]:
    """Build the credential-free arguments for a connector dispatch action."""
    repository = _require_nonempty_string(repository, "repository")
    if "/" not in repository or repository.startswith("/") or repository.endswith("/"):
        raise ConnectorDispatchError("repository must use owner/name form")
    if not isinstance(workflow, (str, int)) or workflow == "":
        raise ConnectorDispatchError("workflow must be a workflow id, name, or path")
    ref = _require_nonempty_string(ref, "ref")
    supplied_inputs = dict(inputs or {})
    if any(not isinstance(key, str) or not key for key in supplied_inputs):
        raise ConnectorDispatchError("workflow input keys must be non-empty strings")

    request_id = correlation_id or uuid.uuid4().hex
    if correlation_input is not None:
        correlation_input = _require_nonempty_string(
            correlation_input, "correlation_input"
        )
        existing = supplied_inputs.get(correlation_input)
        if existing is not None and existing != request_id:
            raise ConnectorDispatchError(
                f"input {correlation_input!r} conflicts with correlation_id"
            )
        supplied_inputs[correlation_input] = request_id

    if expected_head_sha is not None:
        expected_head_sha = _require_nonempty_string(
            expected_head_sha, "expected_head_sha"
        )

    request = {
        "repository": repository,
        "workflow": workflow,
        "ref": ref,
        "inputs": supplied_inputs,
        "correlation_id": request_id,
        "correlation_input": correlation_input,
        "expected_head_sha": expected_head_sha,
        "return_run_details": True,
    }
    return request


def normalize_dispatch_action_result(
    request: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    """Normalize a connector action response into an #26 observation receipt."""
    if not isinstance(request, dict) or not isinstance(result, dict):
        raise ConnectorDispatchError("request and result must be objects")
    if _contains_forbidden_credential_key(result):
        raise ConnectorDispatchError("connector result exposed credential material")

    workflow_id = result.get("workflow_id")
    if not isinstance(workflow_id, int) or workflow_id < 1:
        raise ConnectorDispatchError("connector result requires workflow_id")

    dispatch_status = result.get("dispatch_status")
    if dispatch_status not in {200, 204}:
        raise ConnectorDispatchError("dispatch_status must be 200 or 204")

    run_id = result.get("workflow_run_id")
    if run_id is not None and (not isinstance(run_id, int) or run_id < 1):
        raise ConnectorDispatchError("workflow_run_id must be a positive integer or null")

    requested_at = _validate_requested_at(result.get("requested_at"))

    receipt = {
        "workflow_id": workflow_id,
        "workflow_path": result.get("workflow_path"),
        "workflow_name": result.get("workflow_name"),
        "ref": _require_nonempty_string(request.get("ref"), "ref"),
        "correlation_id": request.get("correlation_id"),
        "correlation_input": request.get("correlation_input"),
        "requested_at": requested_at,
        "workflow_run_id": run_id,
        "run_url": result.get("run_url"),
        "html_url": result.get("html_url"),
        "dispatch_status": dispatch_status,
        "expected_head_sha": request.get("expected_head_sha"),
    }
    return receipt
