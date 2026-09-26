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
    COMMENT_ISSUE = "comment_issue"
    CLOSE_ISSUE = "close_issue"
    DISPATCH_WORKFLOW = "dispatch_workflow"


ReadState = Callable[[NativeGitHubAction, dict[str, Any]], dict[str, Any]]
Mutate = Callable[[NativeGitHubAction, dict[str, Any]], dict[str, Any]]


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
        allowed = {"action", "repository", "target", "preconditions", "desired_postcondition"}
        if set(raw) != allowed:
            raise NativeGitHubError("native GitHub payload must use the closed-world schema")
        try:
            action = NativeGitHubAction(raw["action"])
        except (TypeError, ValueError) as exc:
            raise NativeGitHubError("unsupported native GitHub action") from exc
        repository = raw["repository"]
        if not isinstance(repository, str) or "/" not in repository:
            raise NativeGitHubError("repository must be owner/name")
        for field in ("target", "preconditions", "desired_postcondition"):
            if not isinstance(raw[field], dict):
                raise NativeGitHubError(f"{field} must be an object")
        if not raw["desired_postcondition"]:
            raise NativeGitHubError("desired_postcondition must not be empty")
        return cls(action, repository, dict(raw["target"]), dict(raw["preconditions"]), dict(raw["desired_postcondition"]))


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
