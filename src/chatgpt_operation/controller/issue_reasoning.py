"""Typed semantic proposal and guarded ActionPlan compilation for Issue work."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from .action_plan import ActionPlan
from .decisions import DecisionGuard, GuardOutcome, ReasoningProposal
from .envelope import ReasoningEnvelope
from .reasoning import ReasoningNodeError, ReasoningRequest, StructuredReasoningNode


@dataclass(frozen=True)
class IssueReasoningProposal:
    operation: str
    decision_id: str | None
    compatible_with_locked_decisions: bool
    revision_requested: bool
    action_plan: dict[str, Any] | None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "IssueReasoningProposal":
        allowed={"operation","decision_id","compatible_with_locked_decisions","revision_requested","action_plan"}
        if set(raw)-allowed:
            raise ValueError("unknown Issue reasoning proposal fields")
        operation=raw.get("operation")
        if operation not in {"analyze","implement_gap","propose_revision"}:
            raise ValueError("unsupported reasoning operation")
        compatible=raw.get("compatible_with_locked_decisions")
        revision=raw.get("revision_requested")
        if not isinstance(compatible,bool) or not isinstance(revision,bool):
            raise ValueError("compatibility and revision flags must be boolean")
        decision_id=raw.get("decision_id")
        if decision_id is not None and (not isinstance(decision_id,str) or not decision_id.strip()):
            raise ValueError("decision_id must be null or non-empty")
        plan=raw.get("action_plan")
        if plan is not None and not isinstance(plan,dict):
            raise ValueError("action_plan must be null or object")
        return cls(operation,decision_id,compatible,revision,plan)


def issue_reasoning_node(*,max_attempts:int=2)->StructuredReasoningNode[IssueReasoningProposal]:
    return StructuredReasoningNode(parser=IssueReasoningProposal.from_dict,max_attempts=max_attempts)


def compile_guarded_action(
    proposal: IssueReasoningProposal,
    envelope: ReasoningEnvelope,
) -> tuple[GuardOutcome,ActionPlan|None,str]:
    guard=DecisionGuard().validate(
        ReasoningProposal(
            operation=proposal.operation,
            decision_id=proposal.decision_id,
            compatible_with_locked_decisions=proposal.compatible_with_locked_decisions,
            revision_requested=proposal.revision_requested,
        ),
        envelope.locked_decisions,
        envelope.implementation_gaps,
    )
    if guard.outcome not in {GuardOutcome.CONTINUE,GuardOutcome.IMPLEMENT_GAP}:
        return guard.outcome,None,guard.reason
    if proposal.action_plan is None:
        return GuardOutcome.BLOCKED,None,"typed reasoning produced no executable ActionPlan"
    plan=ActionPlan.from_dict(proposal.action_plan)
    if plan.requires_escalation():
        return GuardOutcome.BLOCKED,None,"ActionPlan requires explicit escalation"
    return guard.outcome,plan,guard.reason
