"""Durable trusted-validation lifecycle for Samuel-created pull requests."""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from .action_lifecycle import ActionLifecycle, DispatchIntent
from .action_plan import ActionPlan, ExecutorKind
from .research import ResearchState


class TrustedValidationError(ValueError):
    pass


def _validation_id(
    *, action_id: str, pr_number: int, head_sha: str, head_branch: str
) -> str:
    semantic={
        "action_id":action_id,
        "pr_number":pr_number,
        "head_sha":head_sha,
        "head_branch":head_branch,
    }
    return hashlib.sha256(
        json.dumps(semantic,sort_keys=True,separators=(",",":")).encode()
    ).hexdigest()


def _create_pr_plan(state: ResearchState, action_id: str) -> ActionPlan:
    item=state.action_queue.get(action_id)
    if not isinstance(item,dict) or item.get("status") != ActionLifecycle.COMPLETE.value:
        raise TrustedValidationError("trusted validation source action is not complete")
    plan=ActionPlan.from_dict(item.get("plan"))
    if (
        plan.executor is not ExecutorKind.GITHUB_NATIVE
        or plan.payload.get("action") != "create_pr"
    ):
        raise TrustedValidationError("trusted validation source is not create_pr")
    return plan


def _owned_open_prs(
    state: ResearchState,
    repository_context: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    raw=repository_context.get("open_pull_requests") or []
    if not isinstance(raw,list):
        raise TrustedValidationError("repository open_pull_requests must be an array")
    result=[]
    for action_id,item in state.action_queue.items():
        if not isinstance(item,dict) or item.get("status") != ActionLifecycle.COMPLETE.value:
            continue
        try:
            plan=ActionPlan.from_dict(item.get("plan"))
        except (TypeError,ValueError):
            continue
        if (
            plan.executor is not ExecutorKind.GITHUB_NATIVE
            or plan.payload.get("action") != "create_pr"
        ):
            continue
        target=plan.payload.get("target")
        if not isinstance(target,dict):
            continue
        head=target.get("head")
        base=target.get("base")
        if not isinstance(head,str) or not isinstance(base,str):
            continue
        matches=[
            pr for pr in raw
            if isinstance(pr,dict)
            and pr.get("state")=="open"
            and pr.get("head_ref")==head
            and pr.get("base_ref")==base
            and isinstance(pr.get("number"),int)
            and isinstance(pr.get("head_sha"),str)
            and bool(pr.get("head_sha"))
        ]
        if len(matches)>1:
            raise TrustedValidationError(
                "multiple open pull requests match one completed create_pr action"
            )
        if matches:
            result.append((action_id,matches[0]))
    return result


def select_trusted_validation_work(
    state: ResearchState,
    repository_context: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]] | None:
    """Return deterministic validation work only for an owned PR lacking CI evidence."""
    if repository_context is None:
        return None
    candidates=[]
    for action_id,pr in _owned_open_prs(state,repository_context):
        ci_state=str(pr.get("ci_state") or "unknown")
        if ci_state in {"success","failure","pending"}:
            continue
        if ci_state != "unknown":
            raise TrustedValidationError("unsupported PR ci_state: "+ci_state)
        item=state.action_queue[action_id]
        current=item.get("trusted_validation")
        head_sha=str(pr["head_sha"])
        if isinstance(current,dict) and current.get("head_sha")==head_sha:
            status=current.get("status")
            if status==ActionLifecycle.DISPATCH_INTENT.value:
                candidates.append(("trusted_validation_intent",{
                    "action_id":action_id,
                    "validation":copy.deepcopy(current),
                    "pr":copy.deepcopy(pr),
                }))
                continue
            if status==ActionLifecycle.DISPATCHED.value:
                candidates.append(("trusted_validation_wait",{
                    "action_id":action_id,
                    "validation":copy.deepcopy(current),
                    "pr":copy.deepcopy(pr),
                }))
                continue
            raise TrustedValidationError(
                "trusted validation has unsupported lifecycle status"
            )
        candidates.append(("trusted_validation",{
            "action_id":action_id,
            "pr":copy.deepcopy(pr),
        }))
    if len(candidates)>1:
        raise TrustedValidationError(
            "multiple owned pull requests require trusted validation"
        )
    return None if not candidates else candidates[0]


def record_trusted_validation_intent(
    state: ResearchState,
    action_id: str,
    *,
    pr_number: int,
    head_sha: str,
    head_branch: str,
    base_ref: str,
    workflow: str,
    ref: str,
    requested_at: str,
    expected_head_sha: str,
) -> dict[str, Any]:
    """Persist one exact-head validation intent before dispatch."""
    plan=_create_pr_plan(state,action_id)
    target=plan.payload.get("target")
    if not isinstance(pr_number,int) or isinstance(pr_number,bool) or pr_number < 1:
        raise TrustedValidationError("trusted validation pr_number must be positive")
    for name,value in {
        "head_sha":head_sha,
        "head_branch":head_branch,
        "base_ref":base_ref,
        "workflow":workflow,
        "ref":ref,
        "requested_at":requested_at,
        "expected_head_sha":expected_head_sha,
    }.items():
        if not isinstance(value,str) or not value.strip():
            raise TrustedValidationError(name+" must be non-empty")
    if target.get("head") != head_branch or target.get("base") != base_ref:
        raise TrustedValidationError(
            "trusted validation PR identity differs from create_pr plan"
        )
    item=state.action_queue[action_id]
    old=item.get("trusted_validation")
    if isinstance(old,dict):
        if old.get("head_sha")==head_sha:
            if old.get("status")==ActionLifecycle.DISPATCH_INTENT.value:
                return copy.deepcopy(old)
            raise TrustedValidationError(
                "trusted validation intent already exists for exact head"
            )
        history=item.setdefault("trusted_validation_history",[])
        if not isinstance(history,list):
            raise TrustedValidationError("trusted validation history is invalid")
        history.append(copy.deepcopy(old))
    validation_id=_validation_id(
        action_id=action_id,
        pr_number=pr_number,
        head_sha=head_sha,
        head_branch=head_branch,
    )
    intent=DispatchIntent.from_dict({
        "schema_version":2,
        "action_id":validation_id,
        "research_id":state.research_id,
        "workflow":workflow,
        "ref":ref,
        "requested_at":requested_at,
        "state_revision":state.revision+1,
        "expected_head_sha":expected_head_sha,
    })
    record={
        "schema_version":1,
        "status":ActionLifecycle.DISPATCH_INTENT.value,
        "validation_id":validation_id,
        "pr_number":pr_number,
        "head_sha":head_sha,
        "head_branch":head_branch,
        "base_ref":base_ref,
        "intent":intent.to_dict(),
    }
    item["trusted_validation"]=record
    state.revision+=1
    return copy.deepcopy(record)


def record_trusted_validation_dispatch(
    state: ResearchState,
    action_id: str,
    receipt: dict[str, Any],
) -> None:
    item=state.action_queue.get(action_id)
    record=None if not isinstance(item,dict) else item.get("trusted_validation")
    if (
        not isinstance(record,dict)
        or record.get("status") != ActionLifecycle.DISPATCH_INTENT.value
    ):
        raise TrustedValidationError(
            "trusted validation dispatch has no durable intent"
        )
    intent=DispatchIntent.from_dict(record.get("intent"))
    if not isinstance(receipt,dict):
        raise TrustedValidationError("trusted validation receipt must be an object")
    correlation=receipt.get("correlation_id")
    if correlation != record.get("validation_id"):
        raise TrustedValidationError("trusted validation receipt correlation mismatch")
    run_id=receipt.get("workflow_run_id")
    if not isinstance(run_id,int) or isinstance(run_id,bool) or run_id < 1:
        raise TrustedValidationError(
            "trusted validation receipt has no authoritative workflow_run_id"
        )
    if receipt.get("ref") != intent.ref:
        raise TrustedValidationError("trusted validation receipt ref mismatch")
    workflow_path=str(receipt.get("workflow_path") or "")
    if workflow_path and workflow_path.rsplit("/",1)[-1] != intent.workflow:
        raise TrustedValidationError("trusted validation receipt workflow mismatch")
    record["status"]=ActionLifecycle.DISPATCHED.value
    record["receipt"]=copy.deepcopy(receipt)
    state.revision+=1


def resume_trusted_validation_intent(
    state: ResearchState,
    action_id: str,
) -> tuple[dict[str, Any], DispatchIntent]:
    _create_pr_plan(state,action_id)
    record=state.action_queue[action_id].get("trusted_validation")
    if (
        not isinstance(record,dict)
        or record.get("status") != ActionLifecycle.DISPATCH_INTENT.value
    ):
        raise TrustedValidationError("trusted validation intent is not resumable")
    return copy.deepcopy(record),DispatchIntent.from_dict(record.get("intent"))


def resume_dispatched_trusted_validation(
    state: ResearchState,
    action_id: str,
) -> tuple[dict[str, Any], DispatchIntent, dict[str, Any]]:
    _create_pr_plan(state,action_id)
    record=state.action_queue[action_id].get("trusted_validation")
    if (
        not isinstance(record,dict)
        or record.get("status") != ActionLifecycle.DISPATCHED.value
    ):
        raise TrustedValidationError("trusted validation dispatch is not resumable")
    receipt=record.get("receipt")
    if not isinstance(receipt,dict):
        raise TrustedValidationError("trusted validation dispatch has no receipt")
    return (
        copy.deepcopy(record),
        DispatchIntent.from_dict(record.get("intent")),
        copy.deepcopy(receipt),
    )
