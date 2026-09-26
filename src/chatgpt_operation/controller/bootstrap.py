"""Deterministic root entrypoint for waking Samuel from persistent pending work."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Any


class BootstrapError(ValueError):
    pass


class BootstrapKind(str, Enum):
    WORKFLOW = "workflow"


@dataclass(frozen=True)
class BootstrapWork:
    work_id: str
    kind: BootstrapKind
    workflow: str
    ref: str = "main"
    status: str = "pending"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "BootstrapWork":
        allowed={"work_id","kind","workflow","ref","status"}
        if set(raw) - allowed:
            raise BootstrapError("bootstrap work contains unknown fields")
        if not isinstance(raw.get("work_id"),str) or not raw["work_id"]:
            raise BootstrapError("work_id is required")
        if raw.get("status","pending") not in {"pending","complete","blocked"}:
            raise BootstrapError("invalid bootstrap status")
        return cls(
            work_id=raw["work_id"],
            kind=BootstrapKind(raw["kind"]),
            workflow=raw["workflow"],
            ref=raw.get("ref","main"),
            status=raw.get("status","pending"),
        )


def load_pending(path: str | Path) -> list[BootstrapWork]:
    raw=json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1 or not isinstance(raw.get("work"),list):
        raise BootstrapError("invalid bootstrap queue")
    items=[BootstrapWork.from_dict(x) for x in raw["work"]]
    ids=[x.work_id for x in items]
    if len(ids) != len(set(ids)):
        raise BootstrapError("duplicate bootstrap work_id")
    return [x for x in items if x.status == "pending"]
