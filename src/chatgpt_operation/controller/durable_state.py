"""Durable Samuel controller state encoded in the Issue #44 ledger."""
from __future__ import annotations

import base64
import binascii
import json
import zlib
from dataclasses import asdict
from typing import Any

from .research import ResearchState

STATE_MARKER = "<!-- samuel-controller-state -->"
STATE_SCHEMA_VERSION = 2
STATE_ENCODING = "zlib+base64"
STATE_INLINE_THRESHOLD = 48_000
STATE_SAFE_COMMENT_LIMIT = 240_000
STATE_MAX_DECOMPRESSED_BYTES = 4_000_000
STATE_MAX_COMPRESSED_BYTES = 1_000_000


class DurableStateError(ValueError):
    pass


def _state_body(envelope: dict[str, Any]) -> str:
    return STATE_MARKER + "\n```json\n" + json.dumps(
        envelope, sort_keys=True, separators=(",", ":")
    ) + "\n```"


def encode_state(state: ResearchState) -> str:
    """Encode durable state, compressing large ledgers without discarding evidence."""
    payload = asdict(state)
    payload["stage"] = state.stage.value
    envelope = {
        "schema_version": STATE_SCHEMA_VERSION,
        "research_id": state.research_id,
        "revision": state.revision,
        "state": payload,
    }
    inline = _state_body(envelope)
    if len(inline) <= STATE_INLINE_THRESHOLD:
        return inline

    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    compressed = zlib.compress(raw, level=9)
    encoded = base64.b64encode(compressed).decode("ascii")
    compact = _state_body({
        "schema_version": STATE_SCHEMA_VERSION,
        "research_id": state.research_id,
        "revision": state.revision,
        "encoding": STATE_ENCODING,
        "state": encoded,
    })
    if len(compact) > STATE_SAFE_COMMENT_LIMIT:
        raise DurableStateError(
            "encoded controller state exceeds safe GitHub comment size"
        )
    return compact


def _decode_compressed_state(value: Any) -> dict[str, Any]:
    if not isinstance(value, str) or not value:
        raise DurableStateError("compressed controller state payload missing")
    try:
        compressed = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise DurableStateError(
            "compressed controller state base64 is invalid"
        ) from exc
    if len(compressed) > STATE_MAX_COMPRESSED_BYTES:
        raise DurableStateError("compressed controller state payload is too large")

    inflater = zlib.decompressobj()
    try:
        raw = inflater.decompress(
            compressed, STATE_MAX_DECOMPRESSED_BYTES + 1
        )
    except zlib.error as exc:
        raise DurableStateError(
            "compressed controller state zlib payload is invalid"
        ) from exc
    if (
        len(raw) > STATE_MAX_DECOMPRESSED_BYTES
        or inflater.unconsumed_tail
        or not inflater.eof
        or inflater.unused_data
    ):
        raise DurableStateError(
            "compressed controller state payload exceeds bounded decode contract"
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DurableStateError(
            "compressed controller state JSON is invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise DurableStateError("compressed controller state payload missing")
    return payload


def decode_state(body: str) -> ResearchState:
    if STATE_MARKER not in body:
        raise DurableStateError("controller state marker missing")
    start = body.find("```json")
    end = body.rfind("```")
    if start < 0 or end <= start + 7:
        raise DurableStateError("controller state JSON fence missing")
    try:
        envelope = json.loads(body[start + 7:end].strip())
    except json.JSONDecodeError as exc:
        raise DurableStateError("controller state JSON is invalid") from exc
    if envelope.get("schema_version") not in {1, STATE_SCHEMA_VERSION}:
        raise DurableStateError("unsupported controller state schema")
    encoding=envelope.get("encoding")
    if encoding is None:
        raw=envelope.get("state")
        if not isinstance(raw,dict):
            raise DurableStateError("controller state payload missing")
    elif encoding==STATE_ENCODING:
        raw=_decode_compressed_state(envelope.get("state"))
    else:
        raise DurableStateError("unsupported controller state encoding")
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
        inherited_evidence=list(raw.get("inherited_evidence", [])),
        last_reasoning_head_sha=(
            str(raw["last_reasoning_head_sha"])
            if raw.get("last_reasoning_head_sha") is not None
            else None
        ),
    )


def can_rollover_state(state: ResearchState) -> bool:
    """Return whether a completed workload may yield the single durable state slot."""
    if not state.action_queue:
        return False
    if any(
        recovery.get("status") in {"open", "needs_evidence"}
        for recovery in state.diagnostic_recoveries.values()
    ):
        return False
    for action_id, item in state.action_queue.items():
        status = item.get("status")
        if status in {"complete", "rejected"}:
            continue
        if status != "suspended":
            return False
        failure = state.execution_results.get(action_id)
        details = {} if not isinstance(failure, dict) else failure.get("details", {})
        if (
            not isinstance(failure, dict)
            or failure.get("status") != "failed"
            or not isinstance(details, dict)
            or details.get("governance_retryable") is not False
        ):
            return False
    return True


def require_fresh_write(current: ResearchState | None, proposed: ResearchState) -> None:
    """Reject stale writes; allow cross-workload replacement only after terminal proof."""
    if current is None:
        return
    if current.research_id != proposed.research_id:
        if not can_rollover_state(current):
            raise DurableStateError("cannot overwrite a different research state before terminal completion")
        return
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
    if expected_previous != current.revision:
        raise DurableStateError(
            f"stale durable state precondition {expected_previous} != {current.revision}"
        )
    if current.research_id != proposed.research_id:
        if not can_rollover_state(current):
            raise DurableStateError(
                "cannot overwrite a different research state before terminal completion"
            )
        return
    if proposed.revision <= current.revision:
        raise DurableStateError("durable state revision did not advance")


def apply_diagnostic_patch(
    current: ResearchState,
    artifact: dict[str, Any],
) -> ResearchState:
    """Apply one diagnostic artifact only from its authoritative workflow dispatch."""
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

    if before.get("diagnostic_dispatch") is not None:
        from chatgpt_operation.controller.diagnostic import resume_dispatched_diagnostic
        try:
            intent, correlation_id, receipt = resume_dispatched_diagnostic(current, action_id)
        except ValueError as exc:
            raise DurableStateError(
                "diagnostic artifact has no matching durable dispatch"
            ) from exc
        provenance = artifact.get("provenance")
        required = {
            "schema_version", "workflow_run_id", "run_attempt",
            "head_sha", "action_id", "dispatch_id",
        }
        if not isinstance(provenance, dict) or set(provenance) != required:
            raise DurableStateError("diagnostic provenance schema is invalid")
        if provenance.get("schema_version") != 1:
            raise DurableStateError("diagnostic provenance schema_version must be 1")
        run_id = provenance.get("workflow_run_id")
        run_attempt = provenance.get("run_attempt")
        if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id < 1:
            raise DurableStateError("diagnostic workflow_run_id must be positive")
        if not isinstance(run_attempt, int) or isinstance(run_attempt, bool) or run_attempt < 1:
            raise DurableStateError("diagnostic run_attempt must be positive")
        if provenance.get("action_id") != action_id:
            raise DurableStateError("diagnostic provenance action_id mismatch")
        if provenance.get("dispatch_id") != correlation_id:
            raise DurableStateError("diagnostic provenance dispatch_id mismatch")
        if receipt.get("workflow_run_id") != run_id:
            raise DurableStateError("diagnostic provenance workflow_run_id mismatch")
        if provenance.get("head_sha") != intent.expected_head_sha:
            raise DurableStateError("diagnostic provenance head_sha mismatch")

    import copy
    proposed = copy.deepcopy(current)
    clean_patch = copy.deepcopy(patched)
    clean_patch.pop("diagnostic_dispatch", None)
    proposed.diagnostic_recoveries[action_id] = clean_patch
    proposed.revision = current.revision + 1
    return proposed


def apply_dispatch_receipt(
    current: ResearchState,
    *,
    surface: str,
    action_id: str,
    receipt: dict[str, Any],
) -> ResearchState:
    """Bind one verified external workflow receipt as exactly one durable revision."""
    from chatgpt_operation.controller.diagnostic import (
        record_action_dispatch,
        record_corrective_dispatch,
        record_diagnostic_dispatch,
        record_evidence_dispatch,
    )
    from chatgpt_operation.controller.trusted_validation import (
        record_trusted_validation_dispatch,
    )
    import copy

    handlers = {
        "action": record_action_dispatch,
        "evidence": record_evidence_dispatch,
        "diagnostic": record_diagnostic_dispatch,
        "corrective": record_corrective_dispatch,
        "trusted_validation": record_trusted_validation_dispatch,
    }
    try:
        handler = handlers[surface]
    except KeyError as exc:
        raise DurableStateError("unsupported dispatch receipt surface") from exc
    proposed = copy.deepcopy(current)
    before = proposed.revision
    handler(proposed, action_id, receipt)
    if proposed.revision != before + 1:
        raise DurableStateError("dispatch receipt must advance exactly one revision")
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


def apply_action_rejection(current: ResearchState, result) -> ResearchState:
    """Record a verified precondition rejection as terminal planning evidence."""
    from chatgpt_operation.controller.execution import (
        ExecutionStatus, require_execution_provenance,
    )
    from chatgpt_operation.controller.action_lifecycle import DispatchIntent
    import copy
    if result.status is not ExecutionStatus.REJECTED:
        raise DurableStateError(
            "action rejection requires REJECTED execution evidence"
        )
    item = current.action_queue.get(result.action_id)
    if item is None or item.get("status") != "dispatched":
        raise DurableStateError("rejected action is not dispatched")
    receipt = item.get("dispatch_receipt")
    run_id = None if not isinstance(receipt, dict) else receipt.get(
        "workflow_run_id"
    )
    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id < 1:
        raise DurableStateError(
            "rejected action has no authoritative workflow_run_id"
        )
    intent = DispatchIntent.from_dict(item.get("dispatch_intent"))
    require_execution_provenance(
        result,
        workflow_run_id=run_id,
        head_sha=intent.expected_head_sha,
    )
    proposed = copy.deepcopy(current)
    queued = proposed.action_queue[result.action_id]
    queued["status"] = "rejected"
    queued["completion_result"] = result.to_dict()
    proposed.revision = current.revision + 1
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
    provider_infrastructure_failure = (
        result.details.get("error_type") == "ExecutionKernelError"
        and isinstance(result.details.get("provider"), str)
        and bool(result.details.get("provider"))
    )
    effective_retryable = result.retryable or provider_infrastructure_failure
    proposed.execution_results[result.action_id]["details"][
        "governance_retryable"
    ] = effective_retryable
    if repeated and effective_retryable:
        open_diagnostic_recovery(proposed, result, fingerprint=(fingerprint,))
        plan = ActionPlan.from_dict(proposed.action_queue[result.action_id]["plan"])
        attach_source_plan(proposed, result.action_id, plan)
        mark_action_suspended(proposed, result.action_id)
    elif effective_retryable:
        queued = proposed.action_queue[result.action_id]
        queued["status"] = "pending"
        queued.pop("dispatch_intent", None)
        queued.pop("dispatch_receipt", None)
        proposed.revision += 1
    else:
        mark_action_suspended(proposed, result.action_id)
    return proposed


def apply_corrective_execution_result(
    current: ResearchState,
    action_id: str,
    result,
) -> ResearchState:
    """Apply one corrective native result as a single durable recovery transaction."""
    from chatgpt_operation.controller.action_plan import ExecutorKind
    from chatgpt_operation.controller.diagnostic import (
        resume_dispatched_corrective,
        resolve_from_execution_receipt,
        resume_resolved_action,
    )
    from chatgpt_operation.controller.execution import (
        ExecutionStatus,
        require_execution_provenance,
    )
    import copy

    try:
        plan, authorization, intent, correlation_id, receipt = (
            resume_dispatched_corrective(current, action_id)
        )
    except ValueError as exc:
        raise DurableStateError(
            "corrective result has no matching durable dispatch"
        ) from exc
    if result.research_id != current.research_id or result.action_id != action_id:
        raise DurableStateError("corrective result identity mismatch")
    if result.executor is not ExecutorKind.GITHUB_NATIVE:
        raise DurableStateError("corrective result came from wrong executor")
    run_id = receipt.get("workflow_run_id")
    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id < 1:
        raise DurableStateError("corrective dispatch has no authoritative workflow_run_id")
    require_execution_provenance(
        result,
        workflow_run_id=run_id,
        head_sha=intent.expected_head_sha,
    )
    if plan.idempotency_key != action_id or authorization.action_id != action_id:
        raise DurableStateError("corrective source plan identity changed")
    if receipt.get("correlation_id") != correlation_id:
        raise DurableStateError("corrective dispatch correlation changed")

    proposed = copy.deepcopy(current)
    before = current.revision
    resolution = resolve_from_execution_receipt(
        proposed,
        action_id,
        corrective_result=result,
    )
    recovery = proposed.diagnostic_recoveries[action_id]
    if resolution.advanced:
        recovery.pop("corrective_dispatch", None)
        resume_resolved_action(proposed, action_id)
        proposed.revision = before + 1
        return proposed

    # A terminal result that cannot verify the correction is evidence against the
    # selected provider. Keep the source action suspended and return diagnosis to
    # provider selection rather than silently replaying the same correction.
    provider = str(recovery.get("corrective_provider", "")).strip()
    failure = dict(recovery.get("failure") or {})
    details = dict(failure.get("details") or {})
    provider_failures = list(details.get("provider_failures") or [])
    evidence = {
        "provider": provider,
        "error_type": str(result.details.get("error_type") or result.status.value),
        "provider_status": str(result.details.get("provider_status") or ""),
        "observation": result.observation,
    }
    if provider and not any(
        isinstance(item, dict) and item.get("provider") == provider
        for item in provider_failures
    ):
        provider_failures.append(evidence)
    details["provider_failures"] = provider_failures
    failure["details"] = details
    recovery["failure"] = failure
    recovery["last_corrective_result"] = result.to_dict()
    recovery["corrective_action"] = None
    recovery.pop("corrective_provider", None)
    recovery.pop("corrective_dispatch", None)
    proposed.revision = before + 1
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
