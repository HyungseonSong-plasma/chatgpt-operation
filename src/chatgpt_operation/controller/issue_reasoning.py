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
    blocker: dict[str, Any] | None = None
    progress: dict[str, Any] | None = None
    completion_claim: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "IssueReasoningProposal":
        allowed={
            "operation","decision_id","compatible_with_locked_decisions",
            "revision_requested","action_plan","blocker","progress","completion_claim",
        }
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
        if isinstance(plan,str) and plan.startswith(
            "__SAMUEL_INVALID_ACTION_PLAN_JSON__:"
        ):
            raise ValueError(plan.split(": ",1)[1])
        if plan is not None and not isinstance(plan,dict):
            raise ValueError("action_plan must be null or object")
        blocker=raw.get("blocker")
        if blocker is not None:
            if not isinstance(blocker,dict) or set(blocker)!={
                "capability","alternatives_considered","exhausted"
            }:
                raise ValueError("invalid blocker schema")
            capability=blocker.get("capability")
            alternatives=blocker.get("alternatives_considered")
            exhausted=blocker.get("exhausted")
            if not isinstance(capability,str) or not capability.strip():
                raise ValueError("blocker capability must be non-empty")
            if (
                not isinstance(alternatives,list)
                or any(not isinstance(item,str) or not item.strip() for item in alternatives)
            ):
                raise ValueError("blocker alternatives_considered must be strings")
            if not isinstance(exhausted,bool):
                raise ValueError("blocker exhausted must be boolean")
            blocker={
                "capability":capability.strip(),
                "alternatives_considered":[item.strip() for item in alternatives],
                "exhausted":exhausted,
            }
        progress=raw.get("progress")
        if progress is not None:
            if not isinstance(progress,dict) or set(progress)!={"criterion","rationale"}:
                raise ValueError("invalid progress schema")
            criterion=progress.get("criterion")
            rationale=progress.get("rationale")
            if not isinstance(criterion,str) or not criterion.strip():
                raise ValueError("progress criterion must be non-empty")
            if not isinstance(rationale,str) or not rationale.strip():
                raise ValueError("progress rationale must be non-empty")
            progress={"criterion":criterion.strip(),"rationale":rationale.strip()}
        completion_claim=raw.get("completion_claim")
        if completion_claim is not None:
            if not isinstance(completion_claim,dict) or set(completion_claim)!={"criteria"}:
                raise ValueError("invalid completion_claim schema")
            criteria=completion_claim.get("criteria")
            if not isinstance(criteria,list):
                raise ValueError("completion_claim criteria must be an array")
            normalized=[]
            for item in criteria:
                if not isinstance(item,dict) or set(item)!={"criterion","evidence_action_ids"}:
                    raise ValueError("invalid completion criterion schema")
                criterion=item.get("criterion")
                evidence=item.get("evidence_action_ids")
                if not isinstance(criterion,str) or not criterion.strip():
                    raise ValueError("completion criterion must be non-empty")
                if (
                    not isinstance(evidence,list)
                    or any(not isinstance(value,str) or not value.strip() for value in evidence)
                ):
                    raise ValueError("completion evidence_action_ids must be strings")
                normalized.append({
                    "criterion":criterion.strip(),
                    "evidence_action_ids":[value.strip() for value in evidence],
                })
            completion_claim={"criteria":normalized}
        return cls(
            operation,decision_id,compatible,revision,plan,blocker,
            progress,completion_claim,
        )


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
        if guard.outcome is GuardOutcome.CONTINUE and proposal.operation == "analyze":
            return GuardOutcome.CONTINUE,None,"analysis accepted; executable ActionPlan not yet produced"
        return GuardOutcome.BLOCKED,None,"typed reasoning produced no executable ActionPlan"
    plan=ActionPlan.from_dict(proposal.action_plan)
    if plan.requires_escalation():
        return GuardOutcome.BLOCKED,None,"ActionPlan requires explicit escalation"
    return guard.outcome,plan,guard.reason
