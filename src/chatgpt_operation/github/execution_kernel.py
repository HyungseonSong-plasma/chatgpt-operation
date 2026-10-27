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
    CREATE_PR = "GITHUB_PR_CREATE"
    COMMENT_ISSUE = "GITHUB_ISSUE_COMMENT"
    CLOSE_ISSUE = "GITHUB_ISSUE_CLOSE"
    DISPATCH_WORKFLOW = "GITHUB_WORKFLOW_DISPATCH"


ACTION_CAPABILITIES = {
    NativeGitHubAction.MERGE_PR: GitHubCapability.MERGE_PR,
    NativeGitHubAction.CREATE_PR: GitHubCapability.CREATE_PR,
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

    def __init__(self, providers: list[ExecutionProvider], *, state: ResearchState,
                 blocker_gate=None, trusted_work_id=None, trusted_head_sha=None):
        self._providers = tuple(providers)
        self._state = state
        # Only a trusted controller/runtime may configure the blocker gate.
        self._blocker_gate = blocker_gate
        self._trusted_work_id = trusted_work_id
        self._trusted_head_sha = trusted_head_sha

    def execute(self, plan: ActionPlan, *, recovery_authorization=None) -> ExecutionReceipt:
        if plan.research_id != self._state.research_id:
            raise ExecutionKernelError(
                f"plan belongs to {plan.research_id}, not {self._state.research_id}"
            )
        if recovery_authorization is None:
            require_action_recoverable(self._state, plan.idempotency_key)
        else:
            from chatgpt_operation.controller.diagnostic import validate_recovery_authorization
            validate_recovery_authorization(self._state, plan, recovery_authorization)
        raw_action = plan.payload.get("action")
        try:
            action = NativeGitHubAction(raw_action)
        except (TypeError, ValueError) as exc:
            raise ExecutionKernelError(f"unsupported action: {raw_action}") from exc
        try:
            capability = ACTION_CAPABILITIES[action]
        except KeyError as exc:
            raise ExecutionKernelError(
                "native action has no registered capability: " + action.value
            ) from exc
        providers = tuple(p for p in self._providers if capability in p.capabilities)
        if recovery_authorization is not None:
            providers = tuple(
                p for p in providers
                if p.name == recovery_authorization.corrective_provider
            )
            if not providers:
                raise ExecutionKernelError(
                    "authorized corrective provider is not registered for "
                    + capability.value
                )
        if not providers:
            raise ExecutionKernelError(
                f"no registered execution provider for {capability.value}"
            )

        if self._blocker_gate is not None:
            from chatgpt_operation.repository.blocker_gate import (
                CommonPreWriteGate, BlockerGateError,
            )
            from chatgpt_operation.repository.blocker_triage import logical_intent_id
            if not isinstance(self._blocker_gate, CommonPreWriteGate):
                raise ExecutionKernelError("untrusted native GitHub blocker gate")
            if not self._trusted_work_id or not self._trusted_head_sha:
                raise ExecutionKernelError("trusted native work/head identity missing")
            try:
                intent = logical_intent_id(
                    repository=plan.payload["repository"], branch="samuel/native-github",
                    work_id=self._trusted_work_id, paths=("github-native/" + action.value,),
                )
                self._blocker_gate.require_clear(
                    logical_intent_id=intent, expected_head_sha=self._trusted_head_sha,
                )
            except (KeyError, TypeError, ValueError, BlockerGateError) as exc:
                raise ExecutionKernelError(
                    "native mutation blocked by common prewrite gate"
                ) from exc

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
                # A thrown provider error is not proof that another provider
                # may safely retry this logical mutation. In particular the
                # source may be an upstream tool safety/policy rejection.
                # Do not wash it away as a 'provider unavailable' signal.
                raise ExecutionKernelError(
                    "mutation provider failure requires classification; "
                    "unverified alternate-provider fallback refused: "
                    + provider.name + ":" + type(exc).__name__
                ) from exc

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


def native_runtime_provider(name: str, transport) -> ExecutionProvider:
    """Adapt the repository native GitHub runtime into the sole execution kernel."""
    return ExecutionProvider(
        name=name,
        capabilities=frozenset(GitHubCapability),
        read_state=transport.read_state,
        mutate=transport.mutate,
    )
