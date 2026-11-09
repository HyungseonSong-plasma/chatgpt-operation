"""Read-only native GitHub adapter for proposed Samuel scoped wake.

Only a repository-owned checked-in policy can nominate a work ID.  The
GitHub REST transport must be authenticated by the trusted Bootstrap runner.
This module issues GET requests only and *never* authorizes dispatch or a
ResearchState/admission write.  A preview result is diagnostic, not a grant.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Any, Mapping, Protocol

from .scoped_wake_binding import ScopedWakeBinding, evaluate_repository_owned_wake

_POLICY_PATH = "automation/samuel/agent-child-scoped-preview-281.json"
_WORKFLOW_PATH = ".github/workflows/samuel-bootstrap.yml"
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_MAX_OPEN_ISSUES = 1000
_MAX_STATE_COMMENTS = 500


class NativeReadPort(Protocol):
    def get(self, path: str, *, query: dict[str, str] | None = None) -> Any: ...


class NativeScopeReadError(ValueError):
    """A missing, unstable, malformed, or mismatched authoritative read."""


def _require_sha(value: Any) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise NativeScopeReadError("invalid exact source SHA")
    return value


def _stable_pages(
    transport: NativeReadPort, path: str, *,
    limit: int, filters: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Two complete identical inventory traversals, with an overflow sentinel."""
    def read() -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        ids: set[int] = set()
        for page in range(1, limit // 100 + 2):
            payload = transport.get(path, query={
                **dict(filters or {}), "per_page": "100", "page": str(page),
            })
            if not isinstance(payload, list) or len(payload) > 100:
                raise NativeScopeReadError("invalid paginated native GitHub response")
            for obj in payload:
                if (
                    not isinstance(obj, dict)
                    or type(obj.get("id")) is not int or obj["id"] <= 0
                    or obj["id"] in ids
                ):
                    raise NativeScopeReadError("missing or duplicate native object identity")
                ids.add(obj["id"])
                result.append(obj)
                if len(result) > limit:
                    raise NativeScopeReadError("native inventory overflow")
            if len(payload) < 100:
                return result
        raise NativeScopeReadError("native pagination did not terminate")

    first = read()
    second = read()
    if first != second:
        raise NativeScopeReadError("native inventory changed during read")
    return second


def _read_policy(transport: NativeReadPort, head: str) -> dict[str, Any]:
    raw = transport.get(
        "/contents/" + _POLICY_PATH, query={"ref": _require_sha(head)},
    )
    if (
        not isinstance(raw, dict)
        or raw.get("path") != _POLICY_PATH
        or raw.get("type") != "file"
        or raw.get("encoding") != "base64"
        or not isinstance(raw.get("content"), str)
    ):
        raise NativeScopeReadError("pinned policy file unavailable")
    try:
        payload = base64.b64decode(
            "".join(raw["content"].split()), validate=True,
        )
        if len(payload) > 16_384:
            raise NativeScopeReadError("pinned policy exceeds bound")
        doc = json.loads(payload.decode("utf-8"))
    except (binascii.Error, UnicodeError, json.JSONDecodeError) as exc:
        raise NativeScopeReadError("invalid pinned policy contents") from exc
    if not isinstance(doc, dict):
        raise NativeScopeReadError("pinned scope must be an object")
    return doc


def _run(transport: NativeReadPort, run_id: int) -> Mapping[str, Any]:
    value = transport.get(f"/actions/runs/{run_id}")
    if not isinstance(value, Mapping):
        raise NativeScopeReadError("native run metadata missing")
    return value


def _main_sha(transport: NativeReadPort) -> str:
    result = transport.get("/branches/main")
    if not isinstance(result, dict) or not isinstance(result.get("commit"), dict):
        raise NativeScopeReadError("native main HEAD unavailable")
    return _require_sha(result["commit"].get("sha"))


class _LiveNativeRunReader:
    """Enforces the source-run API path; cannot be filled from event JSON."""

    def __init__(self, transport: NativeReadPort):
        self.transport = transport

    def get_run(self, run_id: int) -> Mapping[str, Any]:
        return _run(self.transport, run_id)


def evaluate_live_scoped_wake(
    transport: NativeReadPort, *,
    repository: str, run_id: int, run_attempt: int,
) -> ScopedWakeBinding:
    """Return a no-write preview from live, stable, complete GitHub readbacks.

    In production the caller MUST instantiate an authenticated
    GitHubActionsTransport for the current GitHub repository.  This function
    does not read external scheduler-selected work IDs, does not POST/PATCH,
    and does not clear previous blockers.
    """
    def blocked(reason: str) -> ScopedWakeBinding:
        return ScopedWakeBinding(
            status="BLOCKED_SCOPE", work_id="", reason=reason,
        )

    if not isinstance(repository, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository,
    ):
        return blocked("invalid native repository identity")
    if type(run_id) is not int or run_id <= 0:
        return blocked("invalid native run ID")
    if type(run_attempt) is not int or run_attempt <= 0:
        return blocked("invalid native run attempt")
    if getattr(transport, "repository", repository) != repository:
        return blocked("native transport repository mismatch")

    try:
        first_run = _run(transport, run_id)
        repo_meta = first_run.get("repository")
        if (
            first_run.get("id") != run_id
            or not isinstance(repo_meta, dict)
            or repo_meta.get("full_name") != repository
            or first_run.get("event") != "workflow_dispatch"
            or first_run.get("path") not in (
                _WORKFLOW_PATH, _WORKFLOW_PATH + "@refs/heads/main",
            )
            or first_run.get("head_branch") != "main"
            or first_run.get("run_attempt") != run_attempt
            or first_run.get("status") != "in_progress"
            or first_run.get("conclusion") is not None
        ):
            return blocked("trusted native Bootstrap run identity mismatch")
        head = _require_sha(first_run.get("head_sha"))
        if _main_sha(transport) != head:
            return blocked("main HEAD drift before scoped inventory")

        scope = _read_policy(transport, head)
        issues = _stable_pages(
            transport, "/issues", limit=_MAX_OPEN_ISSUES,
            filters={"state": "open"},
        )
        comments = _stable_pages(
            transport, "/issues/44/comments", limit=_MAX_STATE_COMMENTS,
        )
        open_issues = [
            x for x in issues
            if x.get("pull_request") is None
        ]
        for item in open_issues:
            if type(item.get("number")) is not int or item["number"] <= 0:
                raise NativeScopeReadError("malformed open issue number")
        context = {
            "repository": repository,
            "observed_head_sha": head,
            "open_issues_complete": True,
            "open_issues": open_issues,
        }
        result = evaluate_repository_owned_wake(
            scope=scope,
            run_reader=_LiveNativeRunReader(transport),
            run_id=run_id,
            run_attempt=run_attempt,
            comments=comments,
            repository_context=context,
        )
        # A passing preflight is strictly a candidate, not a lease. Recheck
        # immutable identity and mutable main to detect drift during reads.
        second_run = _run(transport, run_id)
        if second_run != first_run or _main_sha(transport) != head:
            return blocked("native run or main changed during scoped readback")
        return result
    except (ValueError, KeyError, TypeError, LookupError, OSError, RuntimeError):
        return blocked("native scoped evidence unavailable or invalid")


def main(argv: list[str] | None = None) -> int:
    """Run a no-write scope check inside the canonical native Bootstrap job.

    The trusted GitHub runner controls every identity value.  There is no
    caller-provided work ID and no fallback to a different workflow/ref.
    This entrypoint remains unapplied to production until separate approval.
    """
    import argparse
    import os
    from chatgpt_operation.github.actions_runtime import GitHubActionsTransport

    parser = argparse.ArgumentParser(
        description="Read-only Samuel native scoped Bootstrap preflight",
    )
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    args = parser.parse_args(argv)
    env = os.environ
    def stop(reason: str) -> int:
        print("SCOPED_BOOTSTRAP=BLOCKED_SCOPE " + reason)
        return 2

    if (
        env.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
        or env.get("GITHUB_REF") != "refs/heads/main"
    ):
        return stop("not canonical GitHub Actions workflow_dispatch on main")
    repository = env.get("GITHUB_REPOSITORY", "")
    if not isinstance(repository, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository,
    ):
        return stop("invalid runner repository identity")
    sha = env.get("GITHUB_SHA", "")
    if not isinstance(sha, str) or not _SHA.fullmatch(sha):
        return stop("unbound exact runner HEAD")
    try:
        run_id = int(env.get("GITHUB_RUN_ID", ""))
        run_attempt = int(env.get("GITHUB_RUN_ATTEMPT", ""))
    except (ValueError, TypeError):
        return stop("runner run identity missing")
    if run_id <= 0 or run_attempt <= 0:
        return stop("runner run identity invalid")
    token = env.get(args.token_env, "")
    if not token:
        return stop("authenticated GitHub REST read token absent")
    native = GitHubActionsTransport(repository, token)
    result = evaluate_live_scoped_wake(
        native, repository=repository, run_id=run_id,
        run_attempt=run_attempt,
    )
    # Verify main has not moved relative to the caller's checked-out code.
    if result.candidate and result.head_sha != sha:
        return stop("scope source differs from executable checkout")
    # Never echo secrets or write to any GitHub endpoint.
    print("SCOPED_BOOTSTRAP=" + result.status)
    print(json.dumps({
        "status": result.status,
        "work_id": result.work_id,
        "reason": result.reason,
        "run_id": result.run_id,
        "source_head_sha": result.head_sha,
        "dispatch_authorized": False,
        "admission_write": None,
        "state_write": None,
        "execution_command": None,
    }, sort_keys=True))
    return 0 if result.candidate else 2


if __name__ == "__main__":
    raise SystemExit(main())
