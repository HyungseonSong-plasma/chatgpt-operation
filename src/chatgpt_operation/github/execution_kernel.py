"""Deterministic execution kernel between Samuel reasoning and mutation providers."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.controller.execution import ExecutionResult, ExecutionStatus
from chatgpt_operation.github.native_executor import (
    NativeGitHubAction,
    execute_native_github,
)


class ExecutionKernelError(RuntimeError):
    pass


class GitHubCapability(str, Enum):
    MERGE_PR = "GITHUB_PR_MERGE"
    COMMENT_ISSUE = "GITHUB_ISSUE_COMMENT"
    CLOSE_ISSUE = "GITHUB_ISSUE_CLOSE"
    DISPATCH_WORKFLOW = "GITHUB_WORKFLOW_DISPATCH"


ACTION_CAPABILITIES = {
    NativeGitHubAction.MERGE_PR: GitHubCapability.MERGE_PR,
    NativeGitHubAction.COMMENT_ISSUE: GitHubCapability.COMMENT_ISSUE,
    NativeGitHubAction.CLOSE_ISSUE: GitHubCapability.CLOSE_ISSUE,
    NativeGitHubAction.DISPATCH_WORKFLOW: GitHubCapability.DISPATCH_WORKFLOW,
}


@dataclass(frozen=True)
class ExecutionProvider:
    name: str
    capabilities: frozenset[GitHubCapability]
    read_state: Callable[[NativeGitHubAction, dict[str, Any]], dict[str, Any]]
    mutate: Callable[[NativeGitHubAction, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ExecutionReceipt:
    capability: GitHubCapability
    provider: str
    attempted: bool
    result: ExecutionResult

    @property
    def complete(self) -> bool:
        return self.result.status in {ExecutionStatus.PASS, ExecutionStatus.NOOP}


class ExecutionKernel:
    """The sole authority for provider selection and mutation execution."""

    def __init__(self, providers: list[ExecutionProvider]):
        self._providers = tuple(providers)

    def execute(self, plan: ActionPlan) -> ExecutionReceipt:
        raw_action = plan.payload.get("action")
        try:
            action = NativeGitHubAction(raw_action)
        except (TypeError, ValueError) as exc:
            raise ExecutionKernelError(f"unsupported action: {raw_action}") from exc
        capability = ACTION_CAPABILITIES[action]
        provider = next(
            (p for p in self._providers if capability in p.capabilities),
            None,
        )
        if provider is None:
            raise ExecutionKernelError(
                f"no registered execution provider for {capability.value}"
            )

        # Capability-related BLOCKED state cannot be inferred by the controller:
        # a provider must be selected and the mutation path actually entered.
        result = execute_native_github(
            plan,
            read_state=provider.read_state,
            mutate=provider.mutate,
        )
        attempted = result.status not in {
            ExecutionStatus.NOOP,
            ExecutionStatus.REJECTED,
        }
        return ExecutionReceipt(
            capability=capability,
            provider=provider.name,
            attempted=attempted,
            result=result,
        )
