"""Typed durable lifecycle records for controller-owned actions."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class ActionLifecycle(str, Enum):
    PENDING = "pending"
    DISPATCH_INTENT = "dispatch_intent"
    DISPATCHED = "dispatched"
    OBSERVING = "observing"
    TERMINAL = "terminal"
    VERIFIED = "verified"
    COMPLETE = "complete"
    SUSPENDED = "suspended"


@dataclass(frozen=True)
class DispatchIntent:
    action_id: str
    research_id: str
    workflow: str
    ref: str
    requested_at: str
    state_revision: int

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "DispatchIntent":
        required = {
            "schema_version",
            "action_id",
            "research_id",
            "workflow",
            "ref",
            "requested_at",
            "state_revision",
        }
        if not isinstance(raw, dict) or set(raw) != required:
            raise ValueError("invalid dispatch intent schema")
        if raw["schema_version"] != 1:
            raise ValueError("unsupported dispatch intent schema")
        values = {}
        for field in ("action_id", "research_id", "workflow", "ref", "requested_at"):
            value = raw[field]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"dispatch intent {field} must be non-empty")
            values[field] = value.strip()
        try:
            datetime.fromisoformat(values["requested_at"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("dispatch intent requested_at must be ISO-8601") from exc
        revision = raw["state_revision"]
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise ValueError("dispatch intent state_revision must be positive")
        return cls(state_revision=revision, **values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "action_id": self.action_id,
            "research_id": self.research_id,
            "workflow": self.workflow,
            "ref": self.ref,
            "requested_at": self.requested_at,
            "state_revision": self.state_revision,
        }
