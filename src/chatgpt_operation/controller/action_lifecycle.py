"""Typed durable lifecycle records for controller-owned actions."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import re
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


_SHA40 = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class DispatchIntent:
    action_id: str
    research_id: str
    workflow: str
    ref: str
    requested_at: str
    state_revision: int
    expected_head_sha: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "DispatchIntent":
        if not isinstance(raw, dict):
            raise ValueError("invalid dispatch intent schema")
        version = raw.get("schema_version")
        base = {
            "schema_version",
            "action_id",
            "research_id",
            "workflow",
            "ref",
            "requested_at",
            "state_revision",
        }
        if version == 1:
            if set(raw) != base:
                raise ValueError("invalid dispatch intent schema")
            expected_head_sha = None
        elif version == 2:
            if set(raw) != base | {"expected_head_sha"}:
                raise ValueError("invalid dispatch intent schema")
            expected_head_sha = raw["expected_head_sha"]
            if not isinstance(expected_head_sha, str) or not _SHA40.fullmatch(expected_head_sha):
                raise ValueError("dispatch intent expected_head_sha must be lowercase 40-hex")
        else:
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
        return cls(
            state_revision=revision,
            expected_head_sha=expected_head_sha,
            **values,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": 1 if self.expected_head_sha is None else 2,
            "action_id": self.action_id,
            "research_id": self.research_id,
            "workflow": self.workflow,
            "ref": self.ref,
            "requested_at": self.requested_at,
            "state_revision": self.state_revision,
        }
        if self.expected_head_sha is not None:
            payload["expected_head_sha"] = self.expected_head_sha
        return payload
