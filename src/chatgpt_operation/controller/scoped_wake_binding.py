"""Repository-owned, read-only Samuel scoped wake binding (draft only).

The external scheduler MAY request canonical Bootstrap wake, but MUST NEVER
choose its work ID.  This preview derives a candidate solely from a checked-in
repository-owned scope and independently fetched native GitHub Actions run data.
A preview never grants repository write / workflow execution authority.

A trusted, authenticated read adapter must implement get_run(run_id); tests
using a fake adapter verify only logic, not production transport security.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping, Protocol

from .scoped_work_gate import assess_scoped_work_snapshot

_CANONICAL_PATH = ".github/workflows/samuel-bootstrap.yml"
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_WORK = re.compile(r"issue:[1-9][0-9]*\Z")
_FIELDS = frozenset({
    "schema_version", "repository", "workflow", "ref",
    "work_id", "mode", "enabled",
})


class NativeWorkflowRunReader(Protocol):
    """An authenticated repository-owned GitHub REST read port."""

    def get_run(self, run_id: int) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class ScopedWakeBinding:
    status: str
    work_id: str
    reason: str
    run_id: int | None = None
    head_sha: str | None = None
    dispatch_authorized: bool = False
    admission_write: None = None
    state_write: None = None
    execution_command: None = None

    @property
    def candidate(self) -> bool:
        return self.status == "SCOPE_CANDIDATE"


def evaluate_repository_owned_wake(
    *,
    scope: Mapping[str, Any],
    run_reader: NativeWorkflowRunReader,
    run_id: int,
    run_attempt: int,
    comments: list[dict[str, Any]],
    repository_context: dict[str, Any],
) -> ScopedWakeBinding:
    """Preflight a repository-owned target; never select from scheduler input.

    A success is read-only SCOPE_CANDIDATE, not permission to dispatch. The
    scope must be compiled from the checked-out repository and the run_reader
    must independently fetch the current run using a native authenticated port.
    An untrusted caller-provided run dict must never be passed as such a reader.
    """
    def blocked(reason: str, work_id: str = "") -> ScopedWakeBinding:
        return ScopedWakeBinding("BLOCKED_SCOPE", work_id, reason)

    if not isinstance(scope, Mapping) or set(scope) != _FIELDS:
        return blocked("scope contract has unknown or missing fields")
    work_id = scope.get("work_id")
    if (
        type(scope.get("schema_version")) is not int
        or scope["schema_version"] != 1
        or not isinstance(work_id, str)
        or not _WORK.fullmatch(work_id)
        or not isinstance(scope.get("repository"), str)
        or not _REPO.fullmatch(scope["repository"])
        or scope.get("workflow") != "samuel-bootstrap.yml"
        or scope.get("ref") != "main"
        or scope.get("mode") != "preview_only"
        or type(scope.get("enabled")) is not bool
    ):
        return blocked("invalid or non-preview repository-owned scope")
    if scope["enabled"] is not True:
        return blocked("repository-owned scope remains disabled", work_id)
    if not isinstance(repository_context, dict):
        return blocked("repository context missing", work_id)
    if repository_context.get("repository") != scope["repository"]:
        return blocked("repository scope identity mismatch", work_id)
    expected_sha = repository_context.get("observed_head_sha")
    if not isinstance(expected_sha, str) or not _SHA.fullmatch(expected_sha):
        return blocked("exact observed repository SHA missing", work_id)
    if (
        type(run_id) is not int or run_id <= 0
        or type(run_attempt) is not int or run_attempt <= 0
    ):
        return blocked("invalid trusted run identity", work_id)

    # The native reader, not the caller's event payload, obtains run evidence.
    try:
        run = run_reader.get_run(run_id)
    except (LookupError, RuntimeError, ValueError, OSError):
        return blocked("native run readback unavailable", work_id)
    if not isinstance(run, Mapping):
        return blocked("native run readback malformed", work_id)
    rrepo = run.get("repository")
    if not isinstance(rrepo, Mapping):
        return blocked("native run repository identity absent", work_id)
    run_path = run.get("path")
    if (
        type(run.get("id")) is not int or run["id"] != run_id
        or type(run.get("run_attempt")) is not int
        or run["run_attempt"] != run_attempt
        or rrepo.get("full_name") != scope["repository"]
        or run.get("event") != "workflow_dispatch"
        or run_path not in (_CANONICAL_PATH, _CANONICAL_PATH + "@refs/heads/main")
        or run.get("head_branch") != "main"
        or run.get("head_sha") != expected_sha
        or run.get("status") != "in_progress"
        or run.get("conclusion") is not None
    ):
        return blocked("canonical in-flight Bootstrap provenance mismatch", work_id)

    result = assess_scoped_work_snapshot(
        requested_work_id=work_id,
        comments=comments,
        repository_context=repository_context,
    )
    if not result.allowed:
        return blocked(result.reason, work_id)
    return ScopedWakeBinding(
        "SCOPE_CANDIDATE", work_id,
        "trusted native run and single repository-owned work candidate; "
        "still preview only, dispatch is not authorized",
        run_id=run_id, head_sha=expected_sha,
    )
