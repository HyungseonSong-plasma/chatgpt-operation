"""Portable GitHub Actions dispatch and observation runtime."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from chatgpt_operation.github.actions_observation import evaluate

DEFAULT_API_VERSION = "2026-03-10"


class ActionsRuntimeError(RuntimeError):
    """Base error for portable GitHub Actions runtime operations."""


class ActionsApiError(ActionsRuntimeError):
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


class ActionsTransport(Protocol):
    def get(self, path: str, *, query: dict[str, str] | None = None) -> Any: ...
    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> tuple[int, Any]: ...


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class GitHubActionsTransport:
    """Minimal stdlib GitHub REST transport for Actions operations."""

    def __init__(
        self,
        repository: str,
        token: str,
        *,
        api_url: str = "https://api.github.com",
        api_version: str = DEFAULT_API_VERSION,
        timeout: int = 30,
    ):
        self.repository = repository
        self.token = token
        self.api_url = api_url.rstrip("/")
        self.api_version = api_version
        self.timeout = timeout

    def _call(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        url = f"{self.api_url}/repos/{self.repository}{path}"
        if query:
            url += "?" + urlencode(query)
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(url, data=data, method=method)
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("X-GitHub-Api-Version", self.api_version)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                status = getattr(response, "status", response.getcode())
                body = response.read()
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(body).get("message", "GitHub API error")
            except json.JSONDecodeError:
                detail = "GitHub API returned non-JSON error"
            raise ActionsApiError(
                f"GitHub API {method} {path} -> {exc.code}: {detail}",
                status=exc.code,
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ActionsApiError(
                f"GitHub API {method} {path} transport failure: {type(exc).__name__}"
            ) from exc

        if not body:
            return int(status), None
        try:
            return int(status), json.loads(body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ActionsApiError(
                f"GitHub API {method} {path} returned invalid JSON"
            ) from exc

    def get(self, path: str, *, query: dict[str, str] | None = None) -> Any:
        return self._call("GET", path, query=query)[1]

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> tuple[int, Any]:
        return self._call(method, path, payload=payload)


def _workflow_path(workflow: str | int) -> str:
    return "/actions/workflows/" + quote(str(workflow), safe="")


def resolve_workflow(transport: ActionsTransport, workflow: str | int) -> dict[str, Any]:
    """Resolve a workflow registered on the repository default branch."""
    payload = transport.get(_workflow_path(workflow))
    if not isinstance(payload, dict) or not isinstance(payload.get("id"), int):
        raise ActionsRuntimeError("workflow resolution returned invalid evidence")
    return payload


def dispatch_workflow(
    transport: ActionsTransport,
    *,
    workflow: str | int,
    ref: str,
    inputs: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    correlation_input: str | None = "correlation_id",
    now: Callable[[], datetime] = _now,
) -> dict[str, Any]:
    """Dispatch one workflow and return a durable correlation receipt."""
    if not isinstance(ref, str) or not ref:
        raise ActionsRuntimeError("ref must be a non-empty branch or tag name")
    if correlation_input is not None and (
        not isinstance(correlation_input, str) or not correlation_input
    ):
        raise ActionsRuntimeError("correlation_input must be non-empty or null")

    workflow_meta = resolve_workflow(transport, workflow)
    workflow_id = workflow_meta["id"]
    request_id = correlation_id or uuid.uuid4().hex
    dispatch_inputs = dict(inputs or {})
    if correlation_input is not None:
        existing = dispatch_inputs.get(correlation_input)
        if existing is not None and existing != request_id:
            raise ActionsRuntimeError(
                f"input {correlation_input!r} conflicts with correlation_id"
            )
        dispatch_inputs[correlation_input] = request_id

    requested_at = _iso(now())
    payload: dict[str, Any] = {
        "ref": ref,
        "inputs": dispatch_inputs,
        "return_run_details": True,
    }
    status, response = transport.request(
        "POST",
        f"/actions/workflows/{workflow_id}/dispatches",
        payload=payload,
    )
    if status not in {200, 204}:
        raise ActionsRuntimeError(f"unexpected workflow dispatch status: {status}")

    run_id = None
    run_url = None
    html_url = None
    if response is not None:
        if not isinstance(response, dict):
            raise ActionsRuntimeError("workflow dispatch returned invalid response")
        run_id = response.get("workflow_run_id")
        run_url = response.get("run_url")
        html_url = response.get("html_url")
        if run_id is not None and not isinstance(run_id, int):
            raise ActionsRuntimeError("workflow_run_id must be an integer")

    return {
        "workflow_id": workflow_id,
        "workflow_path": workflow_meta.get("path"),
        "workflow_name": workflow_meta.get("name"),
        "ref": ref,
        "correlation_id": request_id,
        "correlation_input": correlation_input,
        "requested_at": requested_at,
        "workflow_run_id": run_id,
        "run_url": run_url,
        "html_url": html_url,
        "dispatch_status": status,
    }


def _run_evidence(
    run: dict[str, Any],
    *,
    receipt: dict[str, Any],
    direct_receipt_binding: bool,
) -> dict[str, Any]:
    required = ("id", "workflow_id", "event", "created_at", "run_attempt", "status")
    if any(key not in run for key in required):
        raise ActionsRuntimeError("workflow run evidence is incomplete")
    return {
        "run_id": run["id"],
        "workflow": str(run["workflow_id"]),
        "event": run["event"],
        "correlation_id": (
            receipt.get("correlation_id") if direct_receipt_binding else None
        ),
        "head_sha": run.get("head_sha"),
        "ref": receipt.get("ref") if direct_receipt_binding else run.get("head_branch"),
        "created_at": run["created_at"],
        "run_attempt": run["run_attempt"],
        "status": run["status"],
        "conclusion": run.get("conclusion"),
    }


def _enumerate_runs(
    transport: ActionsTransport,
    *,
    workflow_id: int,
    event: str,
    ref: str,
    max_pages: int = 100,
) -> tuple[list[dict[str, Any]], bool]:
    runs: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        payload = transport.get(
            f"/actions/workflows/{workflow_id}/runs",
            query={
                "event": event,
                "branch": ref,
                "per_page": "100",
                "page": str(page),
            },
        )
        if not isinstance(payload, dict) or not isinstance(
            payload.get("workflow_runs"), list
        ):
            raise ActionsRuntimeError(
                "workflow run enumeration returned invalid evidence"
            )
        page_runs = payload["workflow_runs"]
        runs.extend(page_runs)
        if len(page_runs) < 100:
            return runs, True
    return runs, False


def observe_dispatch_once(
    transport: ActionsTransport,
    receipt: dict[str, Any],
    *,
    visibility_grace_seconds: int = 60,
    expected_head_sha: str | None = None,
    run_attempt: int | None = None,
    now: Callable[[], datetime] = _now,
) -> dict[str, Any]:
    """Observe one dispatch through the deterministic observation core."""
    try:
        workflow_id = int(receipt["workflow_id"])
        requested_at = str(receipt["requested_at"])
        ref = str(receipt["ref"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ActionsRuntimeError("dispatch receipt is incomplete") from exc

    direct_run_id = receipt.get("workflow_run_id")
    direct_binding = isinstance(direct_run_id, int)
    enumeration_complete = True

    if direct_binding:
        try:
            raw_run = transport.get(f"/actions/runs/{direct_run_id}")
            raw_runs = [] if raw_run is None else [raw_run]
        except ActionsApiError as exc:
            if exc.status == 404:
                raw_runs = []
            else:
                raise
    else:
        raw_runs, enumeration_complete = _enumerate_runs(
            transport,
            workflow_id=workflow_id,
            event="workflow_dispatch",
            ref=ref,
        )

    try:
        runs = [
            _run_evidence(
                run,
                receipt=receipt,
                direct_receipt_binding=direct_binding,
            )
            for run in raw_runs
        ]
    except ActionsRuntimeError:
        return {"status": "OBSERVATION_INCOMPLETE", "matched_run_ids": []}

    request_correlation = (
        receipt.get("correlation_id")
        if direct_binding or receipt.get("correlation_input") is not None
        else None
    )
    snapshot = {
        "request": {
            "workflow": str(workflow_id),
            "event": "workflow_dispatch",
            "correlation_id": request_correlation,
            "head_sha": expected_head_sha,
            "ref": ref,
            "requested_at": requested_at,
            "visibility_grace_seconds": visibility_grace_seconds,
            "run_attempt": run_attempt,
        },
        "observation": {
            "observed_at": _iso(now()),
            "enumeration_complete": enumeration_complete,
            "runs": runs,
        },
    }
    result = evaluate(snapshot)
    result["workflow_run_id"] = direct_run_id
    result["correlation_id"] = request_correlation
    return result


def wait_for_dispatch(
    transport: ActionsTransport,
    receipt: dict[str, Any],
    *,
    visibility_grace_seconds: int = 60,
    expected_head_sha: str | None = None,
    run_attempt: int | None = None,
    timeout_seconds: float = 600,
    poll_interval_seconds: float = 5,
    now: Callable[[], datetime] = _now,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Poll only while the observation is pending or active."""
    if timeout_seconds < 0 or poll_interval_seconds < 0:
        raise ActionsRuntimeError("timeout and poll interval must be non-negative")
    deadline = monotonic() + timeout_seconds
    while True:
        result = observe_dispatch_once(
            transport,
            receipt,
            visibility_grace_seconds=visibility_grace_seconds,
            expected_head_sha=expected_head_sha,
            run_attempt=run_attempt,
            now=now,
        )
        if result["status"] not in {"PENDING_VISIBILITY", "MATCHED_ACTIVE"}:
            return result
        current = monotonic()
        if current >= deadline:
            result = dict(result)
            result["wait_timeout"] = True
            return result
        sleep(min(poll_interval_seconds, max(0.0, deadline - current)))


def dispatch_and_wait(
    transport: ActionsTransport,
    *,
    workflow: str | int,
    ref: str,
    inputs: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    correlation_input: str | None = "correlation_id",
    visibility_grace_seconds: int = 60,
    expected_head_sha: str | None = None,
    run_attempt: int | None = None,
    timeout_seconds: float = 600,
    poll_interval_seconds: float = 5,
) -> dict[str, Any]:
    """High-level portable dispatch -> observation operation."""
    receipt = dispatch_workflow(
        transport,
        workflow=workflow,
        ref=ref,
        inputs=inputs,
        correlation_id=correlation_id,
        correlation_input=correlation_input,
    )
    observation = wait_for_dispatch(
        transport,
        receipt,
        visibility_grace_seconds=visibility_grace_seconds,
        expected_head_sha=expected_head_sha,
        run_attempt=run_attempt,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    return {"dispatch": receipt, "observation": observation}


def execution_result_artifact_metadata(
    transport: ActionsTransport,
    run_id: int,
) -> dict[str, Any]:
    """Resolve exactly one typed native execution-result artifact for a verified run."""
    payload = transport.get(f"/actions/runs/{int(run_id)}/artifacts")
    artifacts = payload.get("artifacts") if isinstance(payload, dict) else None
    if not isinstance(artifacts, list):
        raise ActionsRuntimeError("artifact enumeration returned invalid evidence")
    matches = [
        item for item in artifacts
        if isinstance(item, dict)
        and str(item.get("name", "")).startswith("samuel-execution-result-")
        and item.get("expired") is not True
    ]
    if len(matches) != 1 or not isinstance(matches[0].get("id"), int):
        raise ActionsRuntimeError("expected exactly one live typed execution-result artifact")
    return matches[0]
