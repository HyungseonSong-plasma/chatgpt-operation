"""Durable Samuel controller state encoded in the Issue #44 ledger."""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from .research import ResearchState

STATE_MARKER = "<!-- samuel-controller-state -->"
STATE_SCHEMA_VERSION = 2


class DurableStateError(ValueError):
    pass


def encode_state(state: ResearchState) -> str:
    payload = asdict(state)
    payload["stage"] = state.stage.value
    envelope = {
        "schema_version": STATE_SCHEMA_VERSION,
        "research_id": state.research_id,
        "revision": state.revision,
        "state": payload,
    }
    return STATE_MARKER + "\n```json\n" + json.dumps(
        envelope, sort_keys=True, separators=(",", ":")
    ) + "\n```"


def decode_state(body: str) -> ResearchState:
    if STATE_MARKER not in body:
        raise DurableStateError("controller state marker missing")
    start = body.find("```json")
    end = body.find("```", start + 7)
    if start < 0 or end < 0:
        raise DurableStateError("controller state JSON fence missing")
    try:
        envelope = json.loads(body[start + 7:end].strip())
    except json.JSONDecodeError as exc:
        raise DurableStateError("controller state JSON is invalid") from exc
    if envelope.get("schema_version") not in {1, STATE_SCHEMA_VERSION}:
        raise DurableStateError("unsupported controller state schema")
    raw = envelope.get("state")
    if not isinstance(raw, dict):
        raise DurableStateError("controller state payload missing")
    if envelope.get("research_id") != raw.get("research_id"):
        raise DurableStateError("controller state research_id mismatch")
    if envelope.get("revision") != raw.get("revision"):
        raise DurableStateError("controller state revision mismatch")
    return ResearchState(
        research_id=raw["research_id"],
        objective=raw["objective"],
        stage=__import__(
            "chatgpt_operation.controller.research", fromlist=["ResearchStage"]
        ).ResearchStage(raw["stage"]),
        completed_operation_ids=list(raw.get("completed_operation_ids", [])),
        execution_results=dict(raw.get("execution_results", {})),
        diagnostic_recoveries=dict(raw.get("diagnostic_recoveries", {})),
        action_queue=dict(raw.get("action_queue", {})),
        revision=int(raw.get("revision", 0)),
    )


def require_fresh_write(current: ResearchState | None, proposed: ResearchState) -> None:
    """Reject stale or cross-research ledger replacement."""
    if current is None:
        return
    if current.research_id != proposed.research_id:
        raise DurableStateError("cannot overwrite a different research state")
    if proposed.revision <= current.revision:
        raise DurableStateError(
            f"stale controller state revision {proposed.revision} <= {current.revision}"
        )


def find_state_comment(comments: list[dict[str, Any]]) -> dict[str, Any] | None:
    matches = [
        item for item in comments
        if STATE_MARKER in str(item.get("body", ""))
    ]
    if len(matches) > 1:
        raise DurableStateError("multiple authoritative controller state comments")
    return matches[0] if matches else None


def load_state_comment(comments: list[dict[str, Any]]) -> ResearchState | None:
    comment = find_state_comment(comments)
    return None if comment is None else decode_state(str(comment["body"]))


def state_write_request(
    comments: list[dict[str, Any]],
    proposed: ResearchState,
) -> dict[str, Any]:
    """Return a transport-neutral create/update request for the durable state ledger."""
    write = prepare_state_write(comments, proposed)
    comment_id = write["comment_id"]
    return {
        "method": "POST" if comment_id is None else "PATCH",
        "comment_id": comment_id,
        "body": write["body"],
        "expected_previous_revision": write["expected_previous_revision"],
        "expected_revision": proposed.revision,
        "research_id": proposed.research_id,
    }


def prepare_state_write(
    comments: list[dict[str, Any]],
    proposed: ResearchState,
) -> dict[str, Any]:
    """Prepare deterministic create/update data after optimistic revision check."""
    comment = find_state_comment(comments)
    current = None if comment is None else decode_state(str(comment["body"]))
    require_fresh_write(current, proposed)
    return {
        "comment_id": None if comment is None else int(comment["id"]),
        "body": encode_state(proposed),
        "expected_previous_revision": None if current is None else current.revision,
    }


def validate_state_write_precondition(
    comments: list[dict[str, Any]],
    request: dict[str, Any],
) -> None:
    """Re-read authoritative state immediately before a transport write."""
    required = {
        "method", "comment_id", "body", "expected_previous_revision",
        "expected_revision", "research_id",
    }
    if not isinstance(request, dict) or set(request) != required:
        raise DurableStateError("invalid durable state write request schema")
    proposed = decode_state(str(request["body"]))
    if (
        proposed.research_id != request["research_id"]
        or proposed.revision != request["expected_revision"]
    ):
        raise DurableStateError("durable state write request payload mismatch")

    comment = find_state_comment(comments)
    current = None if comment is None else decode_state(str(comment["body"]))
    expected_previous = request["expected_previous_revision"]
    if current is None:
        if expected_previous is not None:
            raise DurableStateError("stale durable state create precondition")
        if request["method"] != "POST" or request["comment_id"] is not None:
            raise DurableStateError("durable state create request is inconsistent")
        return

    if expected_previous is None:
        raise DurableStateError("stale durable state create precondition")
    if request["method"] != "PATCH" or request["comment_id"] != int(comment["id"]):
        raise DurableStateError("durable state update target changed")
    if current.research_id != proposed.research_id:
        raise DurableStateError("cannot overwrite a different research state")
    if expected_previous != current.revision:
        raise DurableStateError(
            f"stale durable state precondition {expected_previous} != {current.revision}"
        )
    if proposed.revision <= current.revision:
        raise DurableStateError("durable state revision did not advance")


def apply_diagnostic_patch(
    current: ResearchState,
    artifact: dict[str, Any],
) -> ResearchState:
    """Apply one diagnostic artifact to the authoritative state without whole-state replacement."""
    action_id = artifact.get("action_id")
    if not isinstance(action_id, str) or action_id not in current.diagnostic_recoveries:
        raise DurableStateError("diagnostic patch action is not present in current state")
    if artifact.get("revision_delta") != 1 or artifact.get("advanced") is not True:
        raise DurableStateError("diagnostic patch must represent exactly one advanced revision")
    patched = artifact.get("recovery")
    if not isinstance(patched, dict):
        raise DurableStateError("diagnostic patch recovery payload missing")
    before = current.diagnostic_recoveries[action_id]
    if before.get("status") != "open":
        raise DurableStateError("diagnostic patch target is not open")
    proposed = ResearchState(
        research_id=current.research_id,
        objective=current.objective,
        stage=current.stage,
        completed_operation_ids=list(current.completed_operation_ids),
        execution_results=dict(current.execution_results),
        diagnostic_recoveries=dict(current.diagnostic_recoveries),
        action_queue=dict(current.action_queue),
        revision=current.revision + 1,
    )
    proposed.diagnostic_recoveries[action_id] = dict(patched)
    return proposed


def apply_action_completion(current: ResearchState, result) -> ResearchState:
    """Apply one verified queued-action completion as a single durable revision."""
    from chatgpt_operation.controller.diagnostic import complete_queued_action
    import copy
    proposed = copy.deepcopy(current)
    before = proposed.revision
    complete_queued_action(proposed, result.action_id, result)
    if proposed.revision != before + 1:
        raise DurableStateError("action completion must advance exactly one revision")
    return proposed


def apply_action_failure(current: ResearchState, result) -> ResearchState:
    """Record typed failure; repeated identical retryable failure opens diagnosis."""
    from chatgpt_operation.controller.execution import (
        ExecutionStatus, open_diagnostic_recovery, record_execution_result,
        require_execution_provenance,
    )
    from chatgpt_operation.controller.diagnostic import (
        attach_source_plan, mark_action_suspended,
    )
    from chatgpt_operation.controller.action_plan import ActionPlan
    import copy, json, hashlib
    if result.status is not ExecutionStatus.FAILED:
        raise DurableStateError("failure governance requires FAILED execution evidence")
    item = current.action_queue.get(result.action_id)
    if item is None or item.get("status") != "dispatched":
        raise DurableStateError("failed action is not dispatched in durable queue")
    receipt = item.get("dispatch_receipt")
    run_id = None if not isinstance(receipt, dict) else receipt.get("workflow_run_id")
    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id < 1:
        raise DurableStateError("failed action has no authoritative workflow_run_id")
    from chatgpt_operation.controller.action_lifecycle import DispatchIntent
    intent = DispatchIntent.from_dict(item.get("dispatch_intent"))
    require_execution_provenance(
        result,
        workflow_run_id=run_id,
        head_sha=intent.expected_head_sha,
    )
    proposed = copy.deepcopy(current)
    previous = proposed.execution_results.get(result.action_id)
    record_execution_result(proposed, result)
    semantic = {
        "executor": result.executor.value,
        "observation": result.observation,
        "provider": result.details.get("provider"),
        "error_type": result.details.get("error_type"),
        "provider_status": result.details.get("provider_status"),
    }
    fingerprint = hashlib.sha256(json.dumps(
        semantic, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    repeated = False
    if previous is not None:
        prior = previous.get("details", {}).get("failure_fingerprint")
        repeated = prior == fingerprint
    proposed.execution_results[result.action_id]["details"]["failure_fingerprint"] = fingerprint
    if repeated and result.retryable:
        open_diagnostic_recovery(proposed, result, fingerprint=(fingerprint,))
        plan = ActionPlan.from_dict(proposed.action_queue[result.action_id]["plan"])
        attach_source_plan(proposed, result.action_id, plan)
        mark_action_suspended(proposed, result.action_id)
    elif result.retryable:
        queued = proposed.action_queue[result.action_id]
        queued["status"] = "pending"
        queued.pop("dispatch_intent", None)
        queued.pop("dispatch_receipt", None)
        proposed.revision += 1
    else:
        mark_action_suspended(proposed, result.action_id)
    return proposed


def apply_evidence_patch(current: ResearchState, artifact: dict[str, Any]) -> ResearchState:
    """Apply evidence only when it is bound to the persisted dispatch identity."""
    from chatgpt_operation.controller.diagnostic import (
        record_acquired_diagnostic_evidence,
        resume_dispatched_evidence,
    )
    import copy
    if not isinstance(artifact, dict) or artifact.get("schema_version") != 1:
        raise DurableStateError("unsupported evidence artifact schema")
    if artifact.get("revision_delta") != 1:
        raise DurableStateError("evidence patch must advance exactly one revision")
    action_id = artifact.get("action_id")
    if not isinstance(action_id, str) or not action_id:
        raise DurableStateError("evidence artifact action_id missing")
    evidence = artifact.get("evidence")
    if not isinstance(evidence, dict) or not evidence:
        raise DurableStateError("evidence artifact payload missing")

    try:
        intent, correlation_id, receipt = resume_dispatched_evidence(current, action_id)
    except ValueError as exc:
        raise DurableStateError("evidence artifact has no matching durable dispatch") from exc

    provenance = artifact.get("provenance")
    required = {
        "schema_version", "workflow_run_id", "run_attempt",
        "head_sha", "action_id", "dispatch_id",
    }
    if not isinstance(provenance, dict) or set(provenance) != required:
        raise DurableStateError("evidence provenance schema is invalid")
    if provenance.get("schema_version") != 1:
        raise DurableStateError("evidence provenance schema_version must be 1")
    run_id = provenance.get("workflow_run_id")
    run_attempt = provenance.get("run_attempt")
    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id < 1:
        raise DurableStateError("evidence workflow_run_id must be positive")
    if not isinstance(run_attempt, int) or isinstance(run_attempt, bool) or run_attempt < 1:
        raise DurableStateError("evidence run_attempt must be positive")
    if provenance.get("action_id") != action_id:
        raise DurableStateError("evidence provenance action_id mismatch")
    if provenance.get("dispatch_id") != correlation_id:
        raise DurableStateError("evidence provenance dispatch_id mismatch")
    if receipt.get("workflow_run_id") != run_id:
        raise DurableStateError("evidence provenance workflow_run_id mismatch")
    if provenance.get("head_sha") != intent.expected_head_sha:
        raise DurableStateError("evidence provenance head_sha mismatch")

    proposed = copy.deepcopy(current)
    before = proposed.revision
    record_acquired_diagnostic_evidence(proposed, action_id, evidence)
    if proposed.revision != before + 1:
        raise DurableStateError("evidence patch revision mismatch")
    return proposed
