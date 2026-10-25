#!/usr/bin/env python3
"""Ingest owner-posted scheduled ChatGPT proposal into a review-only Ledger.

This script does NOT call the OpenAI API, create codeQA branches, or dispatch
a target workflow. Source GitHub Actions issues:write is used only to CAS
update the existing source Issue #220 review Ledger.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from codeqa_governed_write import API, SOURCE, TARGET
from samuel_codeqa_foreign_cycle import (
    EXECUTION_POLICY, _cas_write, _comments, _target_file_is_absent,
)
from chatgpt_operation.controller.chatgpt_scheduled_proposal import (
    PROPOSAL_PATH, ScheduledProposalError, review_owner_proposal,
)
from chatgpt_operation.controller.cross_repository_workflow import (
    select_authoritative_ledger,
)

RECEIPT_FILE=Path("samuel-chatgpt-proposal-receipt.json")


def run() -> dict:
    env=os.environ
    if (
        env.get("GITHUB_ACTIONS") != "true"
        or env.get("GITHUB_REPOSITORY") != SOURCE
        or env.get("GITHUB_EVENT_NAME") != "issue_comment"
        or env.get("GITHUB_REF") != "refs/heads/main"
        or env.get("GITHUB_ACTOR") != "HyungseonSong-plasma"
        or not env.get("GITHUB_RUN_ID", "").isdigit()
    ):
        raise ScheduledProposalError("trusted owner issue_comment environment invalid")
    event=json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text())
    comment=event.get("comment")
    if (
        event.get("action") != "created"
        or event.get("issue",{}).get("number") != 220
        or event.get("repository",{}).get("full_name") != SOURCE
        or event.get("sender",{}).get("login") != "HyungseonSong-plasma"
        or not isinstance(comment,dict)
        or type(comment.get("id")) is not int
    ):
        raise ScheduledProposalError("untrusted event comment or issue identity")
    source=API(env.get("GITHUB_TOKEN",""))
    target=API(env.get("SAMUEL_CODEQA_WRITE_TOKEN",""))
    sr="/repos/"+SOURCE
    tr="/repos/"+TARGET
    live_comment=source.get(sr+"/issues/comments/"+str(comment["id"]))
    if live_comment.get("body") != comment.get("body"):
        raise ScheduledProposalError("event body differs from live GitHub comment")
    source_run=source.get(sr+"/actions/runs/"+env["GITHUB_RUN_ID"])
    if source_run.get("id")!=int(env["GITHUB_RUN_ID"]):
        raise ScheduledProposalError("source workflow run ID does not match event")
    source_sha=source.get(sr+"/git/ref/heads/main").get("object",{}).get("sha")
    if source_sha!=env.get("GITHUB_SHA"):
        raise ScheduledProposalError("source main changed before comment processing")
    target_repo=target.get(tr)
    if (
        target_repo.get("id")!=1424293498
        or target_repo.get("full_name")!=TARGET
        or target_repo.get("default_branch")!="main"
    ):
        raise ScheduledProposalError("target repository identity invalid")
    target_main_sha=target.get(tr+"/git/ref/heads/main").get("object",{}).get("sha")
    if not isinstance(target_main_sha,str) or len(target_main_sha)!=40:
        raise ScheduledProposalError("target HEAD not authenticated")
    comments=_comments(source)
    _,previous=select_authoritative_ledger(comments)
    policy=json.loads(EXECUTION_POLICY.read_text())
    approved=review_owner_proposal(
        source_run=source_run,
        source_main_sha=source_sha,
        source_issue=source.get(sr+"/issues/220"),
        source_comment=live_comment,
        event_comment_id=comment["id"],
        previous=previous,
        target_issue=target.get(tr+"/issues/92"),
        target_main_sha=target_main_sha,
        policy=policy,
        candidate_absent=_target_file_is_absent(target,target_main_sha),
    )
    result=_cas_write(source,comments,approved)
    return {
        "schema_version":1,
        "status":"CHATGPT_PROPOSAL_REVIEW_REQUIRED",
        "source_run_id":int(env["GITHUB_RUN_ID"]),
        "source_sha":source_sha,
        "source_comment_id":comment["id"],
        "ledger_comment_id":result["comment_id"],
        "ledger_revision":approved.revision,
        "target_base_sha":target_main_sha,
        "work_id":approved.work_id,
        "action_id":approved.action_id,
        "review_required":True,
        "target_mutation_performed":False,
        "merge_authorized":False,
    }


def main() -> int:
    try:
        result=run()
        code=0
    except Exception as exc:
        result={
            "schema_version":1,
            "status":"HARD_STOP",
            "error_type":type(exc).__name__,
            "error_code":"OWNER_PROPOSAL_INGRESS_DENIED",
            "target_mutation_performed":False,
            "merge_authorized":False,
        }
        code=2
    RECEIPT_FILE.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("SAMUEL_CHATGPT_ISSUE92="+result["status"])
    return code


if __name__=="__main__":
    raise SystemExit(main())
