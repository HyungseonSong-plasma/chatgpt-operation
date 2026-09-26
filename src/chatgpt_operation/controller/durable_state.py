"""Durable Samuel controller state encoded in the Issue #44 ledger."""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from .research import ResearchState

STATE_MARKER = "<!-- samuel-controller-state -->"
STATE_SCHEMA_VERSION = 1


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
    if envelope.get("schema_version") != STATE_SCHEMA_VERSION:
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
