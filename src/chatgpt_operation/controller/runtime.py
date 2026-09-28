"""Production composition root for one Samuel controller cycle.

The root owns deterministic state loading, admission lifecycle, work selection,
reasoning preflight, and typed reasoning consumption. It returns write requests
but never performs repository side effects itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import copy
from typing import Any, Callable

from .action_lifecycle import ActionLifecycle, DispatchIntent
from .action_plan import ActionPlan, ExecutorKind
from .bootstrap import BootstrapWork, select_controller_work
from .command import ControllerCommand, ControllerCommandKind
from .decisions import DecisionRegistry, GuardOutcome
from .durable_state import can_rollover_state, load_state_comment, state_write_request
from .diagnostic import (
    enqueue_suspended_action,
    record_action_dispatch_intent,
    record_corrective_dispatch_intent,
    record_diagnostic_dispatch_intent,
    record_evidence_dispatch_intent,
)
from .issue_ingestion import (
    ADMISSION_LABEL,
    ADMISSION_MARKER,
    admit_issue,
    decode_admission_ledger,
    discover_admissible_issues,
    encode_admission_ledger,
    transition_issue_status,
)
from .issue_planning import plan_admitted_issue
from .issue_reasoning import (
    IssueReasoningProposal,
    compile_guarded_action,
)
from .reasoning import ReasoningRequest, StructuredReasoningNode
from .reasoning_consumption import (
    ReasoningConsumption,
    consume_reasoning_submission,
)
from .reasoning_provider import ReasoningProviderRegistry
from .research import ResearchState
from chatgpt_operation.github.native_executor import NativeGitHubCommand
from chatgpt_operation.repository.action_plan_adapter import to_repository_manifest


class ControllerCompositionError(ValueError):
    pass


class TriggerKind(str, Enum):
    SCHEDULE = "schedule"
    WORKFLOW_DISPATCH = "workflow_dispatch"
    ISSUES = "issues"
    PULL_REQUEST = "pull_request"
    ISSUE_COMMENT = "issue_comment"
    RETRY = "retry"
    BOOTSTRAP = "bootstrap"


@dataclass(frozen=True)
class ControllerTrigger:
    kind: TriggerKind
    action: str = ""
    head_sha: str = ""
    ref: str = ""
    executor_ref: str = ""
    executor_head_sha: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ControllerTrigger":
        required = {
            "kind", "action", "head_sha", "ref",
            "executor_ref", "executor_head_sha",
        }
        if not isinstance(raw, dict) or set(raw) != required:
            raise ControllerCompositionError("invalid controller trigger schema")
        try:
            kind = TriggerKind(raw["kind"])
        except (TypeError, ValueError) as exc:
            raise ControllerCompositionError("unsupported controller trigger") from exc
        values: dict[str, str] = {}
        for key in (
            "action", "head_sha", "ref", "executor_ref", "executor_head_sha",
        ):
            value = raw[key]
            if not isinstance(value, str):
                raise ControllerCompositionError(f"trigger {key} must be a string")
            values[key] = value
        return cls(kind=kind, **values)

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "action": self.action,
            "head_sha": self.head_sha,
            "ref": self.ref,
            "executor_ref": self.executor_ref,
            "executor_head_sha": self.executor_head_sha,
        }


@dataclass(frozen=True)
class ControllerCycle:
    trigger: ControllerTrigger
    selected_work: dict[str, Any]
    issue_planning: dict[str, Any] | None
    admission_write: dict[str, Any] | None = None
    state_write: dict[str, Any] | None = None
    execution_command: ControllerCommand | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 4,
            "trigger": self.trigger.to_dict(),
            "selected_work": self.selected_work,
            "issue_planning": self.issue_planning,
            "admission_write": self.admission_write,
            "state_write": self.state_write,
            "execution_command": (
                None if self.execution_command is None
                else self.execution_command.to_dict()
            ),
        }


def _admission_state(
    comments: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], int | None]:
    matches = [
        comment for comment in comments
        if ADMISSION_MARKER in str(comment.get("body", ""))
    ]
    if len(matches) > 1:
        raise ControllerCompositionError("multiple admission ledgers")
    if not matches:
        return {}, None
    comment_id = matches[0].get("id")
    if not isinstance(comment_id, int) or isinstance(comment_id, bool):
        raise ControllerCompositionError("admission ledger comment id is invalid")
    return decode_admission_ledger(str(matches[0]["body"])), comment_id


def _admission_write(
    comment_id: int | None,
    work: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "method": "POST" if comment_id is None else "PATCH",
        "comment_id": comment_id,
        "body": encode_admission_ledger(work),
    }


def _selected_payload(selected: tuple[str, Any] | None) -> dict[str, Any]:
    if selected is None:
        return {"kind": "idle"}
    kind, value = selected
    if kind == "pending":
        if not isinstance(value, BootstrapWork):
            raise ControllerCompositionError("pending work has invalid type")
        return {
            "kind": "pending",
            "work_id": value.work_id,
            "workflow": value.workflow,
            "ref": value.ref,
        }
    if not isinstance(value, dict):
        raise ControllerCompositionError("selected work payload must be an object")
    return {"kind": kind, **value}


def _initial_state(work_id: str, item: dict[str, Any]) -> ResearchState:
    return ResearchState(
        work_id,
        str(item.get("title") or item.get("body") or work_id),
    )


def _owned_ready_pr_plan(
    state: ResearchState,
    repository_context: dict[str, Any] | None,
) -> ActionPlan | None:
    """Promote exactly one ready PR owned by the active workload into the action queue."""
    if repository_context is None or not can_rollover_state(state):
        return None
    if any(
        recovery.get("status") in {"open", "needs_evidence"}
        for recovery in state.diagnostic_recoveries.values()
    ):
        return None

    owned_branches: set[str] = set()
    for item in state.action_queue.values():
        plan_raw=item.get("plan")
        if not isinstance(plan_raw,dict):
            continue
        payload=plan_raw.get("payload")
        if not isinstance(payload,dict):
            continue
        target=payload.get("target")
        if not isinstance(target,dict):
            continue
        branch=target.get("branch")
        if isinstance(branch,str) and branch.startswith("samuel/"):
            owned_branches.add(branch)
        if payload.get("action")=="create_pr":
            head=target.get("head")
            if isinstance(head,str) and head.startswith("samuel/"):
                owned_branches.add(head)

    if not owned_branches:
        return None

    repository=str(repository_context.get("repository") or "").strip()
    prs=repository_context.get("open_pull_requests",[])
    if not repository or not isinstance(prs,list):
        return None
    candidates=[
        item for item in prs
        if isinstance(item,dict)
        and item.get("state")=="open"
        and not bool(item.get("draft"))
        and item.get("ci_state")=="success"
        and item.get("head_ref") in owned_branches
        and isinstance(item.get("number"),int)
        and isinstance(item.get("head_sha"),str)
        and item.get("head_sha")
    ]
    if len(candidates)>1:
        raise ControllerCompositionError(
            "multiple ready pull requests belong to active workload"
        )
    if not candidates:
        return None

    pr=candidates[0]
    plan=ActionPlan.from_dict({
        "schema_version":1,
        "research_id":state.research_id,
        "stage":"execute",
        "executor":"github_native",
        "payload":{
            "action":"merge_pr",
            "repository":repository,
            "target":{
                "number":pr["number"],
                "expected_head_sha":pr["head_sha"],
            },
            "desired_postcondition":{"merged":True},
        },
        "expected_observation":(
            f"Pull request #{pr['number']} is merged at exact head "
            f"{pr['head_sha']} after native safety checks."
        ),
    })
    NativeGitHubCommand.from_plan(plan)
    return plan


class SamuelController:
    """Single deterministic root for selecting and preflighting one controller cycle."""

    def __init__(
        self,
        *,
        decisions: DecisionRegistry,
        reasoning: ReasoningProviderRegistry | None = None,
        reasoning_enabled: bool = True,
        now: Callable[[], datetime] | None = None,
    ):
        self.decisions = decisions
        self.reasoning = reasoning or ReasoningProviderRegistry()
        self.reasoning_enabled = reasoning_enabled
        self.now = now or (lambda: datetime.now(timezone.utc))

    def _requested_at(self) -> str:
        value = self.now()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _require_executor_identity(trigger: ControllerTrigger) -> tuple[str, str]:
        if not trigger.executor_ref.strip() or not trigger.executor_head_sha.strip():
            raise ControllerCompositionError(
                "dispatch intent requires executor_ref and executor_head_sha"
            )
        return trigger.executor_ref.strip(), trigger.executor_head_sha.strip()

    def _prepare_dispatch_intent(
        self,
        *,
        trigger: ControllerTrigger,
        comments: list[dict[str, Any]],
        state: ResearchState,
        payload: dict[str, Any],
        admission_write: dict[str, Any] | None = None,
        planning: dict[str, Any] | None = None,
    ) -> ControllerCycle:
        kind = payload.get("kind")
        if kind not in {"action", "evidence", "diagnostic", "corrective"}:
            return ControllerCycle(
                trigger, payload, planning, admission_write, None
            )
        action_id = payload.get("action_id")
        if not isinstance(action_id, str) or not action_id:
            raise ControllerCompositionError("dispatch work has no action_id")
        executor_ref, executor_head_sha = self._require_executor_identity(trigger)
        proposed = copy.deepcopy(state)
        requested_at = self._requested_at()
        if kind == "action":
            raw_plan = payload.get("plan")
            if not isinstance(raw_plan, dict):
                raise ControllerCompositionError("action work has no typed plan")
            plan = ActionPlan.from_dict(raw_plan)
            workflow = {
                ExecutorKind.GITHUB_NATIVE: "samuel-native-github.yml",
                ExecutorKind.REPOSITORY_MUTATION: "samuel-repository-mutation.yml",
            }.get(plan.executor)
            if workflow is None:
                raise ControllerCompositionError(
                    "production action executor is not supported: " + plan.executor.value
                )
            record_action_dispatch_intent(
                proposed,
                action_id,
                workflow=workflow,
                ref=executor_ref,
                requested_at=requested_at,
                expected_head_sha=executor_head_sha,
            )
        elif kind == "evidence":
            record_evidence_dispatch_intent(
                proposed,
                action_id,
                workflow="samuel-evidence-acquisition.yml",
                ref=executor_ref,
                requested_at=requested_at,
                expected_head_sha=executor_head_sha,
            )
        elif kind == "diagnostic":
            record_diagnostic_dispatch_intent(
                proposed,
                action_id,
                workflow="samuel-diagnostic-recovery.yml",
                ref=executor_ref,
                requested_at=requested_at,
                expected_head_sha=executor_head_sha,
            )
        else:
            record_corrective_dispatch_intent(
                proposed,
                action_id,
                workflow="samuel-native-github.yml",
                ref=executor_ref,
                requested_at=requested_at,
                expected_head_sha=executor_head_sha,
            )
        command_kind = {
            "action": ControllerCommandKind.DISPATCH_ACTION,
            "evidence": ControllerCommandKind.DISPATCH_EVIDENCE,
            "diagnostic": ControllerCommandKind.DISPATCH_DIAGNOSTIC,
            "corrective": ControllerCommandKind.DISPATCH_CORRECTIVE,
        }[kind]
        command = ControllerCommand(
            command_kind,
            action_id,
            proposed.research_id,
            proposed.revision,
        )
        return ControllerCycle(
            trigger,
            payload,
            planning,
            admission_write,
            state_write_request(comments, proposed),
            command,
        )

    @staticmethod
    def _command_for_in_flight(
        payload: dict[str, Any],
        state: ResearchState,
    ) -> ControllerCommand | None:
        mapping = {
            "action_intent": ControllerCommandKind.RECONCILE_ACTION,
            "action_observation": ControllerCommandKind.OBSERVE_ACTION,
            "evidence_intent": ControllerCommandKind.RECONCILE_EVIDENCE,
            "evidence_observation": ControllerCommandKind.OBSERVE_EVIDENCE,
            "diagnostic_intent": ControllerCommandKind.RECONCILE_DIAGNOSTIC,
            "diagnostic_observation": ControllerCommandKind.OBSERVE_DIAGNOSTIC,
            "corrective_intent": ControllerCommandKind.RECONCILE_CORRECTIVE,
            "corrective_observation": ControllerCommandKind.OBSERVE_CORRECTIVE,
        }
        command_kind = mapping.get(payload.get("kind"))
        if command_kind is None:
            return None
        action_id = payload.get("action_id")
        if not isinstance(action_id, str) or not action_id:
            raise ControllerCompositionError("in-flight work has no action_id")
        return ControllerCommand(
            command_kind,
            action_id,
            state.research_id,
            state.revision,
        )

    def _consume_provider_reasoning(
        self,
        *,
        work: dict[str, dict[str, Any]],
        work_id: str,
        state: ResearchState,
        repository_context: dict[str, Any] | None,
    ) -> tuple[ReasoningConsumption, dict[str, Any]]:
        item = work.get(work_id)
        if item is None or item.get("status") != "reasoning_required":
            raise ControllerCompositionError(
                "provider reasoning requires reasoning_required work"
            )
        planned = plan_admitted_issue(item, registry=self.decisions)
        context = planned.envelope.as_reasoning_context()
        context["durable_state"] = {
            "research_id": state.research_id,
            "revision": state.revision,
            "stage": state.stage.value,
            "action_queue": copy.deepcopy(state.action_queue),
            "diagnostic_recoveries": copy.deepcopy(state.diagnostic_recoveries),
        }
        context["repository_context"] = copy.deepcopy(repository_context or {})
        context["execution_contracts"] = {
            "action_plan": {
                "required_fields": [
                    "schema_version",
                    "research_id",
                    "stage",
                    "executor",
                    "payload",
                    "expected_observation",
                ],
                "schema_version": 1,
                "research_id": work_id,
                "stage": (
                    "one non-terminal ResearchStage such as implement or execute"
                ),
                "decision_risk": "optional",
            },
            "repository_mutation": {
                "purpose": "bounded branch/file mutation through deterministic policy",
                "resource_actions": {
                    "branch": ["create"],
                    "file": ["create", "update", "delete"],
                },
                "branch_rule": "never mutate main; use samuel/* or issue-*",
                "file_update_rule": (
                    "update/delete require exact current file SHA; create requires absent=true"
                ),
            },
            "github_native": {
                "rule": "mutation is read-before/write/read-after and postcondition verified",
                "create_pr": {
                    "target": ["head", "base", "title", "body"],
                    "preconditions": {"pr_present": False},
                    "desired_postcondition": {"pr_present": True},
                },
                "close_issue": {
                    "target": ["number"],
                    "preconditions": {"issue_state": "open"},
                    "desired_postcondition": {"issue_state": "closed"},
                },
                "comment_issue": {
                    "target": ["number", "body", "marker"],
                    "precondition_keys": ["issue_state", "comment_present"],
                    "desired_postcondition": {"comment_present": True},
                },
                "merge_pr": {
                    "target_required": ["number", "expected_head_sha"],
                    "preconditions": (
                        "optional in proposal; deterministic executor always enforces "
                        "exact head_sha, mergeable=true, and ci=success"
                    ),
                    "desired_postcondition": {"merged": True},
                },
                "dispatch_workflow": {
                    "target_required": ["workflow", "ref"],
                },
            },
        }
        def parse_provider_proposal(
            raw: dict[str, Any],
        ) -> IssueReasoningProposal:
            proposal = IssueReasoningProposal.from_dict(raw)
            if (
                proposal.operation == "implement_gap"
                and not planned.envelope.implementation_gaps
            ):
                raise ValueError(
                    "implement_gap is invalid because implementation_gaps is empty; "
                    "use analyze for an action within accepted architecture"
                )
            if proposal.action_plan is not None:
                candidate = ActionPlan.from_dict(proposal.action_plan)
                if candidate.research_id != work_id:
                    raise ValueError(
                        "ActionPlan research_id must equal active work_id " + work_id
                    )
                if candidate.executor is ExecutorKind.GITHUB_NATIVE:
                    NativeGitHubCommand.from_plan(candidate)
                elif candidate.executor is ExecutorKind.REPOSITORY_MUTATION:
                    expected_repository = (
                        str((repository_context or {}).get("repository") or "")
                        or None
                    )
                    to_repository_manifest(
                        candidate,
                        expected_repository=expected_repository,
                    )
                else:
                    raise ValueError(
                        "production semantic provider emitted unsupported executor "
                        + candidate.executor.value
                    )
            return proposal

        proposal = StructuredReasoningNode(
            parser=parse_provider_proposal,
            max_attempts=2,
        ).run(
            ReasoningRequest(
                task=(
                    "Produce exactly one next bounded ActionPlan toward completing "
                    f"{work_id}. Continue from durable execution history. "
                    "Do not repeat completed actions. When implementation_gaps is "
                    "empty, operation must be analyze. Use implement_gap only for a "
                    "named gap in implementation_gaps. Follow execution_contracts "
                    "exactly. Prefer the smallest verifiable next step; return null "
                    "only when no safe executable step exists."
                ),
                context=context,
            ),
            self.reasoning.runner(),
        )
        outcome, plan, reason = compile_guarded_action(
            proposal, planned.envelope
        )
        repository_audit = context.get("repository_context") or {}
        durable_audit = context.get("durable_state") or {}
        planning = {
            "schema_version": 1,
            "work_id": work_id,
            "outcome": outcome.value,
            "reason": reason,
            "blocker": None,
            "semantic_provider": {
                "available": True,
                "provider": self.reasoning.status().provider,
                "mode": "AUTO_WITH_AUDIT",
            },
            "proposal": {
                "operation": proposal.operation,
                "decision_id": proposal.decision_id,
                "compatible_with_locked_decisions": (
                    proposal.compatible_with_locked_decisions
                ),
                "revision_requested": proposal.revision_requested,
            },
            "action_plan": proposal.action_plan,
            "reasoning_context": {
                "goal": context.get("goal"),
                "locked_decisions": context.get("locked_decisions", []),
                "implementation_gaps": context.get("implementation_gaps", []),
                "allowed_reasoning_operations": context.get(
                    "allowed_reasoning_operations", []
                ),
                "escalation_constraints": context.get(
                    "escalation_constraints", []
                ),
                "durable_state": {
                    "research_id": durable_audit.get("research_id"),
                    "revision": durable_audit.get("revision"),
                    "stage": durable_audit.get("stage"),
                    "action_statuses": {
                        key: value.get("status")
                        for key, value in (
                            durable_audit.get("action_queue") or {}
                        ).items()
                        if isinstance(value, dict)
                    },
                },
                "repository_context": {
                    "repository": repository_audit.get("repository"),
                    "observed_head_sha": repository_audit.get(
                        "observed_head_sha"
                    ),
                    "open_issues": [
                        {
                            "number": item.get("number"),
                            "title": item.get("title"),
                            "state": item.get("state"),
                            "labels": item.get("labels", []),
                        }
                        for item in repository_audit.get(
                            "open_issues", []
                        )
                        if isinstance(item, dict)
                    ],
                    "open_pull_requests": repository_audit.get(
                        "open_pull_requests", []
                    ),
                    "samuel_branches": repository_audit.get(
                        "samuel_branches", []
                    ),
                },
            },
        }
        if plan is None:
            if (
                proposal.operation == "analyze"
                and outcome is GuardOutcome.CONTINUE
            ):
                return (
                    ReasoningConsumption(
                        "reasoning_required",
                        "provider analysis produced no executable ActionPlan",
                        work,
                        state,
                        None,
                    ),
                    planning,
                )
            lifecycle = (
                "revision_required"
                if outcome is GuardOutcome.REVISION_REQUIRED
                else "blocked"
            )
            return (
                ReasoningConsumption(
                    outcome.value,
                    reason,
                    transition_issue_status(work, work_id, lifecycle),
                    state,
                    None,
                ),
                planning,
            )
        if plan.research_id != work_id or state.research_id != work_id:
            raise ControllerCompositionError(
                "provider ActionPlan research identity does not match active work"
            )
        proposed = copy.deepcopy(state)
        enqueue_suspended_action(proposed, plan)
        return (
            ReasoningConsumption(
                "planned",
                reason,
                transition_issue_status(work, work_id, "planned"),
                proposed,
                plan.idempotency_key,
            ),
            planning,
        )

    def _consume_waiting_reasoning(
        self,
        *,
        trigger: ControllerTrigger,
        comments: list[dict[str, Any]],
        work: dict[str, dict[str, Any]],
        work_id: str,
        state: ResearchState | None,
        admission_comment_id: int | None,
        planning: dict[str, Any] | None = None,
        prior_admission_write: dict[str, Any] | None = None,
        repository_context: dict[str, Any] | None = None,
    ) -> ControllerCycle:
        item = work.get(work_id)
        if item is None:
            raise ControllerCompositionError("reasoning work is missing from admission ledger")
        working_state = state or _initial_state(work_id, item)
        if not self.reasoning_enabled:
            return ControllerCycle(
                trigger,
                {"kind": "reasoning_required", "work_id": work_id},
                planning,
                prior_admission_write,
                None,
            )
        if self.reasoning.status().available:
            result, provider_planning = self._consume_provider_reasoning(
                work=work,
                work_id=work_id,
                state=working_state,
                repository_context=repository_context,
            )
            planning = provider_planning
        else:
            result = consume_reasoning_submission(
                comments,
                work,
                work_id,
                registry=self.decisions,
                state=working_state,
            )
        if result.outcome == "reasoning_required":
            return ControllerCycle(
                trigger,
                {"kind": "reasoning_required", "work_id": work_id},
                planning,
                prior_admission_write,
                None,
            )

        admission_write = _admission_write(admission_comment_id, result.work)
        if result.action_id is None:
            return ControllerCycle(
                trigger,
                {
                    "kind": "reasoning_consumed",
                    "work_id": work_id,
                    "outcome": result.outcome,
                    "action_id": None,
                },
                planning,
                admission_write,
                None,
            )
        queued = result.state.action_queue.get(result.action_id)
        if not isinstance(queued, dict) or not isinstance(queued.get("plan"), dict):
            raise ControllerCompositionError("planned reasoning produced no durable queued plan")
        payload = {
            "kind": "action",
            "action_id": result.action_id,
            "plan": queued["plan"],
            "reasoning_outcome": result.outcome,
            "work_id": work_id,
        }
        return self._prepare_dispatch_intent(
            trigger=trigger,
            comments=comments,
            state=result.state,
            payload=payload,
            admission_write=admission_write,
            planning=planning,
        )

    def run_cycle(
        self,
        trigger: ControllerTrigger,
        *,
        comments: list[dict[str, Any]],
        pending: list[BootstrapWork],
        issue: dict[str, Any] | None = None,
        repository_context: dict[str, Any] | None = None,
    ) -> ControllerCycle:
        if not isinstance(comments, list) or any(
            not isinstance(item, dict) for item in comments
        ):
            raise ControllerCompositionError("comments must be a list of objects")
        if issue is not None and trigger.kind is not TriggerKind.ISSUES:
            raise ControllerCompositionError(
                "issue payload is only valid for an issues trigger"
            )

        state = load_state_comment(comments)
        admitted, admission_comment_id = _admission_state(comments)
        if issue is not None:
            labels = {
                item.get("name")
                for item in issue.get("labels", [])
                if isinstance(item, dict)
            }
            if ADMISSION_LABEL in labels:
                admission = admit_issue(comments, issue)
                admitted = decode_admission_ledger(admission["body"])
                admission_comment_id = admission["comment_id"]

        admission_write = None
        if repository_context is not None:
            open_issues = repository_context.get("open_issues", [])
            if not isinstance(open_issues, list):
                raise ControllerCompositionError(
                    "repository context open_issues must be a list"
                )
            discovered = discover_admissible_issues(admitted, open_issues)
            if discovered != admitted:
                admitted = discovered
                admission_write = _admission_write(
                    admission_comment_id, admitted
                )

            if state is not None and can_rollover_state(state):
                current = admitted.get(state.research_id)
                open_numbers = {
                    item.get("number")
                    for item in open_issues
                    if isinstance(item, dict)
                    and item.get("state") in {None, "open"}
                    and isinstance(item.get("number"), int)
                }
                if (
                    isinstance(current, dict)
                    and isinstance(current.get("issue_number"), int)
                    and current["issue_number"] not in open_numbers
                ):
                    if current.get("status") != "complete":
                        admitted = transition_issue_status(
                            admitted, state.research_id, "complete"
                        )
                    admission_write = _admission_write(
                        admission_comment_id, admitted
                    )
                    state = None

        if state is not None:
            ready_pr_plan=_owned_ready_pr_plan(state,repository_context)
            if ready_pr_plan is not None:
                proposed=copy.deepcopy(state)
                enqueue_suspended_action(proposed,ready_pr_plan)
                if state.research_id in admitted:
                    admitted=transition_issue_status(
                        admitted,state.research_id,"planned"
                    )
                    admission_write=_admission_write(
                        admission_comment_id,admitted
                    )
                return self._prepare_dispatch_intent(
                    trigger=trigger,
                    comments=comments,
                    state=proposed,
                    payload={
                        "kind":"action",
                        "action_id":ready_pr_plan.idempotency_key,
                        "plan":proposed.action_queue[
                            ready_pr_plan.idempotency_key
                        ]["plan"],
                        "reasoning_outcome":"deterministic_ready_pr",
                        "work_id":state.research_id,
                    },
                    admission_write=admission_write,
                )

        if state is not None and self.reasoning.status().available:
            current = admitted.get(state.research_id)
            if (
                isinstance(current, dict)
                and current.get("status") == "planned"
                and state.action_queue
                and all(
                    item.get("status") in {"complete", "rejected"}
                    for item in state.action_queue.values()
                )
                and not any(
                    recovery.get("status") in {"open", "needs_evidence"}
                    for recovery in state.diagnostic_recoveries.values()
                )
            ):
                admitted = transition_issue_status(
                    admitted, state.research_id, "reasoning_required"
                )
                continuation_write = _admission_write(
                    admission_comment_id, admitted
                )
                return self._consume_waiting_reasoning(
                    trigger=trigger,
                    comments=comments,
                    work=admitted,
                    work_id=state.research_id,
                    state=state,
                    admission_comment_id=admission_comment_id,
                    prior_admission_write=continuation_write,
                    repository_context=repository_context,
                )

        waiting = sorted(
            work_id for work_id, item in admitted.items()
            if item.get("status") == "reasoning_required"
        )
        planned = sorted(
            work_id for work_id, item in admitted.items()
            if item.get("status") == "planned"
        )
        if len(waiting) > 1:
            raise ControllerCompositionError("multiple reasoning-required work items")
        if state is None and planned:
            if len(planned) != 1 or waiting:
                raise ControllerCompositionError(
                    "ambiguous planned work without durable controller state"
                )
            work_id = planned[0]
            admitted = transition_issue_status(admitted, work_id, "reasoning_required")
            recovery_write = _admission_write(admission_comment_id, admitted)
            return self._consume_waiting_reasoning(
                trigger=trigger,
                comments=comments,
                work=admitted,
                work_id=work_id,
                state=None,
                admission_comment_id=admission_comment_id,
                prior_admission_write=recovery_write,
                repository_context=repository_context,
            )
        if waiting:
            return self._consume_waiting_reasoning(
                trigger=trigger,
                comments=comments,
                work=admitted,
                work_id=waiting[0],
                state=state,
                admission_comment_id=admission_comment_id,
                prior_admission_write=admission_write,
                repository_context=repository_context,
            )

        selected = select_controller_work(
            pending,
            diagnostic_recoveries={} if state is None else state.diagnostic_recoveries,
            action_queue={} if state is None else state.action_queue,
            admitted_work=admitted,
        )
        payload = _selected_payload(selected)
        if payload["kind"] == "action_intent":
            if state is None:
                raise ControllerCompositionError(
                    "action intent requires durable controller state"
                )
            action_id=payload.get("action_id")
            if not isinstance(action_id,str) or not action_id:
                raise ControllerCompositionError(
                    "action intent has no action_id"
                )
            queued=state.action_queue.get(action_id)
            if not isinstance(queued,dict):
                raise ControllerCompositionError(
                    "action intent has no durable queue entry"
                )
            intent=DispatchIntent.from_dict(queued.get("dispatch_intent"))
            observed_ref=trigger.executor_ref.strip()
            observed_head=trigger.executor_head_sha.strip()
            if (
                intent.expected_head_sha is not None
                and observed_ref
                and observed_head
                and intent.ref == observed_ref
                and intent.expected_head_sha != observed_head
            ):
                proposed=copy.deepcopy(state)
                retired=proposed.action_queue[action_id]
                retired.setdefault("dispatch_intent_history",[]).append({
                    **intent.to_dict(),
                    "retired_reason":"executor_source_advanced_before_dispatch",
                    "observed_executor_head_sha":observed_head,
                })
                retired["status"]=ActionLifecycle.REJECTED.value
                retired.pop("dispatch_intent",None)
                retired.pop("dispatch_receipt",None)
                proposed.revision += 1
                admission_write=None
                if state.research_id in admitted:
                    admitted=transition_issue_status(
                        admitted,state.research_id,"reasoning_required"
                    )
                    admission_write=_admission_write(
                        admission_comment_id,admitted
                    )
                return ControllerCycle(
                    trigger,
                    {
                        "kind":"stale_action_intent",
                        "action_id":action_id,
                        "expected_head_sha":intent.expected_head_sha,
                        "observed_head_sha":observed_head,
                    },
                    None,
                    admission_write,
                    state_write_request(comments,proposed),
                    None,
                )
        if payload["kind"] in {"action", "evidence", "diagnostic", "corrective"}:
            if state is None:
                raise ControllerCompositionError(
                    "dispatchable work requires durable controller state"
                )
            return self._prepare_dispatch_intent(
                trigger=trigger,
                comments=comments,
                state=state,
                payload=payload,
                admission_write=admission_write,
            )
        if payload["kind"] == "pending":
            raise ControllerCompositionError(
                "legacy static workflow work is not supported by production controller"
            )
        if payload["kind"] != "issue":
            command = None if state is None else self._command_for_in_flight(
                payload, state
            )
            return ControllerCycle(
                trigger, payload, None, admission_write, None, command
            )

        result = plan_admitted_issue(payload, registry=self.decisions)
        provider = self.reasoning.status()
        planning = {
            "schema_version": 1,
            "work_id": result.work_id,
            "outcome": "reasoning_required",
            "reason": (
                "semantic reasoning provider available; reasoning step required"
                if provider.available
                else "external semantic reasoning worker required"
            ),
            "blocker": None,
            "semantic_provider": {
                "available": provider.available,
                "provider": provider.provider,
            },
            "action_plan": None,
            "reasoning_context": result.envelope.as_reasoning_context(),
        }
        transitioned = transition_issue_status(
            admitted, result.work_id, "reasoning_required"
        )
        admission_write = _admission_write(admission_comment_id, transitioned)
        return self._consume_waiting_reasoning(
            trigger=trigger,
            comments=comments,
            work=transitioned,
            work_id=result.work_id,
            state=state,
            admission_comment_id=admission_comment_id,
            planning=planning,
            prior_admission_write=admission_write,
            repository_context=repository_context,
        )
