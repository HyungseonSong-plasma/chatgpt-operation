"""Evidence-based execution-authority classification for Samuel."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from chatgpt_operation.controller.action_plan import ExecutorKind
from chatgpt_operation.github.native_executor import NativeGitHubAction


class AuthorityError(ValueError):
    pass


class AuthorityOutcome(str, Enum):
    ROUTE_TO_EXECUTOR = "route_to_executor"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class AuthorityEvidence:
    executor: ExecutorKind
    action: NativeGitHubAction
    executor_implemented: bool
    runtime_available: bool
    permission_denial_status: int | None = None


@dataclass(frozen=True)
class AuthorityDecision:
    outcome: AuthorityOutcome
    reason: str


def classify_execution_authority(evidence: AuthorityEvidence) -> AuthorityDecision:
    """Never infer global authority from a frontend/connector mutation refusal."""
    if evidence.executor is not ExecutorKind.GITHUB_NATIVE:
        raise AuthorityError("authority classifier only governs github_native actions")
    if not evidence.executor_implemented:
        return AuthorityDecision(AuthorityOutcome.BLOCKED, "native executor is not implemented")
    if not evidence.runtime_available:
        return AuthorityDecision(AuthorityOutcome.BLOCKED, "native executor runtime is unavailable")
    if evidence.permission_denial_status in {401, 403}:
        return AuthorityDecision(
            AuthorityOutcome.BLOCKED,
            f"native executor returned verified HTTP {evidence.permission_denial_status}",
        )
    if evidence.permission_denial_status is not None:
        raise AuthorityError("permission denial evidence must be HTTP 401/403 or null")
    return AuthorityDecision(
        AuthorityOutcome.ROUTE_TO_EXECUTOR,
        f"route {evidence.action.value} through github_native executor",
    )
