"""Typed terminal artifact ingestion into Samuel durable state."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import copy
import json
from typing import Any

from .diagnostic import record_native_dispatch_evidence_failure
from .durable_state import (
    apply_action_completion,
    apply_action_failure,
    apply_corrective_execution_result,
    apply_diagnostic_patch,
    apply_evidence_patch,
)
from .execution import ExecutionResult, ExecutionStatus
from .research import ResearchState


class TerminalIngestionError(ValueError):
    pass


class TerminalSurface(str, Enum):
    ACTION = "action"
    EVIDENCE = "evidence"
    DIAGNOSTIC = "diagnostic"
    CORRECTIVE = "corrective"


class TerminalIngestionOutcome(str, Enum):
    APPLIED = "applied"
    NOOP = "noop"
    RECOVERED_INVALID_EVIDENCE = "recovered_invalid_evidence"


@dataclass(frozen=True)
class TerminalIngestionResult:
    surface: TerminalSurface
    action_id: str
    run_id: int
    outcome: TerminalIngestionOutcome
    proposed_state: ResearchState | None

    @property
    def changed(self) -> bool:
        return self.proposed_state is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "surface": self.surface.value,
            "action_id": self.action_id,
            "run_id": self.run_id,
            "outcome": self.outcome.value,
            "changed": self.changed,
        }


def _gateway_identity(
    gateway_result: dict[str, Any],
    *,
    surface: TerminalSurface,
    run_id: int,
) -> str:
    if not isinstance(gateway_result, dict) or gateway_result.get("schema_version") != 1:
        raise TerminalIngestionError("invalid execution gateway result schema")
    if gateway_result.get("status") != "terminal":
        raise TerminalIngestionError("gateway result is not terminal")
    if gateway_result.get("surface") != surface.value:
        raise TerminalIngestionError("terminal surface does not match gateway result")
    if gateway_result.get("terminal_run_id") != run_id:
        raise TerminalIngestionError("terminal run_id does not match gateway result")
    action_id = gateway_result.get("action_id")
    if not isinstance(action_id, str) or not action_id:
        raise TerminalIngestionError("gateway terminal action_id is missing")
    return action_id


def _parse_json_artifact(text: str, *, surface: TerminalSurface) -> dict[str, Any]:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TerminalIngestionError(
            f"{surface.value} terminal artifact is invalid JSON"
        ) from exc
    if not isinstance(raw, dict):
        raise TerminalIngestionError(
            f"{surface.value} terminal artifact must be an object"
        )
    return raw


def ingest_terminal_artifact(
    current: ResearchState,
    *,
    surface: TerminalSurface,
    run_id: int,
    artifact_text: str,
    gateway_result: dict[str, Any],
) -> TerminalIngestionResult:
    """Convert one causally bound terminal artifact into a proposed durable state."""
    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id < 1:
        raise TerminalIngestionError("terminal run_id must be positive")
    action_id = _gateway_identity(
        gateway_result, surface=surface, run_id=run_id
    )

    if surface is TerminalSurface.ACTION:
        try:
            raw = json.loads(artifact_text)
        except json.JSONDecodeError:
            observation = gateway_result.get("observation")
            conclusion = (
                str(observation.get("conclusion") or "unknown")
                if isinstance(observation, dict)
                else "unknown"
            )
            proposed = copy.deepcopy(current)
            record_native_dispatch_evidence_failure(
                proposed,
                action_id,
                workflow_run_id=run_id,
                conclusion=conclusion,
                failure_kind="invalid_execution_result_json",
            )
            return TerminalIngestionResult(
                surface,
                action_id,
                run_id,
                TerminalIngestionOutcome.RECOVERED_INVALID_EVIDENCE,
                proposed,
            )
        if not isinstance(raw, dict):
            raise TerminalIngestionError("action terminal artifact must be an object")
        result = ExecutionResult.from_dict(raw)
        if result.action_id != action_id:
            raise TerminalIngestionError(
                "action artifact identity does not match gateway terminal"
            )
        item = current.action_queue.get(action_id)
        if isinstance(item, dict) and item.get("status") == "complete":
            if item.get("completion_result") != raw:
                raise TerminalIngestionError("conflicting action completion replay")
            return TerminalIngestionResult(
                surface, action_id, run_id, TerminalIngestionOutcome.NOOP, None
            )
        if result.status in {ExecutionStatus.PASS, ExecutionStatus.NOOP}:
            proposed = apply_action_completion(current, result)
        elif result.status is ExecutionStatus.FAILED:
            proposed = apply_action_failure(current, result)
        else:
            raise TerminalIngestionError(
                "unsupported terminal execution status " + result.status.value
            )
        return TerminalIngestionResult(
            surface, action_id, run_id, TerminalIngestionOutcome.APPLIED, proposed
        )

    if surface is TerminalSurface.CORRECTIVE:
        raw = _parse_json_artifact(artifact_text, surface=surface)
        result = ExecutionResult.from_dict(raw)
        if result.action_id != action_id:
            raise TerminalIngestionError(
                "corrective artifact identity does not match gateway terminal"
            )
        proposed = apply_corrective_execution_result(
            current, action_id, result
        )
        return TerminalIngestionResult(
            surface, action_id, run_id, TerminalIngestionOutcome.APPLIED, proposed
        )

    raw = _parse_json_artifact(artifact_text, surface=surface)
    if raw.get("action_id") != action_id:
        raise TerminalIngestionError(
            f"{surface.value} artifact identity does not match gateway terminal"
        )
    provenance = raw.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("workflow_run_id") != run_id:
        raise TerminalIngestionError(
            f"{surface.value} artifact run identity mismatch"
        )

    if surface is TerminalSurface.EVIDENCE:
        proposed = apply_evidence_patch(current, raw)
    else:
        if raw.get("advanced") is not True:
            raise TerminalIngestionError("diagnostic artifact did not advance")
        proposed = apply_diagnostic_patch(current, raw)
    return TerminalIngestionResult(
        surface, action_id, run_id, TerminalIngestionOutcome.APPLIED, proposed
    )
