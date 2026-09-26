"""Deterministic execution kernel between Samuel reasoning and mutation providers."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.controller.research import ResearchState
from chatgpt_operation.controller.execution import ExecutionResult, ExecutionStatus, require_action_recoverable
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
class ProviderFailureEvidence:
    provider: str
    capability: GitHubCapability
    operation: str
    attempted: bool
    error_type: str
    message: str


@dataclass(frozen=True)
class ExecutionReceipt:
    capability: GitHubCapability
    provider: str
    attempted: bool
    result: ExecutionResult
    provider_failures: tuple[ProviderFailureEvidence, ...] = ()

    @property
    def complete(self) -> bool:
        return self.result.status in {ExecutionStatus.PASS, ExecutionStatus.NOOP}


class ExecutionKernel:
    """The sole authority for provider selection and mutation execution."""

    def __init__(self, providers: list[ExecutionProvider], *, state: ResearchState):
        self._providers = tuple(providers)
        self._state = state

    def execute(self, plan: ActionPlan) -> ExecutionReceipt:
        if plan.research_id != self._state.research_id:
            raise ExecutionKernelError(
                f"plan belongs to {plan.research_id}, not {self._state.research_id}"
            )
        require_action_recoverable(self._state, plan.idempotency_key)
        raw_action = plan.payload.get("action")
        try:
            action = NativeGitHubAction(raw_action)
        except (TypeError, ValueError) as exc:
            raise ExecutionKernelError(f"unsupported action: {raw_action}") from exc
        capability = ACTION_CAPABILITIES[action]
        providers = tuple(p for p in self._providers if capability in p.capabilities)
        if not providers:
            raise ExecutionKernelError(
                f"no registered execution provider for {capability.value}"
            )

        failures: list[ProviderFailureEvidence] = []
        for provider in providers:
            try:
                result = execute_native_github(
                    plan,
                    read_state=provider.read_state,
                    mutate=provider.mutate,
                )
            except Exception as exc:
                failures.append(ProviderFailureEvidence(
                    provider=provider.name,
                    capability=capability,
                    operation=action.value,
                    attempted=True,
                    error_type=type(exc).__name__,
                    message=str(exc),
                ))
                continue

            attempted = result.status not in {
                ExecutionStatus.NOOP,
                ExecutionStatus.REJECTED,
            }
            return ExecutionReceipt(
                capability=capability,
                provider=provider.name,
                attempted=attempted,
                result=result,
                provider_failures=tuple(failures),
            )

        summary = "; ".join(
            f"{f.provider}:{f.error_type}:{f.message}" for f in failures
        )
        raise ExecutionKernelError(
            f"all registered providers failed for {capability.value}: {summary}"
        )
