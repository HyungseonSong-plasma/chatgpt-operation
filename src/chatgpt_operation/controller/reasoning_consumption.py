"""Deterministically consume a typed external reasoning submission."""
from __future__ import annotations
import copy
from dataclasses import dataclass
from typing import Any

from .decisions import DecisionRegistry, GuardOutcome
from .diagnostic import enqueue_suspended_action
from .issue_ingestion import transition_issue_status
from .issue_planning import plan_admitted_issue
from .issue_reasoning import compile_guarded_action
from .reasoning_submission import select_submission
from .research import ResearchState

@dataclass(frozen=True)
class ReasoningConsumption:
    outcome: str
    reason: str
    work: dict[str,dict[str,Any]]
    state: ResearchState
    action_id: str|None

def consume_reasoning_submission(
    comments:list[dict[str,Any]], work:dict[str,dict[str,Any]], work_id:str,
    *, registry:DecisionRegistry, state:ResearchState,
)->ReasoningConsumption:
    item=work.get(work_id)
    if item is None or item.get("status")!="reasoning_required":
        raise ValueError("work is not awaiting semantic reasoning")
    submission=select_submission(comments,work_id)
    if submission is None:
        return ReasoningConsumption("reasoning_required","typed reasoning submission not present",work,state,None)
    envelope=plan_admitted_issue(item,registry=registry).envelope
    outcome,plan,reason=compile_guarded_action(submission.proposal,envelope)
    if plan is None:
        lifecycle="revision_required" if outcome is GuardOutcome.REVISION_REQUIRED else "blocked"
        return ReasoningConsumption(outcome.value,reason,transition_issue_status(work,work_id,lifecycle),state,None)
    proposed=copy.deepcopy(state)
    enqueue_suspended_action(proposed,plan)
    return ReasoningConsumption(
        "planned",reason,transition_issue_status(work,work_id,"planned"),proposed,plan.idempotency_key
    )
