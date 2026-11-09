"""Trusted runtime gate for writing Samuel's authoritative Issue #44 ledger.

This is defense in depth, NOT a replacement for GitHub credential isolation.
Environment claims alone are not authoritative: the bootstrap workflow run
must be fetched independently with the same GitHub API credential.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Protocol


REPOSITORY = "HyungseonSong-plasma/chatgpt-operation"
WORKFLOW_PATH = ".github/workflows/samuel-bootstrap.yml"
_STATE_ISSUE = 44
_SHA40 = re.compile(r"^[0-9a-f]{40}$")


class StateWriterAuthorityError(ValueError):
    pass


class RunReader(Protocol):
    def get(self, path: str, *, query: dict[str, str] | None = None) -> Any: ...


def require_bootstrap_state_writer(
    *,
    repository: str,
    issue_number: int,
    environment: Mapping[str, str],
    transport: RunReader,
) -> None:
    """Reject an Issue #44 write outside independently verified Bootstrap.

    Other issue numbers are unaffected by this special authority check.
    The GitHub API does not enforce issue-scoped credentials; any token with
    issues:write may still PATCH comments outside this Python method.
    """
    if not isinstance(repository, str) or not repository:
        raise StateWriterAuthorityError("repository identity is required")
    if type(issue_number) is not int or issue_number <= 0:
        raise StateWriterAuthorityError("invalid state issue number")
    if repository != REPOSITORY or issue_number != _STATE_ISSUE:
        return
    if not isinstance(environment, Mapping):
        raise StateWriterAuthorityError("trusted Bootstrap environment required")
    run_id = str(environment.get("GITHUB_RUN_ID") or "")
    attempt = str(environment.get("GITHUB_RUN_ATTEMPT") or "")
    sha = environment.get("GITHUB_SHA")
    if not (
        environment.get("GITHUB_ACTIONS") == "true"
        and environment.get("GITHUB_WORKFLOW") == "Samuel Bootstrap"
        and environment.get("GITHUB_REPOSITORY") == REPOSITORY
        and environment.get("GITHUB_REF") == "refs/heads/main"
        and environment.get("GITHUB_JOB") == "wake"
        and environment.get("GITHUB_EVENT_NAME") in {"workflow_dispatch", "issues"}
        and run_id.isascii() and run_id.isdecimal() and int(run_id) > 0
        and attempt.isascii() and attempt.isdecimal() and int(attempt) > 0
        and isinstance(sha, str) and _SHA40.fullmatch(sha)
    ):
        raise StateWriterAuthorityError("only current mainline Samuel Bootstrap may persist Issue #44")
    if not hasattr(transport, "get"):
        raise StateWriterAuthorityError("authenticated run reader is required")
    try:
        run = transport.get("/actions/runs/" + run_id)
    except Exception as exc:
        raise StateWriterAuthorityError("authenticated Bootstrap run lookup failed") from exc
    repo = run.get("repository") if isinstance(run, dict) else None
    path = run.get("path") if isinstance(run, dict) else None
    if not (
        isinstance(run, dict)
        and type(run.get("id")) is int and run["id"] == int(run_id)
        and type(run.get("run_attempt")) is int
        and run["run_attempt"] == int(attempt)
        and isinstance(repo, dict) and repo.get("full_name") == REPOSITORY
        and isinstance(path, str)
        and path.split("@", 1)[0] == WORKFLOW_PATH
        and run.get("event") == environment["GITHUB_EVENT_NAME"]
        and run.get("head_sha") == sha
        and run.get("head_branch") == "main"
        and run.get("status") in {"queued", "in_progress"}
    ):
        raise StateWriterAuthorityError("live GitHub run is not the trusted Bootstrap writer")
