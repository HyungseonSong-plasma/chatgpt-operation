"""Durable, replay-safe submission boundary for external semantic reasoning."""
from __future__ import annotations
from dataclasses import dataclass
import json
from typing import Any

from .issue_reasoning import IssueReasoningProposal

REASONING_SUBMISSION_MARKER="<!-- samuel-reasoning-submission -->"
SCHEMA_VERSION=1

class ReasoningSubmissionError(ValueError):
    pass

@dataclass(frozen=True)
class ReasoningSubmission:
    work_id: str
    proposal: IssueReasoningProposal

    @classmethod
    def from_dict(cls, raw: dict[str,Any]) -> "ReasoningSubmission":
        if set(raw)!={"schema_version","work_id","proposal"}:
            raise ReasoningSubmissionError("invalid reasoning submission fields")
        if raw["schema_version"] != SCHEMA_VERSION:
            raise ReasoningSubmissionError("unsupported reasoning submission schema")
        work_id=raw["work_id"]
        if not isinstance(work_id,str) or not work_id.startswith("issue:"):
            raise ReasoningSubmissionError("typed Issue work_id required")
        return cls(work_id,IssueReasoningProposal.from_dict(raw["proposal"]))

def encode_submission(submission: ReasoningSubmission) -> str:
    p=submission.proposal
    payload={
        "schema_version":SCHEMA_VERSION,
        "work_id":submission.work_id,
        "proposal":{
            "operation":p.operation,
            "decision_id":p.decision_id,
            "compatible_with_locked_decisions":p.compatible_with_locked_decisions,
            "revision_requested":p.revision_requested,
            "action_plan":p.action_plan,
        },
    }
    return REASONING_SUBMISSION_MARKER+"\n~~~json\n"+json.dumps(payload,sort_keys=True,separators=(",",":"))+"\n~~~"

def decode_submission(body: str) -> ReasoningSubmission:
    if REASONING_SUBMISSION_MARKER not in body:
        raise ReasoningSubmissionError("reasoning submission marker missing")
    start=body.find("~~~json"); end=body.find("~~~",start+7)
    if start<0 or end<0:
        raise ReasoningSubmissionError("reasoning submission JSON fence missing")
    return ReasoningSubmission.from_dict(json.loads(body[start+7:end].strip()))

def select_submission(comments: list[dict[str,Any]], work_id: str) -> ReasoningSubmission|None:
    matches=[]
    for comment in comments:
        body=str(comment.get("body",""))
        if REASONING_SUBMISSION_MARKER not in body:
            continue
        item=decode_submission(body)
        if item.work_id==work_id:
            matches.append(item)
    if len(matches)>1:
        raise ReasoningSubmissionError("multiple reasoning submissions for work")
    return None if not matches else matches[0]
