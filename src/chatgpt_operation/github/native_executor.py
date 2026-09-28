"""Closed-world native GitHub mutation contract for Samuel executors."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from chatgpt_operation.controller.action_plan import ActionPlan, ActionPlanError, ExecutorKind
from chatgpt_operation.controller.execution import ExecutionResult, ExecutionStatus


class NativeGitHubError(ValueError):
    pass


class NativeGitHubAction(str, Enum):
    MERGE_PR = "merge_pr"
    CREATE_PR = "create_pr"
    COMMENT_ISSUE = "comment_issue"
    CLOSE_ISSUE = "close_issue"
    DISPATCH_WORKFLOW = "dispatch_workflow"


NATIVE_GITHUB_PAYLOAD_ALLOWED_FIELDS = frozenset({
    "action", "repository", "target",
    "preconditions", "desired_postcondition",
})
NATIVE_GITHUB_PAYLOAD_REQUIRED_FIELDS = frozenset({
    "action", "repository", "target", "desired_postcondition",
})


ReadState = Callable[[NativeGitHubAction, dict[str, Any]], dict[str, Any]]
Mutate = Callable[[NativeGitHubAction, dict[str, Any]], dict[str, Any]]


def native_github_reasoning_contract() -> dict[str, Any]:
    """Return the closed-world semantic contract consumed by Samuel reasoning."""
    return {
        "rule": (
            "mutation is read-before/write/read-after and postcondition verified; "
            "payload must match this closed-world schema exactly"
        ),
        "payload": {
            "required_fields": sorted(NATIVE_GITHUB_PAYLOAD_REQUIRED_FIELDS),
            "optional_fields": ["preconditions"],
            "allowed_fields": sorted(NATIVE_GITHUB_PAYLOAD_ALLOWED_FIELDS),
            "additional_fields": False,
            "repository": "owner/name",
            "preconditions_required_except": ["merge_pr"],
        },
        "actions": {
            "create_pr": {
                "target_required_exactly": ["head", "base", "title", "body"],
                "preconditions": {"pr_present": False},
                "desired_postcondition": {"pr_present": True},
            },
            "close_issue": {
                "target_required_exactly": ["number"],
                "preconditions": {"issue_state": "open"},
                "desired_postcondition": {"issue_state": "closed"},
            },
            "merge_pr": {
                "target_required": ["number", "expected_head_sha"],
                "target_optional": ["merge_method"],
                "preconditions": (
                    "optional in proposal; deterministic executor derives exact "
                    "head_sha, mergeable=true, and ci=success"
                ),
                "desired_postcondition": {"merged": True},
            },
        },
        "controller_only_actions": {
            "comment_issue": (
                "status and audit comments are controller-owned side effects, not "
                "semantic implementation progress"
            ),
        },
        "unqualified_actions": {
            "dispatch_workflow": (
                "not exposed to semantic planning until authoritative "
                "post-dispatch readback can verify the desired postcondition"
            ),
        },
    }


@dataclass(frozen=True)
class NativeGitHubCommand:
    action: NativeGitHubAction
    repository: str
    target: dict[str, Any]
    preconditions: dict[str, Any]
    desired_postcondition: dict[str, Any]

    @classmethod
    def from_plan(cls, plan: ActionPlan) -> "NativeGitHubCommand":
        if plan.executor is not ExecutorKind.GITHUB_NATIVE:
            raise ActionPlanError("plan is not for the native GitHub executor")
        if plan.requires_escalation():
            raise ActionPlanError("action plan requires escalation before execution")
        raw = plan.payload
        if (
            set(raw) - NATIVE_GITHUB_PAYLOAD_ALLOWED_FIELDS
            or not NATIVE_GITHUB_PAYLOAD_REQUIRED_FIELDS.issubset(raw)
        ):
            raise NativeGitHubError(
                "native GitHub payload must use the closed-world schema"
            )
        try:
            action = NativeGitHubAction(raw["action"])
        except (TypeError, ValueError) as exc:
            raise NativeGitHubError("unsupported native GitHub action") from exc
        repository = raw["repository"]
        if not isinstance(repository, str) or "/" not in repository:
            raise NativeGitHubError("repository must be owner/name")
        for field in ("target", "desired_postcondition"):
            if not isinstance(raw[field], dict):
                raise NativeGitHubError(f"{field} must be an object")
        supplied_preconditions = raw.get("preconditions")
        if supplied_preconditions is not None and not isinstance(
            supplied_preconditions, dict
        ):
            raise NativeGitHubError("preconditions must be an object")
        if action is not NativeGitHubAction.MERGE_PR and supplied_preconditions is None:
            raise NativeGitHubError("preconditions are required for this action")
        if not raw["desired_postcondition"]:
            raise NativeGitHubError("desired_postcondition must not be empty")
        target = dict(raw["target"])
        preconditions = dict(supplied_preconditions or {})
        if action is NativeGitHubAction.MERGE_PR:
            required_merge = {"number", "expected_head_sha"}
            optional_merge = {"merge_method"}
            if (
                not required_merge.issubset(target)
                or set(target) - required_merge - optional_merge
            ):
                raise NativeGitHubError(
                    "merge_pr target requires number and expected_head_sha"
                )
            expected_head = target["expected_head_sha"]
            if (
                not isinstance(expected_head, str)
                or not expected_head.strip()
            ):
                raise NativeGitHubError(
                    "merge_pr expected_head_sha must be non-empty"
                )
            mandatory = {
                "head_sha": expected_head,
                "mergeable": True,
                "ci": "success",
            }
            for key, value in mandatory.items():
                if key in preconditions and preconditions[key] != value:
                    raise NativeGitHubError(
                        "merge_pr precondition conflicts with mandatory safety gate: "
                        + key
                    )
                preconditions[key] = value
            if raw["desired_postcondition"] != {"merged": True}:
                raise NativeGitHubError(
                    "merge_pr desired_postcondition must be merged=true"
                )
        if action is NativeGitHubAction.CREATE_PR:
            required = {"head", "base", "title", "body"}
            if set(target) != required:
                raise NativeGitHubError(
                    "create_pr target must contain head, base, title, and body"
                )
            if any(
                not isinstance(target[key], str) or not target[key].strip()
                for key in ("head", "base", "title")
            ):
                raise NativeGitHubError(
                    "create_pr head, base, and title must be non-empty strings"
                )
            if not isinstance(target["body"], str):
                raise NativeGitHubError("create_pr body must be a string")
        return cls(
            action,
            repository,
            target,
            preconditions,
            dict(raw["desired_postcondition"]),
        )


def _matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(actual.get(key) == value for key, value in expected.items())


def execute_native_github(
    plan: ActionPlan,
    *,
    read_state: ReadState,
    mutate: Mutate,
) -> ExecutionResult:
    """Execute one bounded GitHub mutation with read-before/write/read-after semantics."""
    command = NativeGitHubCommand.from_plan(plan)
    before = read_state(command.action, {
        "repository": command.repository,
        **command.target,
    })

    if _matches(before, command.desired_postcondition):
        return ExecutionResult(
            research_id=plan.research_id,
            action_id=plan.idempotency_key,
            executor=plan.executor,
            status=ExecutionStatus.NOOP,
            observation="desired GitHub postcondition already holds",
            details={"before": before},
        )

    if not _matches(before, command.preconditions):
        return ExecutionResult(
            research_id=plan.research_id,
            action_id=plan.idempotency_key,
            executor=plan.executor,
            status=ExecutionStatus.REJECTED,
            observation="GitHub precondition mismatch; refusing stale mutation",
            details={"before": before, "required": command.preconditions},
        )

    mutation = mutate(command.action, {
        "repository": command.repository,
        **command.target,
    })
    after = read_state(command.action, {
        "repository": command.repository,
        **command.target,
    })
    if not _matches(after, command.desired_postcondition):
        return ExecutionResult(
            research_id=plan.research_id,
            action_id=plan.idempotency_key,
            executor=plan.executor,
            status=ExecutionStatus.FAILED,
            observation="GitHub mutation returned but postcondition verification failed",
            retryable=True,
            details={"mutation": mutation, "after": after, "expected": command.desired_postcondition},
        )

    return ExecutionResult(
        research_id=plan.research_id,
        action_id=plan.idempotency_key,
        executor=plan.executor,
        status=ExecutionStatus.PASS,
        observation="GitHub mutation verified by postcondition readback",
        details={"mutation": mutation, "after": after},
    )
