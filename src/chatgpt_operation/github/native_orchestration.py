"""Closed-loop dispatcher for Samuel native GitHub ActionPlans."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from chatgpt_operation.controller.action_plan import ActionPlan, ExecutorKind
from chatgpt_operation.controller.execution import ExecutionResult
from chatgpt_operation.github.actions_runtime import GitHubActionsTransport, dispatch_and_wait


class NativeOrchestrationError(RuntimeError):
    pass


def dispatch_native_plan(
    plan: ActionPlan,
    *,
    transport: GitHubActionsTransport,
    workflow: str = "samuel-native-github.yml",
    ref: str,
    expected_head_sha: str | None = None,
    timeout_seconds: float = 600,
    poll_interval_seconds: float = 5,
) -> dict[str, Any]:
    if plan.executor is not ExecutorKind.GITHUB_NATIVE:
        raise NativeOrchestrationError("only github_native plans may be dispatched")
    if plan.requires_escalation():
        raise NativeOrchestrationError("plan requires escalation before dispatch")

    correlation_id=plan.idempotency_key
    outcome=dispatch_and_wait(
        transport,
        workflow=workflow,
        ref=ref,
        inputs={"plan_json": json.dumps({
            "schema_version": 1,
            "research_id": plan.research_id,
            "stage": plan.stage.value,
            "executor": plan.executor.value,
            "payload": plan.payload,
            "expected_observation": plan.expected_observation,
            "decision_risk": None if plan.decision_risk is None else {
                "impact": plan.decision_risk.impact,
                "uncertainty": plan.decision_risk.uncertainty,
                "irreversibility": plan.decision_risk.irreversibility,
            },
        }, sort_keys=True)},
        correlation_id=correlation_id,
        correlation_input=None,
        expected_head_sha=expected_head_sha,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    observation=outcome["observation"]
    if observation.get("status") != "MATCHED_TERMINAL":
        raise NativeOrchestrationError(
            "native executor workflow did not reach one verified terminal run: "
            + str(observation.get("status"))
        )
    if observation.get("conclusion") != "success":
        raise NativeOrchestrationError(
            "native executor workflow failed: " + str(observation.get("conclusion"))
        )
    return outcome


def load_execution_result(path: str | Path, *, expected_plan: ActionPlan) -> ExecutionResult:
    raw=json.loads(Path(path).read_text(encoding="utf-8"))
    result=ExecutionResult.from_dict(raw)
    if result.action_id != expected_plan.idempotency_key:
        raise NativeOrchestrationError("execution result action_id does not match dispatched plan")
    if result.research_id != expected_plan.research_id:
        raise NativeOrchestrationError("execution result research_id does not match dispatched plan")
    if result.executor is not ExecutorKind.GITHUB_NATIVE:
        raise NativeOrchestrationError("execution result came from the wrong executor")
    return result
