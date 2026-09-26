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
