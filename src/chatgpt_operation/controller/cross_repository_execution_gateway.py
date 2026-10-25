"""Cross-repository extension of the existing Samuel Actions ExecutionGateway.

Requires a distinct target-scoped transport and a separately reviewed policy.
Dispatch alone never certifies a target code change. A target-owned execution
receipt, exact Draft PR HEAD and independent CI are additional conditions.
The target executor workflow is not yet deployed; default policy DENIES it.
"""
from __future__ import annotations

from dataclasses import replace
import json
from typing import Any, Mapping

from .action_plan import ActionPlan
from .cross_repository_workflow import (
    EXECUTOR_WORKFLOW, ForeignWorkError, ForeignWorkState,
    TARGET, record_dispatch, observe_pr_ci, validate_foreign_plan,
)
from chatgpt_operation.github.actions_runtime import (
    ActionsTransport, dispatch_workflow, observe_dispatch_once,
)


REQUIRED_CI = (
    "layout.yml",
    "pinned-python-sdk.yml",
    "self-audit.yml",
    "semgrep-gate.yml",
)


def dispatch_foreign_action(
    state: ForeignWorkState,
    *,
    target_transport: ActionsTransport,
    execution_policy: Mapping[str, Any],
    expected_revision: int,
) -> ForeignWorkState:
    if state.phase != "dispatch_ready" or state.revision != expected_revision:
        raise ForeignWorkError("stale or unauthorized foreign dispatch")
    if getattr(target_transport, "repository", None) != TARGET:
        raise ForeignWorkError("transport is not bound to exact codeQA repository")
    if state.action_plan is None or state.action_id is None:
        raise ForeignWorkError("foreign executable plan absent")
    plan=ActionPlan.from_dict(state.action_plan)
    validate_foreign_plan(plan,execution_policy)
    if plan.idempotency_key != state.action_id:
        raise ForeignWorkError("action identity changed after review")
    if execution_policy.get("base_sha") != state.base_sha:
        raise ForeignWorkError("stale separately approved codeQA base")
    current=target_transport.get("/git/ref/heads/main")
    if (not isinstance(current,dict)
        or current.get("object",{}).get("sha") != state.base_sha):
        raise ForeignWorkError("target HEAD advanced before execution")
    workflow=target_transport.get("/actions/workflows/"+EXECUTOR_WORKFLOW)
    if (not isinstance(workflow,dict)
        or workflow.get("state") != "active"
        or workflow.get("path") != ".github/workflows/"+EXECUTOR_WORKFLOW):
        raise ForeignWorkError("reviewed codeQA executor workflow not installed")
    # No new token/permission comes from the plan, Issues or source comments.
    # The target-bound credential is supplied by the trusted host boundary.
    receipt=dispatch_workflow(
        target_transport,workflow=EXECUTOR_WORKFLOW,ref="main",
        correlation_id=state.action_id,
        correlation_input="samuel_action_id",
        inputs={
            "source_run_id":str(state.admission_run_id),
            "base_sha":state.base_sha,
            "plan_json":json.dumps(state.action_plan,sort_keys=True,separators=(",",":")),
        },
        correlation_run_name_prefix="samuel-codeqa-issue92:",
    )
    return record_dispatch(state,receipt,expected_revision=expected_revision)


def observe_foreign_execution(
    state: ForeignWorkState,
    *,
    target_transport: ActionsTransport,
) -> ForeignWorkState:
    if (state.phase not in {"dispatched","ci_pending"}
        or state.receipt is None
        or getattr(target_transport,"repository",None)!=TARGET):
        raise ForeignWorkError("target execution observation scope invalid")
    result=observe_dispatch_once(
        target_transport,state.receipt,expected_head_sha=state.base_sha
    )
    status=result.get("status")
    if status in {"MATCHED_ACTIVE","PENDING_VISIBILITY","OBSERVATION_INCOMPLETE"}:
        return state
    if status=="MATCHED_TERMINAL" and result.get("conclusion")=="success":
        return replace(state,revision=state.revision+1,phase="ci_pending")
    if status in {"MATCHED_TERMINAL","BOUND_RUN_IDENTITY_MISMATCH"}:
        return replace(state,revision=state.revision+1,
                       phase="revision_required",
                       last_failure="TARGET_EXECUTION_NOT_SUCCESS")
    raise ForeignWorkError("uncorrelated or invalid target workflow observation")


def inspect_foreign_pr_ci(
    state: ForeignWorkState,
    *,
    target_transport: ActionsTransport,
    target_receipt: Mapping[str,Any],
    required_workflows: tuple[str,...]=REQUIRED_CI,
) -> ForeignWorkState:
    if state.phase!="ci_pending" or getattr(target_transport,"repository",None)!=TARGET:
        raise ForeignWorkError("target CI inspection requires successful dispatch")
    if (not isinstance(target_receipt,dict)
        or target_receipt.get("status")!="EXECUTED_DRAFT_PR"
        or target_receipt.get("work_id")!=state.work_id
        or target_receipt.get("action_id")!=state.action_id
        or target_receipt.get("base_sha")!=state.base_sha
        or target_receipt.get("source_run_id")!=state.admission_run_id
        or target_receipt.get("merge_performed") is not False):
        raise ForeignWorkError("target-owned execution receipt missing or mismatched")
    pr_number=target_receipt.get("pr_number")
    if type(pr_number) is not int or pr_number<=0:
        raise ForeignWorkError("target receipt missing PR identity")
    pr=target_transport.get("/pulls/"+str(pr_number))
    if (not isinstance(pr,dict)
        or pr.get("number")!=pr_number
        or pr.get("head",{}).get("sha") != target_receipt.get("head_sha")):
        raise ForeignWorkError("PR HEAD differs from trusted target receipt")
    all_runs=target_transport.get("/actions/runs",query={
        "head_sha":target_receipt["head_sha"],"per_page":"100",
    })
    if not isinstance(all_runs,dict) or not isinstance(all_runs.get("workflow_runs"),list):
        raise ForeignWorkError("target CI run enumeration not complete")
    return observe_pr_ci(state,pr=pr,runs=all_runs["workflow_runs"],
                         required_workflows=required_workflows)
