#!/usr/bin/env python3
"""One source-owned, manual, bounded foreign-Issue Controller cycle.

Records a durable ledger in source Issue #220, never target Issue #92.
No target writes; the separate reviewed codeQA execution policy is disabled.
Source issue-comment compare-before-write prevents blind overwrite.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from codeqa_governed_write import API, POLICY_FILE, SOURCE, TARGET, _identity_env
from chatgpt_operation.controller.cross_repository_issue_admission import (
    FOREIGN_CYCLE_WORKFLOW, CrossRepositoryAdmissionError, admit_cross_repository_issue,
)
from chatgpt_operation.controller.cross_repository_workflow import (
    ForeignWorkState, MARKER, decode_ledger, encode_ledger, select_authoritative_ledger,
    advance_reviewed_base,
)
from chatgpt_operation.controller.decisions import DecisionRegistry
from chatgpt_operation.controller.reasoning_provider import ReasoningProviderRegistry
from chatgpt_operation.controller.runtime import SamuelController, ControllerTrigger, TriggerKind

RESULT_FILE=Path("samuel-codeqa-foreign-cycle.json")

_SAFE_FOREIGN_ADMISSION_ERRORS = {
    "unverified Controller planning workflow": "SOURCE_WORKFLOW_NOT_ATTESTED",
    "workflow not approved for foreign issue admission": "UNAPPROVED_SOURCE_WORKFLOW",
    "target acceptance criteria absent": "TARGET_ACCEPTANCE_NOT_FOUND",
    "ambiguous acceptance section": "AMBIGUOUS_TARGET_ACCEPTANCE",
    "live GitHub Issue identity invalid": "ISSUE_IDENTITY_MISMATCH",
}


def safe_foreign_cycle_error(exc: Exception) -> str:
    """Constant-only diagnostics; never leak PAT, issue body or remote messages."""
    if isinstance(exc, CrossRepositoryAdmissionError):
        if str(exc).startswith("target identity/readback denied:"):
            return "TARGET_READBACK_DENIED"
        return _SAFE_FOREIGN_ADMISSION_ERRORS.get(str(exc), "FOREIGN_ADMISSION_REJECTED")
    return "OTHER_FOREIGN_CYCLE_ERROR"
EXECUTION_POLICY=Path("automation/samuel/codeqa-issue92-execution-candidate-v1.json")


class ForeignCycleError(ValueError):
    pass


def _comments(api: API) -> list[dict]:
    path="/repos/"+SOURCE+"/issues/220/comments"
    first=api.get(path+"?per_page=100&page=1")
    second=api.get(path+"?per_page=100&page=2")
    if not isinstance(first,list) or not isinstance(second,list) or second:
        raise ForeignCycleError("incomplete authoritative source issue comment inventory")
    return first


def _cas_write(api: API, before: list[dict], after: ForeignWorkState) -> dict:
    id_before,previous=select_authoritative_ledger(before)
    now=_comments(api)
    id_now,current=select_authoritative_ledger(now)
    if (id_before!=id_now
        or ((previous.to_dict() if previous else None)
            !=(current.to_dict() if current else None))):
        raise ForeignCycleError("foreign state changed after Controller snapshot")
    new_body=encode_ledger(after)
    root="/repos/"+SOURCE
    if previous is not None and encode_ledger(previous)==new_body:
        return {"operation":"NOOP","comment_id":id_now,"revision":after.revision}
    if id_now is None:
        created=api.call("POST",root+"/issues/220/comments",{"body":new_body})
        if type(created.get("id")) is not int:
            raise ForeignCycleError("source ledger creation not verified")
        number=created["id"]
        action="POST"
    else:
        updated=api.call("PATCH",root+"/issues/comments/"+str(id_now),{"body":new_body})
        if updated.get("id")!=id_now:
            raise ForeignCycleError("source ledger revision not verified")
        number=id_now
        action="PATCH"
    # Independently read back the exact body after write.
    check=api.get(root+"/issues/comments/"+str(number))
    if check.get("body")!=new_body:
        raise ForeignCycleError("durable ledger source readback mismatch")
    return {"operation":action,"comment_id":number,"revision":after.revision}


def run() -> dict:
    run_id,sha=_identity_env()
    policy=json.loads(POLICY_FILE.read_text(encoding="utf-8"))
    future_policy=json.loads(EXECUTION_POLICY.read_text(encoding="utf-8"))
    # Deliberately disallow target source-code mutation or provider auto-call
    # in this live StateKernel admission tranche.
    if future_policy.get("enabled") is not False:
        raise ForeignCycleError("manual admission lane must not activate target write policy")
    source=API(os.environ.get("GITHUB_TOKEN",""))
    target=API(os.environ.get("SAMUEL_CODEQA_WRITE_TOKEN",""))
    source_path="/repos/"+SOURCE
    target_path="/repos/"+TARGET
    snapshot,context=admit_cross_repository_issue(
        source_run=source.get(source_path+"/actions/runs/"+str(run_id)),
        source_run_id=run_id,controller_sha=sha,
        source_issue=source.get(source_path+"/issues/220"),
        target_issue=target.get(target_path+"/issues/92"),
        policy=policy,target_reader=target,
        workflow_filename=FOREIGN_CYCLE_WORKFLOW,
    )
    comments=_comments(source)
    _,before=select_authoritative_ledger(comments)
    decisions=DecisionRegistry.load("automation/samuel/decisions.json")
    controller=SamuelController(
        decisions=decisions,
        reasoning=ReasoningProviderRegistry(),
        reasoning_enabled=False,
    )
    cycle=controller.run_cycle(
        ControllerTrigger(kind=TriggerKind.WORKFLOW_DISPATCH,head_sha=sha,ref="main"),
        comments=[],pending=[],
        foreign_snapshot=snapshot,foreign_context=context,
        foreign_ledger=before,foreign_policy=future_policy,
    )
    planned=cycle.issue_planning
    if (not isinstance(planned,dict)
        or planned.get("work_id")!=snapshot.work_id
        or planned.get("execution_authorized") is not False):
        raise ForeignCycleError("foreign controller unexpectedly authorized execution")
    proposed=ForeignWorkState.from_dict(planned["foreign_ledger"])
    approved_rollover=os.environ.get("SAMUEL_APPROVE_BASE_ROLLOVER")=="true"
    if approved_rollover:
        proposed=advance_reviewed_base(proposed,snapshot)
    proof=_cas_write(source,comments,proposed)
    return {
        "schema_version":1,"status":"FOREIGN_LEDGER_CYCLE_VERIFIED",
        "work_id":snapshot.work_id,"source_run_id":run_id,
        "controller_sha":sha,"target_base_sha":snapshot.target_base_sha,
        "issue_body_sha256":snapshot.issue_body_sha256,
        "revision":proposed.revision,"phase":proposed.phase,
        "ledger_write":proof,"action_plan":proposed.action_plan,
        "target_mutation_performed":False,"merge_authorized":False,
        "execution_policy_enabled":False,
        "reviewed_base_transition":approved_rollover,
    }


def main() -> int:
    try:
        result=run()
        rc=0
    except Exception as exc:
        result={
            "schema_version":1,"status":"HARD_STOP",
            "error_type":type(exc).__name__,
            "error_code":safe_foreign_cycle_error(exc),
            "target_mutation_performed":False,"merge_authorized":False,
        }
        rc=2
    RESULT_FILE.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print("SAMUEL_FOREIGN_CYCLE="+result["status"])
    return rc


if __name__=="__main__":
    raise SystemExit(main())
