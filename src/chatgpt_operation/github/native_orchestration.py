"""Closed-loop dispatcher for Samuel native GitHub ActionPlans."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from chatgpt_operation.controller.action_plan import ActionPlan, ExecutorKind
from chatgpt_operation.controller.action_lifecycle import DispatchIntent
from chatgpt_operation.controller.execution import ExecutionResult
from chatgpt_operation.github.actions_runtime import (
    GitHubActionsTransport,
    dispatch_and_wait,
    dispatch_workflow,
    observation_receipt_from_identity,
    observe_dispatch_once,
)


NATIVE_RUN_NAME_PREFIX = "Samuel Native GitHub Executor dispatch:"


class NativeOrchestrationError(RuntimeError):
    pass



def dispatch_native_plan_async(
    plan: ActionPlan,
    *,
    transport: GitHubActionsTransport,
    workflow: str = "samuel-native-github.yml",
    ref: str,
    recovery_state: str | None = None,
    recovery_authorization: dict[str, Any] | None = None,
    dispatch_id: str | None = None,
) -> dict[str, Any]:
    """Dispatch once and return a durable receipt without waiting for completion."""
    if plan.executor is not ExecutorKind.GITHUB_NATIVE:
        raise NativeOrchestrationError("only github_native plans may be dispatched")
    if plan.requires_escalation():
        raise NativeOrchestrationError("plan requires escalation before dispatch")
    correlation_id = dispatch_id or plan.idempotency_key
    if not isinstance(correlation_id, str) or not correlation_id.strip():
        raise NativeOrchestrationError("dispatch_id must be a non-empty string")
    inputs = {
        "samuel_action_id": plan.idempotency_key,
        "samuel_dispatch_id": correlation_id,
        "plan_json": json.dumps({
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
        }, sort_keys=True),
    }
    if recovery_state is not None and recovery_authorization is not None:
        inputs["recovery_state"] = recovery_state
        inputs["recovery_authorization"] = json.dumps(
            recovery_authorization, sort_keys=True, separators=(",", ":")
        )
    return dispatch_workflow(
        transport,
        workflow=workflow,
        ref=ref,
        inputs=inputs,
        correlation_id=correlation_id,
        correlation_input="samuel_dispatch_id",
        correlation_run_name_prefix=NATIVE_RUN_NAME_PREFIX,
    )


def observe_native_intent(
    plan: ActionPlan,
    intent: DispatchIntent,
    *,
    transport: GitHubActionsTransport,
    expected_head_sha: str | None = None,
    dispatch_id: str | None = None,
) -> dict[str, Any]:
    """Reconcile a pre-dispatch intent without issuing another dispatch."""
    if (
        plan.idempotency_key != intent.action_id
        or plan.research_id != intent.research_id
    ):
        raise NativeOrchestrationError("dispatch intent does not match ActionPlan")
    correlation_id = dispatch_id or intent.action_id
    receipt = observation_receipt_from_identity(
        transport,
        workflow=intent.workflow,
        ref=intent.ref,
        correlation_id=correlation_id,
        requested_at=intent.requested_at,
        correlation_input="samuel_dispatch_id",
        correlation_run_name_prefix=NATIVE_RUN_NAME_PREFIX,
    )
    observation = observe_dispatch_once(
        transport, receipt, expected_head_sha=expected_head_sha
    )
    matched = observation.get("matched_run_ids") or []
    bound_receipt = None
    if observation.get("status") in {"MATCHED_ACTIVE", "MATCHED_TERMINAL"}:
        if len(matched) != 1:
            raise NativeOrchestrationError("matched dispatch identity is not unique")
        bound_receipt = dict(receipt)
        bound_receipt["workflow_run_id"] = int(matched[0])
        bound_receipt["recovered_from_intent"] = True
    return {"observation": observation, "receipt": bound_receipt}


def observe_native_plan(
    plan: ActionPlan,
    receipt: dict[str, Any],
    *,
    transport: GitHubActionsTransport,
    expected_head_sha: str | None = None,
    dispatch_id: str | None = None,
) -> dict[str, Any]:
    """Observe a persisted dispatch once; never redispatch it."""
    expected_dispatch_id = dispatch_id or plan.idempotency_key
    if receipt.get("correlation_id") != expected_dispatch_id:
        raise NativeOrchestrationError("dispatch receipt does not match expected execution identity")
    return observe_dispatch_once(
        transport,
        receipt,
        expected_head_sha=expected_head_sha,
    )

def dispatch_native_plan(
    plan: ActionPlan,
    *,
    transport: GitHubActionsTransport,
    workflow: str = "samuel-native-github.yml",
    ref: str,
    expected_head_sha: str | None = None,
    timeout_seconds: float = 600,
    poll_interval_seconds: float = 5,
    recovery_state: str | None = None,
    recovery_authorization: dict[str, Any] | None = None,
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
        inputs={
            "plan_json": json.dumps({
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
            }, sort_keys=True),
            **(
                {
                    "recovery_state": recovery_state,
                    "recovery_authorization": json.dumps(
                        recovery_authorization, sort_keys=True, separators=(",", ":")
                    ),
                }
                if recovery_state is not None and recovery_authorization is not None
                else {}
            ),
        },
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
