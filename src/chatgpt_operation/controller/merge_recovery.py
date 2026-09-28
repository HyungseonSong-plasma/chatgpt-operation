"""Deterministic recovery model for workload-owned pull requests rejected at merge."""
from __future__ import annotations

from typing import Any
import hashlib
from pathlib import Path

from .action_plan import ActionPlan
from .durable_state import can_rollover_state
from .research import ResearchState


def owned_workload_branches(state: ResearchState) -> set[str]:
    branches: set[str] = set()
    for item in state.action_queue.values():
        if not isinstance(item,dict):
            continue
        plan=item.get("plan")
        if not isinstance(plan,dict):
            continue
        payload=plan.get("payload")
        if not isinstance(payload,dict):
            continue
        target=payload.get("target")
        if not isinstance(target,dict):
            continue
        branch=target.get("branch")
        if isinstance(branch,str) and branch.startswith("samuel/"):
            branches.add(branch)
        if payload.get("action")=="create_pr":
            head=target.get("head")
            if isinstance(head,str) and head.startswith("samuel/"):
                branches.add(head)
    return branches


def rejected_merge_targets(state: ResearchState) -> set[tuple[int,str]]:
    """Exact PR/head pairs whose deterministic merge already failed closed."""
    rejected: set[tuple[int,str]] = set()
    for item in state.action_queue.values():
        if not isinstance(item,dict) or item.get("status")!="rejected":
            continue
        plan=item.get("plan")
        if not isinstance(plan,dict) or plan.get("executor")!="github_native":
            continue
        payload=plan.get("payload")
        if not isinstance(payload,dict) or payload.get("action")!="merge_pr":
            continue
        target=payload.get("target")
        if not isinstance(target,dict):
            continue
        number=target.get("number")
        head_sha=target.get("expected_head_sha")
        if (
            isinstance(number,int) and not isinstance(number,bool)
            and isinstance(head_sha,str) and head_sha
        ):
            rejected.add((number,head_sha))
    return rejected


def conflicted_workload_pull_requests(
    state: ResearchState,
    repository_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Project rejected exact-head merge attempts into bounded conflict evidence."""
    if repository_context is None:
        return []
    rejected=rejected_merge_targets(state)
    conflicts=[]
    for pr in repository_context.get("open_pull_requests",[]) or []:
        if not isinstance(pr,dict):
            continue
        key=(pr.get("number"),pr.get("head_sha"))
        if key not in rejected:
            continue
        head_ref=pr.get("head_ref")
        if not isinstance(head_ref,str) or not head_ref.startswith("samuel/"):
            continue
        conflicts.append({
            "number":pr["number"],
            "head_ref":head_ref,
            "head_sha":pr["head_sha"],
            "reason":"exact-head merge was rejected; branch must not be reused",
        })
    return sorted(conflicts,key=lambda item:item["number"])


def conflict_recovery_branch_name(
    state: ResearchState,
    repository_context: dict[str, Any] | None,
) -> str | None:
    if not conflicted_workload_pull_requests(state,repository_context):
        return None
    if repository_context is None:
        return None
    observed=str(repository_context.get("observed_head_sha") or "").strip()
    if len(observed)<12:
        return None
    work=state.research_id.replace(":","-").replace("/","-")
    return f"samuel/{work}-refresh-{observed[:12]}"


def conflict_recovery_branch_plan(
    state: ResearchState,
    repository_context: dict[str, Any] | None,
) -> ActionPlan | None:
    """Create a fresh workload branch from current main after exact merge rejection."""
    if repository_context is None or not can_rollover_state(state):
        return None
    name=conflict_recovery_branch_name(state,repository_context)
    if name is None:
        return None
    observed=str(repository_context.get("observed_head_sha") or "").strip()
    existing={
        str(item.get("ref") or "").removeprefix("refs/heads/")
        for item in repository_context.get("samuel_branches",[]) or []
        if isinstance(item,dict)
    }
    if name in existing:
        return None
    repository=str(repository_context.get("repository") or "").strip()
    if not repository:
        return None
    return ActionPlan.from_dict({
        "schema_version":1,
        "research_id":state.research_id,
        "stage":"implement",
        "executor":"repository_mutation",
        "payload":{
            "schema_version":1,
            "repository":repository,
            "resource":"branch",
            "action":"create",
            "target":{"name":name},
            "expected":{"absent":True},
            "desired":{"sha":observed},
        },
        "expected_observation":(
            f"Fresh conflict-recovery branch {name} exists at exact current main "
            f"head {observed}."
        ),
    })


def conflict_main_file_snapshots(
    state: ResearchState,
    repository_context: dict[str, Any] | None,
    *,
    root: str | Path = ".",
    max_files: int = 20,
    max_bytes_per_file: int = 20000,
) -> list[dict[str, Any]]:
    """Expose bounded current-main snapshots only for paths touched on conflicted branches."""
    conflicts=conflicted_workload_pull_requests(state,repository_context)
    conflict_branches={item["head_ref"] for item in conflicts}
    if not conflict_branches:
        return []
    paths=[]
    for item in state.action_queue.values():
        if not isinstance(item,dict):
            continue
        plan=item.get("plan")
        if not isinstance(plan,dict) or plan.get("executor")!="repository_mutation":
            continue
        payload=plan.get("payload")
        if not isinstance(payload,dict) or payload.get("resource")!="file":
            continue
        target=payload.get("target")
        if not isinstance(target,dict) or target.get("branch") not in conflict_branches:
            continue
        path=target.get("path")
        if isinstance(path,str) and path not in paths:
            paths.append(path)
    base=Path(root)
    snapshots=[]
    for path in paths[:max_files]:
        candidate=(base/path)
        try:
            data=candidate.read_bytes()
        except OSError:
            continue
        if len(data)>max_bytes_per_file:
            snapshots.append({
                "path":path,
                "exists":True,
                "content_omitted":True,
                "size":len(data),
            })
            continue
        header=f"blob {len(data)}\0".encode()
        snapshots.append({
            "path":path,
            "exists":True,
            "content_omitted":False,
            "git_blob_sha":hashlib.sha1(header+data).hexdigest(),
            "content":data.decode("utf-8"),
        })
    return snapshots
