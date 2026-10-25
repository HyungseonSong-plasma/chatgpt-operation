"""Fail-closed planning boundary for admitted Issue work."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import re

from .decisions import DecisionGuard, DecisionRegistry, GuardOutcome, ReasoningProposal
from .envelope import ReasoningEnvelope, build_reasoning_envelope
from .implementation import Capability, CapabilityStatus, ImplementationState


@dataclass(frozen=True)
class IssuePlanningResult:
    work_id: str
    outcome: GuardOutcome
    reason: str
    envelope: ReasoningEnvelope
    action_plan: dict[str, Any] | None = None


def verified_implementation_state() -> ImplementationState:
    state=ImplementationState()
    state.record(Capability("typed_issue_admission",CapabilityStatus.VERIFIED,("pr-84",)))
    state.record(Capability("admitted_issue_selection",CapabilityStatus.VERIFIED,("pr-85",)))
    state.record(Capability("native_github_executor",CapabilityStatus.VERIFIED,("issue-44-qualification",)))
    return state


def plan_admitted_issue(
    work: dict[str, Any],
    *,
    registry: DecisionRegistry,
    implementation: ImplementationState | None = None,
    cross_repository_verified: bool = False,
) -> IssuePlanningResult:
    work_id=work.get("work_id")
    native = (
        isinstance(work_id, str)
        and re.fullmatch(r"issue:[1-9][0-9]*", work_id) is not None
    )
    cross_repo = (
        isinstance(work_id, str)
        and re.fullmatch(
            r"github:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+:issue:[1-9][0-9]*",
            work_id,
        ) is not None
    )
    if not native and not (cross_repo and cross_repository_verified is True):
        raise ValueError("typed admitted issue work_id is required")
    if cross_repo:
        repository = work.get("repository")
        issue_number = work.get("issue_number")
        if (
            repository != work_id.split(":")[1]
            or type(issue_number) is not int
            or work_id != f"github:{repository}:issue:{issue_number}"
        ):
            raise ValueError("cross-repository issue scope mismatch")
    title=work.get("title")
    if not isinstance(title,str) or not title.strip():
        raise ValueError("admitted issue title is required")
    state=implementation or verified_implementation_state()
    envelope=build_reasoning_envelope(
        goal=title.strip(),
        observations=(str(work.get("body") or ""),),
        registry=registry,
        implementation=state,
        required_capabilities=("typed_issue_admission","admitted_issue_selection","native_github_executor"),
        allowed_reasoning_operations=("analyze","implement_gap","propose_revision"),
        required_outputs=("typed_proposal","action_plan"),
        escalation_constraints=("no_raw_issue_execution","explicit_revision_for_locked_decisions"),
    )
    # The deterministic bridge may classify the admitted work, but it must not
    # invent an executable mutation from free-form Issue text.
    proposal=ReasoningProposal(operation="analyze")
    guarded=DecisionGuard().validate(proposal,envelope.locked_decisions,envelope.implementation_gaps)
    return IssuePlanningResult(
        work_id=work_id,
        outcome=guarded.outcome,
        reason=guarded.reason,
        envelope=envelope,
        action_plan=None,
    )
