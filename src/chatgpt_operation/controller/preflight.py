"""Deterministic preflight for semantic ActionPlans before dispatch."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from .action_plan import ActionPlan, ExecutorKind
from .research import ResearchState


@dataclass(frozen=True)
class PreflightFailure:
    code: str
    evidence: dict[str, Any]
    repair_hint: str

    def as_validation_error(self) -> str:
        return "PREFLIGHT_REJECTED " + json.dumps(
            {
                "code": self.code,
                "evidence": self.evidence,
                "repair_hint": self.repair_hint,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


def extract_acceptance_criteria(body: str) -> tuple[str, ...]:
    """Extract top-level bullets under a markdown ## Acceptance section."""
    if not isinstance(body, str) or not body.strip():
        return ()
    lines=body.splitlines()
    active=False
    criteria=[]
    for raw in lines:
        line=raw.strip()
        if line.startswith("## "):
            if active:
                break
            active=line.lower()=="## acceptance"
            continue
        if not active:
            continue
        if line.startswith("### "):
            continue
        match=re.match(r"^-\s+(?:\[[ xX]\]\s+)?(.+?)\s*$", line)
        if match:
            criterion=match.group(1).strip()
            if criterion and criterion not in criteria:
                criteria.append(criterion)
    return tuple(criteria)


def verified_evidence_ids(state: ResearchState) -> set[str]:
    """Return terminal-success evidence already provenance-checked by the lifecycle."""
    result=set()
    for action_id,item in state.action_queue.items():
        if not isinstance(item,dict) or item.get("status")!="complete":
            continue
        completion=item.get("completion_result")
        if (
            isinstance(completion,dict)
            and completion.get("status") in {"pass","noop"}
        ):
            result.add(action_id)
            continue
        # Legacy durable states stored terminal results separately.
        execution=state.execution_results.get(action_id)
        if isinstance(execution,dict) and execution.get("status") in {"pass","noop"}:
            result.add(action_id)
    for item in state.inherited_evidence:
        if not isinstance(item,dict):
            continue
        if item.get("verified_status") not in {"pass","noop"}:
            continue
        source=item.get("source_action_id")
        if isinstance(source,str) and source:
            result.add(source)
    return result


def integrated_acceptance_evidence(
    state: ResearchState,
) -> dict[str, tuple[str, ...]]:
    """Map acceptance criteria to progress evidence integrated through a merged PR.

    A progress claim may legitimately need several actions while a branch is under
    construction. It becomes durable integrated evidence only after that workload
    branch is carried by a provenance-verified create_pr action whose PR is later
    merged by a provenance-verified merge_pr action.
    """
    verified=verified_evidence_ids(state)
    merged_pr_numbers:set[int]=set()

    for action_id,item in state.action_queue.items():
        if action_id not in verified or not isinstance(item,dict):
            continue
        plan=item.get("plan")
        payload=plan.get("payload") if isinstance(plan,dict) else None
        target=payload.get("target") if isinstance(payload,dict) else None
        completion=item.get("completion_result")
        details=completion.get("details") if isinstance(completion,dict) else None
        after=details.get("after") if isinstance(details,dict) else None
        if (
            isinstance(payload,dict)
            and payload.get("action")=="merge_pr"
            and isinstance(target,dict)
            and isinstance(target.get("number"),int)
            and isinstance(after,dict)
            and after.get("merged") is True
        ):
            merged_pr_numbers.add(target["number"])

    merged_heads:set[str]=set()
    for action_id,item in state.action_queue.items():
        if action_id not in verified or not isinstance(item,dict):
            continue
        plan=item.get("plan")
        payload=plan.get("payload") if isinstance(plan,dict) else None
        target=payload.get("target") if isinstance(payload,dict) else None
        completion=item.get("completion_result")
        details=completion.get("details") if isinstance(completion,dict) else None
        after=details.get("after") if isinstance(details,dict) else None
        if (
            isinstance(payload,dict)
            and payload.get("action")=="create_pr"
            and isinstance(target,dict)
            and isinstance(after,dict)
            and after.get("pr_number") in merged_pr_numbers
        ):
            head=target.get("head")
            if isinstance(head,str) and head:
                merged_heads.add(head)

    by_criterion:dict[str,set[str]]={}
    for action_id,item in state.action_queue.items():
        if action_id not in verified or not isinstance(item,dict):
            continue
        progress=item.get("progress")
        if not isinstance(progress,dict):
            continue
        criterion=progress.get("criterion")
        if not isinstance(criterion,str) or not criterion:
            continue
        plan=item.get("plan")
        payload=plan.get("payload") if isinstance(plan,dict) else None
        target=payload.get("target") if isinstance(payload,dict) else None
        if not isinstance(payload,dict) or not isinstance(target,dict):
            continue

        action=payload.get("action")
        resource=payload.get("resource")
        integrated=False
        if action=="create_pr":
            completion=item.get("completion_result")
            details=completion.get("details") if isinstance(completion,dict) else None
            after=details.get("after") if isinstance(details,dict) else None
            integrated=isinstance(after,dict) and after.get("pr_number") in merged_pr_numbers
        elif action=="merge_pr":
            integrated=target.get("number") in merged_pr_numbers
        elif resource=="file":
            integrated=target.get("branch") in merged_heads
        elif resource=="branch" and action=="create":
            # Creating a branch is preparation, not acceptance evidence by itself.
            integrated=False

        if integrated:
            by_criterion.setdefault(criterion,set()).add(action_id)

    return {
        criterion:tuple(sorted(action_ids))
        for criterion,action_ids in sorted(by_criterion.items())
    }


def _samuel_branch_heads(repository_context: dict[str, Any]) -> dict[str,str]:
    branches={}
    for item in repository_context.get("samuel_branches") or []:
        if not isinstance(item,dict):
            continue
        ref=str(item.get("ref") or "")
        sha=str(item.get("head_sha") or "")
        prefix="refs/heads/"
        if ref.startswith(prefix) and sha:
            branches[ref[len(prefix):]]=sha
    return branches


def _is_close_issue(plan: ActionPlan) -> bool:
    return (
        plan.executor is ExecutorKind.GITHUB_NATIVE
        and plan.payload.get("action")=="close_issue"
    )


def _preflight_repository_target(
    plan: ActionPlan,
    repository_context: dict[str, Any],
) -> PreflightFailure | None:
    if plan.executor is not ExecutorKind.REPOSITORY_MUTATION:
        return None
    payload=plan.payload
    resource=payload.get("resource")
    action=payload.get("action")
    target=payload.get("target")
    if not isinstance(target,dict):
        return PreflightFailure(
            "invalid_target",
            {"resource":resource,"action":action},
            "produce a repository mutation with a typed target",
        )
    observed=str(repository_context.get("observed_head_sha") or "")
    branches=_samuel_branch_heads(repository_context)
    if resource=="branch" and action=="create":
        desired=payload.get("desired")
        desired_sha=desired.get("sha") if isinstance(desired,dict) else None
        if observed and desired_sha!=observed:
            return PreflightFailure(
                "stale_branch_base",
                {"observed_head_sha":observed,"desired_sha":desired_sha},
                "refresh repository state and create the branch from the exact observed main head",
            )
        return None
    if resource=="file":
        branch=target.get("branch")
        conflicted=set(repository_context.get("conflicted_workload_branches") or [])
        if isinstance(branch,str) and branch in conflicted:
            return PreflightFailure(
                "conflicted_workload_branch",
                {"branch":branch},
                "use repository_context.conflict_recovery_branch; rejected merge branches are immutable recovery evidence",
            )
        if not isinstance(branch,str) or branch not in branches:
            return PreflightFailure(
                "missing_target_branch",
                {
                    "branch":branch,
                    "known_workload_branches":sorted(branches),
                },
                "reuse an existing observed workload branch or create one first",
            )
    return None


def _preflight_native_target(
    plan: ActionPlan,
    repository_context: dict[str, Any],
) -> PreflightFailure | None:
    if plan.executor is not ExecutorKind.GITHUB_NATIVE:
        return None
    action=plan.payload.get("action")
    target=plan.payload.get("target")
    if not isinstance(target,dict):
        return PreflightFailure(
            "invalid_target",
            {"action":action},
            "produce a native GitHub action with a typed target",
        )
    if action=="create_pr":
        head=target.get("head")
        conflicted=set(repository_context.get("conflicted_workload_branches") or [])
        if isinstance(head,str) and head in conflicted:
            return PreflightFailure(
                "conflicted_pr_head_branch",
                {"head":head},
                "open replacement work only from repository_context.conflict_recovery_branch",
            )
        branches=_samuel_branch_heads(repository_context)
        if not isinstance(head,str) or head not in branches:
            return PreflightFailure(
                "missing_pr_head_branch",
                {"head":head,"known_workload_branches":sorted(branches)},
                "create or reuse an observed workload branch before opening a PR",
            )
    if action=="merge_pr":
        number=target.get("number")
        expected=target.get("expected_head_sha")
        matches=[
            item for item in repository_context.get("open_pull_requests") or []
            if isinstance(item,dict) and item.get("number")==number
        ]
        if len(matches)!=1:
            return PreflightFailure(
                "missing_merge_target",
                {"number":number,"matches":len(matches)},
                "refresh pull-request state before planning merge",
            )
        actual=matches[0].get("head_sha")
        if actual!=expected:
            return PreflightFailure(
                "stale_pr_head",
                {"number":number,"expected_head_sha":expected,"actual_head_sha":actual},
                "refresh the PR and replan against its exact current head",
            )
        if matches[0].get("ci_state")!="success":
            return PreflightFailure(
                "pr_not_ready",
                {"number":number,"ci_state":matches[0].get("ci_state")},
                "wait for authoritative CI success before merge",
            )
    return None


def preflight_semantic_plan(
    *,
    plan: ActionPlan,
    progress: dict[str, Any] | None,
    completion_claim: dict[str, Any] | None,
    issue_body: str,
    state: ResearchState,
    repository_context: dict[str, Any],
) -> PreflightFailure | None:
    """Reject predictable semantic/execution failures before enqueue/dispatch."""
    if plan.idempotency_key in state.action_queue:
        prior=state.action_queue[plan.idempotency_key]
        return PreflightFailure(
            "duplicate_action",
            {
                "action_id":plan.idempotency_key,
                "prior_status":prior.get("status") if isinstance(prior,dict) else None,
            },
            "do not repeat an already-known ActionPlan; choose the next unmet criterion",
        )

    failure=_preflight_repository_target(plan,repository_context)
    if failure is not None:
        return failure
    failure=_preflight_native_target(plan,repository_context)
    if failure is not None:
        return failure

    criteria=extract_acceptance_criteria(issue_body)
    if not criteria:
        return None

    if _is_close_issue(plan):
        if progress is not None:
            return PreflightFailure(
                "close_has_progress_claim",
                {"criterion":progress.get("criterion")},
                "close_issue should use completion_claim, not a new progress claim",
            )
        if completion_claim is None:
            return PreflightFailure(
                "premature_close",
                {"acceptance_criteria":list(criteria),"missing":"completion_claim"},
                "map every acceptance criterion to terminal-success evidence before closing",
            )
        claimed=completion_claim.get("criteria")
        if not isinstance(claimed,list):
            return PreflightFailure(
                "invalid_completion_claim",
                {"reason":"criteria must be an array"},
                "provide one completion entry for every exact acceptance criterion",
            )
        by_criterion={}
        for item in claimed:
            if not isinstance(item,dict):
                continue
            criterion=item.get("criterion")
            evidence=item.get("evidence_action_ids")
            if isinstance(criterion,str) and isinstance(evidence,list):
                by_criterion[criterion]=evidence
        missing=[criterion for criterion in criteria if criterion not in by_criterion]
        extra=[criterion for criterion in by_criterion if criterion not in criteria]
        if missing or extra:
            return PreflightFailure(
                "incomplete_acceptance_coverage",
                {"missing":missing,"extra":extra},
                "cover each exact ## Acceptance bullet once and do not invent criteria",
            )
        verified=verified_evidence_ids(state)
        invalid={}
        for criterion in criteria:
            ids=by_criterion[criterion]
            if not ids:
                invalid[criterion]=ids
                continue
            bad=[
                action_id for action_id in ids
                if not isinstance(action_id,str) or action_id not in verified
            ]
            if bad:
                invalid[criterion]=bad
        if invalid:
            return PreflightFailure(
                "unverified_completion_evidence",
                {"invalid_evidence":invalid,"verified_evidence_ids":sorted(verified)},
                "use only terminal PASS/NOOP durable or inherited evidence IDs",
            )
        return None

    if completion_claim is not None:
        return PreflightFailure(
            "completion_claim_before_close",
            {},
            "use completion_claim only for close_issue",
        )
    if progress is None:
        return PreflightFailure(
            "missing_acceptance_progress",
            {"acceptance_criteria":list(criteria)},
            "identify the exact ## Acceptance criterion this ActionPlan advances",
        )
    criterion=progress.get("criterion")
    if criterion not in criteria:
        return PreflightFailure(
            "unknown_acceptance_criterion",
            {"criterion":criterion,"acceptance_criteria":list(criteria)},
            "copy one exact ## Acceptance bullet into progress.criterion",
        )
    integrated=integrated_acceptance_evidence(state)
    if criterion in integrated:
        return PreflightFailure(
            "acceptance_already_integrated",
            {
                "criterion":criterion,
                "evidence_action_ids":list(integrated[criterion]),
            },
            (
                "do not re-prove an acceptance criterion already integrated through "
                "a verified merged PR; choose the next unmet criterion or close the "
                "issue with a complete evidence claim"
            ),
        )
    return None
