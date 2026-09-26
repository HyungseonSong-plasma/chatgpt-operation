"""Adapter from controller ActionPlan objects to repository mutation manifests."""
from __future__ import annotations

from chatgpt_operation.controller.action_plan import (
    ActionPlan,
    ActionPlanError,
    ExecutorKind,
)
from chatgpt_operation.repository.mutation import Manifest, ManifestError, parse_manifest


def to_repository_manifest(
    plan: ActionPlan,
    *,
    expected_repository: str | None = None,
) -> Manifest:
    """Validate and translate a repository-mutation ActionPlan.

    Repository policy enforcement and stale-state checks remain authoritative in
    repository.mutation.Engine. This adapter only validates the typed boundary
    and reuses the existing closed-world mutation manifest contract.
    """
    if plan.executor is not ExecutorKind.REPOSITORY_MUTATION:
        raise ActionPlanError(
            f"executor {plan.executor.value} cannot be handled by repository mutation"
        )
    if plan.requires_escalation():
        raise ActionPlanError("action plan requires escalation before execution")

    try:
        manifest = parse_manifest(plan.payload)
    except ManifestError as exc:
        raise ActionPlanError(f"invalid repository mutation payload: {exc}") from exc

    if expected_repository is not None and manifest.repository != expected_repository:
        raise ActionPlanError(
            f"repository mismatch: expected {expected_repository}, got {manifest.repository}"
        )
    return manifest


def repository_operation_id(
    plan: ActionPlan,
    *,
    expected_repository: str | None = None,
) -> str:
    """Return the existing mutation engine's semantic operation identity."""
    return to_repository_manifest(
        plan, expected_repository=expected_repository
    ).operation_id
