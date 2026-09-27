"""Typed execution commands emitted only by the Samuel composition root."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ControllerCommandError(ValueError):
    pass


class ControllerCommandKind(str, Enum):
    DISPATCH_ACTION = "dispatch_action"
    RECONCILE_ACTION = "reconcile_action"
    OBSERVE_ACTION = "observe_action"
    DISPATCH_EVIDENCE = "dispatch_evidence"
    RECONCILE_EVIDENCE = "reconcile_evidence"
    OBSERVE_EVIDENCE = "observe_evidence"
    DISPATCH_DIAGNOSTIC = "dispatch_diagnostic"
    RECONCILE_DIAGNOSTIC = "reconcile_diagnostic"
    OBSERVE_DIAGNOSTIC = "observe_diagnostic"
    DISPATCH_CORRECTIVE = "dispatch_corrective"
    RECONCILE_CORRECTIVE = "reconcile_corrective"
    OBSERVE_CORRECTIVE = "observe_corrective"


@dataclass(frozen=True)
class ControllerCommand:
    kind: ControllerCommandKind
    action_id: str
    research_id: str
    state_revision: int

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ControllerCommand":
        required = {
            "schema_version", "kind", "action_id", "research_id", "state_revision"
        }
        if not isinstance(raw, dict) or set(raw) != required:
            raise ControllerCommandError("invalid controller command schema")
        if raw["schema_version"] != 1:
            raise ControllerCommandError("unsupported controller command schema")
        try:
            kind = ControllerCommandKind(raw["kind"])
        except (TypeError, ValueError) as exc:
            raise ControllerCommandError("unsupported controller command kind") from exc
        action_id = raw["action_id"]
        research_id = raw["research_id"]
        revision = raw["state_revision"]
        if not isinstance(action_id, str) or not action_id.strip():
            raise ControllerCommandError("controller command action_id must be non-empty")
        if not isinstance(research_id, str) or not research_id.strip():
            raise ControllerCommandError("controller command research_id must be non-empty")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            raise ControllerCommandError("controller command state_revision must be non-negative")
        return cls(kind, action_id.strip(), research_id.strip(), revision)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": self.kind.value,
            "action_id": self.action_id,
            "research_id": self.research_id,
            "state_revision": self.state_revision,
        }
