"""Adapter from controller ActionPlan objects to GitHub Actions route planning."""
from __future__ import annotations

from typing import Any

from chatgpt_operation.controller.action_plan import (
    ActionPlan,
    ActionPlanError,
    ExecutorKind,
)
from chatgpt_operation.github.actions_execution import (
    ActionsExecutionError,
    evaluate,
)


def plan_github_actions(plan: ActionPlan) -> dict[str, Any]:
    """Validate and route a GitHub-Actions ActionPlan.

    Route precedence, authorization, observability, boundedness, and repository
    mutation requirements remain authoritative in github.actions_execution.
    """
    if plan.executor is not ExecutorKind.GITHUB_ACTIONS:
        raise ActionPlanError(
            f"executor {plan.executor.value} cannot be handled by GitHub Actions"
        )
    if plan.requires_escalation():
        raise ActionPlanError("action plan requires escalation before execution")

    try:
        return evaluate(plan.payload)
    except ActionsExecutionError as exc:
        raise ActionPlanError(f"invalid GitHub Actions payload: {exc}") from exc
