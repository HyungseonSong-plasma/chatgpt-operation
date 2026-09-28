"""Deterministic execution gateway for root-issued Samuel commands."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .action_lifecycle import DispatchIntent
from .action_plan import ExecutorKind
from .command import ControllerCommand, ControllerCommandKind
from .diagnostic import (
    recovery_authorization_to_dict,
    resume_corrective_dispatch_intent,
    resume_diagnostic_dispatch_intent,
    resume_dispatched_action,
    resume_dispatched_corrective,
    resume_dispatched_diagnostic,
    resume_dispatched_evidence,
    resume_dispatch_intent,
    resume_evidence_dispatch_intent,
)
from .durable_state import encode_state
from .research import ResearchState
from chatgpt_operation.github.actions_runtime import (
    ActionsTransport,
    dispatch_workflow,
    observation_receipt_from_identity,
    observe_dispatch_once,
)
from chatgpt_operation.github.native_orchestration import (
    dispatch_native_plan_async,
    observe_native_intent,
    observe_native_plan,
)


class ExecutionGatewayError(RuntimeError):
    pass


class GatewayStatus(str, Enum):
    RECEIPT = "receipt"
    WAIT = "wait"
    TERMINAL = "terminal"


@dataclass(frozen=True)
class GatewayResult:
    surface: str
    action_id: str
    status: GatewayStatus
    receipt: dict[str, Any] | None = None
    observation: dict[str, Any] | None = None
    terminal_run_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "surface": self.surface,
            "action_id": self.action_id,
            "status": self.status.value,
            "receipt": self.receipt,
            "observation": self.observation,
            "terminal_run_id": self.terminal_run_id,
        }


def terminal_gateway_result_from_completed_run(
    gateway_result: dict[str, Any],
    completed_run: dict[str, Any],
) -> GatewayResult:
    """Bind a completed exact worker run to a typed terminal gateway result.

    Fresh dispatch commands return a bound RECEIPT before the worker is terminal.
    Once the trusted Bootstrap has polled that exact run to completion, this
    function performs the deterministic receipt -> terminal transition required
    by terminal ingestion. Existing TERMINAL results are revalidated and
    normalized through the same boundary.
    """
    required = {
        "schema_version", "surface", "action_id", "status",
        "receipt", "observation", "terminal_run_id",
    }
    if not isinstance(gateway_result, dict) or set(gateway_result) != required:
        raise ExecutionGatewayError("invalid gateway result schema")
    if gateway_result.get("schema_version") != 1:
        raise ExecutionGatewayError("unsupported gateway result schema_version")

    surface = gateway_result.get("surface")
    action_id = gateway_result.get("action_id")
    if surface not in {"action", "evidence", "diagnostic", "corrective"}:
        raise ExecutionGatewayError("gateway result has unsupported surface")
    if not isinstance(action_id, str) or not action_id:
        raise ExecutionGatewayError("gateway result action_id is missing")
    if not isinstance(completed_run, dict):
        raise ExecutionGatewayError("completed worker run must be an object")

    run_id = completed_run.get("id")
    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id < 1:
        raise ExecutionGatewayError("completed worker run id is invalid")
    if completed_run.get("status") != "completed":
        raise ExecutionGatewayError("worker run is not completed")
    if completed_run.get("event") != "workflow_dispatch":
        raise ExecutionGatewayError("worker run event is not workflow_dispatch")

    status = gateway_result.get("status")
    receipt = gateway_result.get("receipt")
    if status == GatewayStatus.RECEIPT.value:
        if not isinstance(receipt, dict):
            raise ExecutionGatewayError("receipt gateway result is missing receipt")
        if receipt.get("workflow_run_id") != run_id:
            raise ExecutionGatewayError("worker run id does not match bound receipt")
        workflow_id = receipt.get("workflow_id")
        observed_workflow_id = completed_run.get("workflow_id")
        if (
            isinstance(workflow_id, int)
            and isinstance(observed_workflow_id, int)
            and workflow_id != observed_workflow_id
        ):
            raise ExecutionGatewayError("worker workflow id does not match bound receipt")
        workflow_path = receipt.get("workflow_path")
        observed_path = completed_run.get("path")
        if (
            isinstance(workflow_path, str)
            and workflow_path
            and isinstance(observed_path, str)
            and observed_path
            and workflow_path != observed_path
        ):
            raise ExecutionGatewayError("worker workflow path does not match bound receipt")
    elif status == GatewayStatus.TERMINAL.value:
        if gateway_result.get("terminal_run_id") != run_id:
            raise ExecutionGatewayError("terminal gateway run id changed")
    else:
        raise ExecutionGatewayError(
            "only receipt or terminal gateway results can bind completed workers"
        )

    observation = {
        "status": "MATCHED_TERMINAL",
        "matched_run_ids": [run_id],
        "run_status": "completed",
        "conclusion": str(completed_run.get("conclusion") or ""),
    }
    head_sha = completed_run.get("head_sha")
    if isinstance(head_sha, str) and head_sha:
        observation["head_sha"] = head_sha
    path = completed_run.get("path")
    if isinstance(path, str) and path:
        observation["workflow_path"] = path

    return GatewayResult(
        surface=surface,
        action_id=action_id,
        status=GatewayStatus.TERMINAL,
        receipt=receipt if isinstance(receipt, dict) else None,
        observation=observation,
        terminal_run_id=run_id,
    )


class ExecutionGateway:
    """Only runtime boundary allowed to dispatch or observe controller workflows."""

    def __init__(self, transport: ActionsTransport):
        self.transport = transport

    @staticmethod
    def _validate_command(command: ControllerCommand, state: ResearchState) -> None:
        if command.research_id != state.research_id:
            raise ExecutionGatewayError("controller command belongs to another research state")
        if command.state_revision != state.revision:
            raise ExecutionGatewayError(
                f"stale controller command revision {command.state_revision} != {state.revision}"
            )

    def execute(
        self,
        command: ControllerCommand,
        *,
        state: ResearchState,
    ) -> GatewayResult:
        self._validate_command(command, state)
        dispatch = {
            ControllerCommandKind.DISPATCH_ACTION: self._dispatch_action,
            ControllerCommandKind.RECONCILE_ACTION: self._reconcile_action,
            ControllerCommandKind.OBSERVE_ACTION: self._observe_action,
            ControllerCommandKind.DISPATCH_EVIDENCE: self._dispatch_evidence,
            ControllerCommandKind.RECONCILE_EVIDENCE: self._reconcile_evidence,
            ControllerCommandKind.OBSERVE_EVIDENCE: self._observe_evidence,
            ControllerCommandKind.DISPATCH_DIAGNOSTIC: self._dispatch_diagnostic,
            ControllerCommandKind.RECONCILE_DIAGNOSTIC: self._reconcile_diagnostic,
            ControllerCommandKind.OBSERVE_DIAGNOSTIC: self._observe_diagnostic,
            ControllerCommandKind.DISPATCH_CORRECTIVE: self._dispatch_corrective,
            ControllerCommandKind.RECONCILE_CORRECTIVE: self._reconcile_corrective,
            ControllerCommandKind.OBSERVE_CORRECTIVE: self._observe_corrective,
        }
        try:
            handler = dispatch[command.kind]
        except KeyError as exc:
            raise ExecutionGatewayError("unsupported controller command") from exc
        return handler(state, command.action_id)

    @staticmethod
    def _action_prefix(plan) -> str:
        if plan.executor is ExecutorKind.GITHUB_NATIVE:
            return "Samuel Native GitHub Executor dispatch:"
        if plan.executor is ExecutorKind.REPOSITORY_MUTATION:
            return "Samuel Repository Mutation dispatch:"
        raise ExecutionGatewayError(
            "unsupported production action executor: " + plan.executor.value
        )

    def _dispatch_action_plan(
        self,
        plan,
        intent: DispatchIntent,
    ) -> dict[str, Any]:
        if plan.executor is ExecutorKind.GITHUB_NATIVE:
            return dispatch_native_plan_async(
                plan,
                transport=self.transport,
                ref=intent.ref,
                workflow=intent.workflow,
            )
        if plan.executor is ExecutorKind.REPOSITORY_MUTATION:
            payload={
                "schema_version":1,
                "research_id":plan.research_id,
                "stage":plan.stage.value,
                "executor":plan.executor.value,
                "payload":plan.payload,
                "expected_observation":plan.expected_observation,
                "decision_risk":None if plan.decision_risk is None else {
                    "impact":plan.decision_risk.impact,
                    "uncertainty":plan.decision_risk.uncertainty,
                    "irreversibility":plan.decision_risk.irreversibility,
                },
            }
            return dispatch_workflow(
                self.transport,
                workflow=intent.workflow,
                ref=intent.ref,
                inputs={
                    "samuel_action_id":plan.idempotency_key,
                    "samuel_dispatch_id":plan.idempotency_key,
                    "plan_json":__import__("json").dumps(
                        payload,sort_keys=True,separators=(",",":")
                    ),
                },
                correlation_id=plan.idempotency_key,
                correlation_input="samuel_dispatch_id",
                correlation_run_name_prefix=self._action_prefix(plan),
            )
        raise ExecutionGatewayError(
            "unsupported production action executor: " + plan.executor.value
        )

    def _dispatch_action(self, state: ResearchState, action_id: str) -> GatewayResult:
        plan, intent = resume_dispatch_intent(state, action_id)
        receipt = self._dispatch_action_plan(plan, intent)
        if isinstance(receipt.get("workflow_run_id"), int):
            return GatewayResult("action", action_id, GatewayStatus.RECEIPT, receipt=receipt)
        return GatewayResult("action", action_id, GatewayStatus.WAIT)

    def _reconcile_action(self, state: ResearchState, action_id: str) -> GatewayResult:
        plan, intent = resume_dispatch_intent(state, action_id)
        if plan.executor is ExecutorKind.GITHUB_NATIVE:
            reconciled = observe_native_intent(
                plan,
                intent,
                transport=self.transport,
                expected_head_sha=intent.expected_head_sha,
            )
            observation = reconciled["observation"]
            bound = reconciled.get("receipt")
        elif plan.executor is ExecutorKind.REPOSITORY_MUTATION:
            receipt = observation_receipt_from_identity(
                self.transport,
                workflow=intent.workflow,
                ref=intent.ref,
                correlation_id=plan.idempotency_key,
                requested_at=intent.requested_at,
                correlation_input="samuel_dispatch_id",
                correlation_run_name_prefix=self._action_prefix(plan),
            )
            observation = observe_dispatch_once(
                self.transport,
                receipt,
                expected_head_sha=intent.expected_head_sha,
            )
            matched=observation.get("matched_run_ids") or []
            bound=None
            if observation.get("status") in {"MATCHED_ACTIVE","MATCHED_TERMINAL"}:
                if len(matched)!=1:
                    raise ExecutionGatewayError(
                        "matched repository mutation dispatch is not unique"
                    )
                bound=dict(receipt)
                bound["workflow_run_id"]=int(matched[0])
                bound["recovered_from_intent"]=True
        else:
            raise ExecutionGatewayError(
                "unsupported production action executor: " + plan.executor.value
            )
        if bound is not None:
            return GatewayResult(
                "action", action_id, GatewayStatus.RECEIPT,
                receipt=bound, observation=observation,
            )
        status = observation.get("status")
        if status in {"PENDING_VISIBILITY", "OBSERVATION_INCOMPLETE"}:
            return GatewayResult(
                "action", action_id, GatewayStatus.WAIT, observation=observation
            )
        if status == "NO_MATCH":
            receipt = self._dispatch_action_plan(plan, intent)
            if isinstance(receipt.get("workflow_run_id"), int):
                return GatewayResult(
                    "action", action_id, GatewayStatus.RECEIPT,
                    receipt=receipt, observation=observation,
                )
            return GatewayResult(
                "action", action_id, GatewayStatus.WAIT, observation=observation
            )
        raise ExecutionGatewayError(
            "action intent observation cannot continue: " + str(status)
        )

    def _observe_action(self, state: ResearchState, action_id: str) -> GatewayResult:
        plan, receipt = resume_dispatched_action(state, action_id)
        intent = DispatchIntent.from_dict(
            state.action_queue[action_id].get("dispatch_intent")
        )
        observation = observe_native_plan(
            plan,
            receipt,
            transport=self.transport,
            expected_head_sha=intent.expected_head_sha,
        )
        status = observation.get("status")
        if status == "MATCHED_TERMINAL":
            run_id = receipt.get("workflow_run_id")
            if not isinstance(run_id, int):
                raise ExecutionGatewayError("dispatched action lost workflow run identity")
            return GatewayResult(
                "action", action_id, GatewayStatus.TERMINAL,
                observation=observation, terminal_run_id=run_id,
            )
        if status == "BOUND_RUN_IDENTITY_MISMATCH":
            run_id = receipt.get("workflow_run_id")
            if not isinstance(run_id, int):
                raise ExecutionGatewayError(
                    "bound action mismatch lost workflow run identity"
                )
            if observation.get("run_status") == "completed":
                return GatewayResult(
                    "action", action_id, GatewayStatus.TERMINAL,
                    observation=observation, terminal_run_id=run_id,
                )
            return GatewayResult(
                "action", action_id, GatewayStatus.WAIT,
                observation=observation,
            )
        if status in {
            "MATCHED_ACTIVE", "PENDING_VISIBILITY", "NO_MATCH",
            "OBSERVATION_INCOMPLETE",
        }:
            return GatewayResult(
                "action", action_id, GatewayStatus.WAIT, observation=observation
            )
        raise ExecutionGatewayError("unsupported action observation: " + str(status))

    def _dispatch_corrective(
        self, state: ResearchState, action_id: str
    ) -> GatewayResult:
        plan, authorization, intent, correlation_id = (
            resume_corrective_dispatch_intent(state, action_id)
        )
        receipt = dispatch_native_plan_async(
            plan,
            transport=self.transport,
            ref=intent.ref,
            workflow=intent.workflow,
            recovery_state=encode_state(state),
            recovery_authorization=recovery_authorization_to_dict(authorization),
            dispatch_id=correlation_id,
        )
        if isinstance(receipt.get("workflow_run_id"), int):
            return GatewayResult(
                "corrective", action_id, GatewayStatus.RECEIPT, receipt=receipt
            )
        return GatewayResult("corrective", action_id, GatewayStatus.WAIT)

    def _reconcile_corrective(
        self, state: ResearchState, action_id: str
    ) -> GatewayResult:
        plan, authorization, intent, correlation_id = (
            resume_corrective_dispatch_intent(state, action_id)
        )
        reconciled = observe_native_intent(
            plan,
            intent,
            transport=self.transport,
            expected_head_sha=intent.expected_head_sha,
            dispatch_id=correlation_id,
        )
        observation = reconciled["observation"]
        bound = reconciled.get("receipt")
        if bound is not None:
            return GatewayResult(
                "corrective", action_id, GatewayStatus.RECEIPT,
                receipt=bound, observation=observation,
            )
        status = observation.get("status")
        if status in {"PENDING_VISIBILITY", "OBSERVATION_INCOMPLETE"}:
            return GatewayResult(
                "corrective", action_id, GatewayStatus.WAIT,
                observation=observation,
            )
        if status == "NO_MATCH":
            receipt = dispatch_native_plan_async(
                plan,
                transport=self.transport,
                ref=intent.ref,
                workflow=intent.workflow,
                recovery_state=encode_state(state),
                recovery_authorization=recovery_authorization_to_dict(authorization),
                dispatch_id=correlation_id,
            )
            if isinstance(receipt.get("workflow_run_id"), int):
                return GatewayResult(
                    "corrective", action_id, GatewayStatus.RECEIPT,
                    receipt=receipt, observation=observation,
                )
            return GatewayResult(
                "corrective", action_id, GatewayStatus.WAIT,
                observation=observation,
            )
        raise ExecutionGatewayError(
            "corrective intent observation cannot continue: " + str(status)
        )

    def _observe_corrective(
        self, state: ResearchState, action_id: str
    ) -> GatewayResult:
        plan, _authorization, intent, correlation_id, receipt = (
            resume_dispatched_corrective(state, action_id)
        )
        observation = observe_native_plan(
            plan,
            receipt,
            transport=self.transport,
            expected_head_sha=intent.expected_head_sha,
            dispatch_id=correlation_id,
        )
        status = observation.get("status")
        if status == "MATCHED_TERMINAL":
            run_id = receipt.get("workflow_run_id")
            if not isinstance(run_id, int):
                raise ExecutionGatewayError(
                    "dispatched corrective lost workflow run identity"
                )
            return GatewayResult(
                "corrective", action_id, GatewayStatus.TERMINAL,
                observation=observation, terminal_run_id=run_id,
            )
        if status in {
            "MATCHED_ACTIVE", "PENDING_VISIBILITY", "NO_MATCH",
            "OBSERVATION_INCOMPLETE",
        }:
            return GatewayResult(
                "corrective", action_id, GatewayStatus.WAIT,
                observation=observation,
            )
        raise ExecutionGatewayError(
            "unsupported corrective observation: " + str(status)
        )

    def _generic_dispatch(
        self,
        *,
        surface: str,
        state: ResearchState,
        action_id: str,
    ) -> GatewayResult:
        if surface == "evidence":
            intent, correlation_id = resume_evidence_dispatch_intent(state, action_id)
            prefix = "Samuel Evidence Acquisition dispatch:"
            recovery_payload = {
                "kind": "evidence",
                "action_id": action_id,
                "recovery": state.diagnostic_recoveries[action_id],
            }
        elif surface == "diagnostic":
            intent, correlation_id = resume_diagnostic_dispatch_intent(state, action_id)
            prefix = "Samuel Diagnostic Recovery dispatch:"
            recovery_payload = {
                "kind": "diagnostic",
                "action_id": action_id,
                "recovery": state.diagnostic_recoveries[action_id],
            }
        else:
            raise ExecutionGatewayError("unsupported workflow surface")
        receipt = dispatch_workflow(
            self.transport,
            workflow=intent.workflow,
            ref=intent.ref,
            inputs={
                "samuel_dispatch_id": correlation_id,
                "recovery_json": __import__("json").dumps(
                    recovery_payload, sort_keys=True, separators=(",", ":")
                ),
                "controller_state": encode_state(state),
            },
            correlation_id=correlation_id,
            correlation_input="samuel_dispatch_id",
            correlation_run_name_prefix=prefix,
        )
        if isinstance(receipt.get("workflow_run_id"), int):
            return GatewayResult(surface, action_id, GatewayStatus.RECEIPT, receipt=receipt)
        return GatewayResult(surface, action_id, GatewayStatus.WAIT)

    def _dispatch_evidence(self, state: ResearchState, action_id: str) -> GatewayResult:
        return self._generic_dispatch(surface="evidence", state=state, action_id=action_id)

    def _dispatch_diagnostic(self, state: ResearchState, action_id: str) -> GatewayResult:
        return self._generic_dispatch(surface="diagnostic", state=state, action_id=action_id)

    def _generic_reconcile(
        self,
        *,
        surface: str,
        state: ResearchState,
        action_id: str,
    ) -> GatewayResult:
        if surface == "evidence":
            intent, correlation_id = resume_evidence_dispatch_intent(state, action_id)
            prefix = "Samuel Evidence Acquisition dispatch:"
        elif surface == "diagnostic":
            intent, correlation_id = resume_diagnostic_dispatch_intent(state, action_id)
            prefix = "Samuel Diagnostic Recovery dispatch:"
        else:
            raise ExecutionGatewayError("unsupported workflow surface")
        receipt = observation_receipt_from_identity(
            self.transport,
            workflow=intent.workflow,
            ref=intent.ref,
            correlation_id=correlation_id,
            requested_at=intent.requested_at,
            correlation_input="samuel_dispatch_id",
            correlation_run_name_prefix=prefix,
        )
        observation = observe_dispatch_once(
            self.transport,
            receipt,
            expected_head_sha=intent.expected_head_sha,
        )
        status = observation.get("status")
        matched = observation.get("matched_run_ids") or []
        if status in {"MATCHED_ACTIVE", "MATCHED_TERMINAL"}:
            if len(matched) != 1:
                raise ExecutionGatewayError(
                    f"ambiguous recovered {surface} workflow run"
                )
            if (
                surface == "evidence"
                and status == "MATCHED_TERMINAL"
                and observation.get("conclusion") != "success"
            ):
                raise ExecutionGatewayError(
                    "evidence acquisition workflow failed: "
                    + str(observation.get("conclusion"))
                )
            receipt = dict(receipt)
            receipt["workflow_run_id"] = int(matched[0])
            receipt["recovered_from_intent"] = True
            return GatewayResult(
                surface, action_id, GatewayStatus.RECEIPT,
                receipt=receipt, observation=observation,
            )
        if status in {"PENDING_VISIBILITY", "OBSERVATION_INCOMPLETE"}:
            return GatewayResult(
                surface, action_id, GatewayStatus.WAIT, observation=observation
            )
        if status == "NO_MATCH" and surface == "diagnostic":
            return self._generic_dispatch(
                surface=surface, state=state, action_id=action_id
            )
        if status == "NO_MATCH":
            return GatewayResult(
                surface, action_id, GatewayStatus.WAIT, observation=observation
            )
        raise ExecutionGatewayError(
            f"{surface} intent observation cannot continue: {status}"
        )

    def _reconcile_evidence(self, state: ResearchState, action_id: str) -> GatewayResult:
        return self._generic_reconcile(surface="evidence", state=state, action_id=action_id)

    def _reconcile_diagnostic(self, state: ResearchState, action_id: str) -> GatewayResult:
        return self._generic_reconcile(surface="diagnostic", state=state, action_id=action_id)

    def _generic_observe(
        self,
        *,
        surface: str,
        state: ResearchState,
        action_id: str,
    ) -> GatewayResult:
        if surface == "evidence":
            intent, _correlation_id, receipt = resume_dispatched_evidence(state, action_id)
        elif surface == "diagnostic":
            intent, _correlation_id, receipt = resume_dispatched_diagnostic(state, action_id)
        else:
            raise ExecutionGatewayError("unsupported workflow surface")
        observation = observe_dispatch_once(
            self.transport,
            receipt,
            expected_head_sha=intent.expected_head_sha,
        )
        status = observation.get("status")
        if status != "MATCHED_TERMINAL":
            return GatewayResult(
                surface, action_id, GatewayStatus.WAIT, observation=observation
            )
        matched = observation.get("matched_run_ids") or (
            [receipt.get("workflow_run_id")] if receipt.get("workflow_run_id") else []
        )
        if len(matched) != 1 or int(matched[0]) != int(receipt["workflow_run_id"]):
            raise ExecutionGatewayError(
                f"{surface} terminal workflow identity mismatch"
            )
        if surface == "evidence" and observation.get("conclusion") != "success":
            raise ExecutionGatewayError(
                "evidence acquisition workflow failed: "
                + str(observation.get("conclusion"))
            )
        return GatewayResult(
            surface, action_id, GatewayStatus.TERMINAL,
            observation=observation, terminal_run_id=int(matched[0]),
        )

    def _observe_evidence(self, state: ResearchState, action_id: str) -> GatewayResult:
        return self._generic_observe(surface="evidence", state=state, action_id=action_id)

    def _observe_diagnostic(self, state: ResearchState, action_id: str) -> GatewayResult:
        return self._generic_observe(surface="diagnostic", state=state, action_id=action_id)
