"""Read-only parent audit across the live authenticated Child partitions.

This workflow MUST never mutate Issue #44 or automatically merge a PR.
Only the verified source artifacts and parent allocation records can drive
READY_FOR_PARENT_REVIEW, which is not an approval to take an action.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from chatgpt_operation.github.actions_runtime import GitHubActionsTransport
from .agent_issue_artifact_download import authenticated_artifact_zip
from .agent_issue_attestation import verify_authenticated_child_receipt
from .agent_issue_partition import AgentIssueError
from .agent_issue_provision import read_live_parent_registry
from .agent_issue_runtime import reduce_verified_parent_children

REPOSITORY="HyungseonSong-plasma/chatgpt-operation"
TRUSTED_ACTOR="HyungseonSong-plasma"
LEGACY_CONTROLLER_ISSUE=44


def audit_all_agent_children(
    *, transport: GitHubActionsTransport,
    token: str,
    parent_issue: int,
) -> dict[str, Any]:
    if not token:
        raise AgentIssueError("authenticated GitHub read token required")
    if (
        type(parent_issue) is not int or parent_issue<=0
        or parent_issue==LEGACY_CONTROLLER_ISSUE
    ):
        raise AgentIssueError("approved active work Parent is required; not Issue #44")
    registry=read_live_parent_registry(
        transport,repository=REPOSITORY,parent_issue=parent_issue,
    )
    if not registry:
        return {
            "schema_version":1,"status":"NO_ALLOCATIONS",
            "children":[],"parent_mutation":None,
            "merge_authorized":False,
        }
    # The parent may only record references after separate semantic/policy
    # approval. For the read-only doc audit pilot, the independently sourced
    # run and artifact is the sole strict gate.
    def verify(receipt):
        return verify_authenticated_child_receipt(
            receipt,reader=transport,
            fetch_artifact_zip=lambda artifact_id: authenticated_artifact_zip(
                repository=REPOSITORY,artifact_id=artifact_id,token=token,
            ),
            repository=REPOSITORY,trusted_actor=TRUSTED_ACTOR,
        )
    result=reduce_verified_parent_children(
        transport,registry=registry,
        trusted_comment_authors=frozenset({"github-actions[bot]"}),
        live_gate_states={"attested-source":"PASS"},
        verify_source=verify,
    )
    # READY_FOR_PARENT_REVIEW never means semantic approval or automation.
    return {"schema_version":1,**result}


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",default="samuel-child-parent-audit.json")
    parser.add_argument("--parent",required=True,type=int)
    args=parser.parse_args()
    if not (
        os.environ.get("GITHUB_ACTIONS")=="true"
        and os.environ.get("GITHUB_REPOSITORY")==REPOSITORY
        and os.environ.get("GITHUB_REF")=="refs/heads/main"
        and os.environ.get("GITHUB_EVENT_NAME")=="workflow_dispatch"
        and os.environ.get("GITHUB_ACTOR")==TRUSTED_ACTOR
    ):
        raise AgentIssueError("read-only parent audit must be trusted manual mainline run")
    token=os.environ.get("GITHUB_TOKEN","")
    result=audit_all_agent_children(
        transport=GitHubActionsTransport(REPOSITORY,token),token=token,
        parent_issue=args.parent,
    )
    Path(args.output).write_text(
        json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8",
    )
    print("SAMUEL_CHILD_PARENT_AUDIT="+result["status"])
    return 0


if __name__=="__main__":
    raise SystemExit(main())
