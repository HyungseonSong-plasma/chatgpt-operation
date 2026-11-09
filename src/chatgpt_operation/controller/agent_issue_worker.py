"""Manually dispatched, scoped Agent Child document evidence publisher.

Only approved mainline GitHub Actions run may read the trusted parent
allocation and append an immutable receipt to that specific Child. Never
PATCH the parent or a prior receipt. The parent independently re-verifies
the finished run/artifact before accepting the receipt.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping

from chatgpt_operation.github.actions_runtime import (
    ActionsApiError, GitHubActionsTransport,
)
from .agent_issue_append import plan_child_append, reconcile_child_append_ack
from .agent_issue_partition import AgentIssueError, validate_receipt
from .agent_issue_provision import read_live_parent_registry
from .agent_issue_runtime import read_stable_child_comments
from .agent_issue_source import build_readonly_document_receipt

SOURCE_REPOSITORY = "HyungseonSong-plasma/chatgpt-operation"
EXPECTED_WORKFLOW = ".github/workflows/samuel-agent-child-evidence.yml"
EXPECTED_ACTOR = "HyungseonSong-plasma"
EXPECTED_EVENT = "workflow_dispatch"
PARENT_ISSUE = 44


class AgentWorkerError(AgentIssueError):
    pass


def verified_worker_identity(
    reader: GitHubActionsTransport, environment: Mapping[str, str],
) -> tuple[int, str]:
    """Verify actual trusted GitHub run metadata; environment is not authority."""
    if not isinstance(environment, Mapping):
        raise AgentWorkerError("untrusted worker environment")
    if not all((
        environment.get("GITHUB_ACTIONS") == "true",
        environment.get("GITHUB_REPOSITORY") == SOURCE_REPOSITORY,
        environment.get("GITHUB_EVENT_NAME") == EXPECTED_EVENT,
        environment.get("GITHUB_REF") == "refs/heads/main",
        environment.get("GITHUB_ACTOR") == EXPECTED_ACTOR,
    )):
        raise AgentWorkerError("only approved owner-dispatched mainline worker is allowed")
    run_id = str(environment.get("GITHUB_RUN_ID", ""))
    attempt = str(environment.get("GITHUB_RUN_ATTEMPT", ""))
    sha = environment.get("GITHUB_SHA")
    if not (
        run_id.isascii() and run_id.isdecimal() and int(run_id) > 0
        and attempt == "1" and isinstance(sha, str) and len(sha) == 40
        and all(c in "0123456789abcdef" for c in sha)
    ):
        raise AgentWorkerError("invalid run attempt, ID, or source SHA")
    actual = reader.get("/actions/runs/" + run_id)
    if not isinstance(actual, dict):
        raise AgentWorkerError("authenticated GitHub run missing")
    actor, repo = actual.get("actor"), actual.get("repository")
    path = actual.get("path")
    if not all((
        type(actual.get("id")) is int and actual["id"] == int(run_id),
        type(actual.get("run_attempt")) is int and actual["run_attempt"] == 1,
        actual.get("head_sha") == sha,
        actual.get("head_branch") == "main",
        actual.get("event") == EXPECTED_EVENT,
        isinstance(path, str) and path.split("@", 1)[0] == EXPECTED_WORKFLOW,
        isinstance(actor, dict) and actor.get("login") == EXPECTED_ACTOR,
        isinstance(repo, dict) and repo.get("full_name") == SOURCE_REPOSITORY,
        actual.get("status") in ("queued", "in_progress"),
    )):
        raise AgentWorkerError("GitHub run is not approved Child evidence producer")
    return int(run_id), sha


def _assignment_for_child(
    reader: GitHubActionsTransport, *, child_issue: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if type(child_issue) is not int or child_issue <= 0 or child_issue == PARENT_ISSUE:
        raise AgentWorkerError("invalid requested Child Issue number")
    registry = read_live_parent_registry(
        reader,repository=SOURCE_REPOSITORY,parent_issue=PARENT_ISSUE,
    )
    selected = [x for x in registry if x["child_issue"] == child_issue]
    if len(selected) != 1:
        raise AgentWorkerError("Child is not uniquely allocated by parent Bootstrap")
    return selected[0],registry


def produce_child_manifest(
    reader: GitHubActionsTransport, *,
    environment: Mapping[str, str], child_issue: int,
    unit_id: str, source_root: Path,
) -> dict[str, Any]:
    if type(child_issue) is not int or child_issue <= 0 or child_issue == PARENT_ISSUE:
        raise AgentWorkerError("invalid requested Child Issue number")
    run_id,sha=verified_worker_identity(reader,environment)
    assignment,_ = _assignment_for_child(reader,child_issue=child_issue)
    receipt=build_readonly_document_receipt(
        assignment,unit_id=unit_id,run_id=run_id,
        source_sha=sha,root=source_root,
    )
    return {"schema_version":1,"receipt":receipt}


def publish_child_manifest(
    reader: GitHubActionsTransport, *,
    environment: Mapping[str, str], child_issue: int,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    if type(child_issue) is not int or child_issue <= 0 or child_issue == PARENT_ISSUE:
        raise AgentWorkerError("invalid requested Child Issue number")
    run_id,sha=verified_worker_identity(reader,environment)
    assignment,registry=_assignment_for_child(reader,child_issue=child_issue)
    if (
        not isinstance(manifest,dict)
        or set(manifest)!={"schema_version","receipt"}
        or manifest["schema_version"]!=1
    ):
        raise AgentWorkerError("invalid local evidence manifest")
    receipt=validate_receipt(manifest["receipt"])
    if (
        receipt["source_run_id"]!=run_id
        or receipt["source_head_sha"]!=sha
        or receipt["assignment_id"]!=assignment["assignment_id"]
        or receipt["child_issue"]!=child_issue
        or receipt["agent_id"]!=assignment["agent_id"]
    ):
        raise AgentWorkerError("evidence does not belong to this worker run and Child")
    issue=reader.get("/issues/"+str(child_issue))
    if not isinstance(issue,dict):
        raise AgentWorkerError("target Child Issue was not found")
    comments=read_stable_child_comments(reader,child_issue=child_issue)
    candidate=plan_child_append(
        issue,comments,assignment,receipt,
        parent_registry=registry,
        trusted_authors=frozenset({"github-actions[bot]"}),
    )
    if candidate["status"]=="ALREADY_PRESENT":
        return {
            "status":"ALREADY_PRESENT","receipt_id":receipt["receipt_id"],
            "child_issue":child_issue,"parent_state_patch":False,
        }
    if (
        candidate["method"]!="POST"
        or candidate["path"]!="/issues/"+str(child_issue)+"/comments"
    ):
        raise AgentWorkerError("worker attempted non-Child or non-append operation")
    # No blind retry on API exceptions. Reconcile by querying GitHub.
    transport_error: Exception | None=None
    try:
        status,_=reader.request(
            candidate["method"],candidate["path"],
            payload={"body":candidate["body"]},
        )
        if status!=201:
            raise AgentWorkerError("Child receipt POST was not acknowledged")
    except (ActionsApiError, TimeoutError, OSError) as exc:
        transport_error=exc
    fresh=read_stable_child_comments(reader,child_issue=child_issue)
    final=reconcile_child_append_ack(
        fresh,receipt=receipt,
        trusted_authors=frozenset({"github-actions[bot]"}),
    )
    if final["status"]!="COMMITTED_APPEND":
        raise AgentWorkerError(
            "Child append result UNKNOWN; retry only after authoritative readback"
        ) from transport_error
    return {
        **final, "child_issue":child_issue,"parent_state_patch":False,
    }


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("phase",choices=("produce","publish"))
    parser.add_argument("--child",required=True,type=int)
    parser.add_argument("--unit",default="")
    parser.add_argument("--output",default="agent-receipt.json")
    args=parser.parse_args()
    token=os.environ.get("GITHUB_TOKEN","")
    if not token:
        raise AgentWorkerError("runtime GitHub token is required")
    reader=GitHubActionsTransport(SOURCE_REPOSITORY,token)
    if args.phase=="produce":
        if not args.unit:
            raise AgentWorkerError("source unit is required")
        if not (Path.cwd()/".git").exists():
            raise AgentWorkerError("source must be checked out in exact worktree")
        result=produce_child_manifest(
            reader,environment=os.environ,child_issue=args.child,
            unit_id=args.unit,source_root=Path.cwd(),
        )
    else:
        result=publish_child_manifest(
            reader,environment=os.environ,child_issue=args.child,
            manifest=json.loads(Path(args.output).read_text(encoding="utf-8")),
        )
    if args.phase=="produce":
        Path(args.output).write_text(
            json.dumps(result,sort_keys=True,separators=(",",":"),
                       ensure_ascii=False)+"\n",encoding="utf-8",
        )
    else:
        print("SAMUEL_AGENT_CHILD_APPEND="+result["status"])
    return 0


if __name__=="__main__":
    raise SystemExit(main())
