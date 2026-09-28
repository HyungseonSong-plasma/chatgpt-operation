"""Append-only runtime error evidence and attribution helpers.

This module owns factual runtime error/provenance records. Scientific or numerical\nowner inference remains a domain-layer responsibility.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4

SCHEMA_VERSION = 1
ERROR_LEDGER_SCHEMA_VERSION = SCHEMA_VERSION


class ErrorCategory(str, Enum):
    USER_ERROR = "USER_ERROR"
    CHATGPT_ERROR = "CHATGPT_ERROR"
    CODE_ERROR = "CODE_ERROR"
    UNCLASSIFIED = "UNCLASSIFIED"


class AttributionConfidence(str, Enum):
    CONFIRMED = "CONFIRMED"
    HIGH = "HIGH"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class AttributionSignals:
    user_controlled_contract_violation: bool = False
    assistant_generated_contract_violation: bool = False
    contract_conformant: bool | None = None
    reproducible_runtime_failure: bool = False
    isolated_code_owner: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Attribution:
    category: ErrorCategory
    confidence: AttributionConfidence
    reason: str
    signals: AttributionSignals


def classify_attribution(signals: AttributionSignals) -> Attribution:
    claims: list[tuple[ErrorCategory, AttributionConfidence, str]] = []
    if signals.user_controlled_contract_violation:
        claims.append(
            (
                ErrorCategory.USER_ERROR,
                AttributionConfidence.HIGH,
                "user-controlled invocation/input/environment violated the frozen contract",
            )
        )
    if signals.assistant_generated_contract_violation:
        claims.append(
            (
                ErrorCategory.CHATGPT_ERROR,
                AttributionConfidence.HIGH,
                "assistant-generated artifact/transformation violated the frozen contract",
            )
        )
    if signals.contract_conformant is True and signals.reproducible_runtime_failure:
        confidence = (
            AttributionConfidence.CONFIRMED
            if signals.isolated_code_owner
            else AttributionConfidence.HIGH
        )
        owner = (
            f"; isolated owner={signals.isolated_code_owner}"
            if signals.isolated_code_owner
            else ""
        )
        claims.append(
            (
                ErrorCategory.CODE_ERROR,
                confidence,
                "contract conformant and runtime failure reproducible" + owner,
            )
        )

    categories = {item[0] for item in claims}
    if len(categories) == 1:
        category = next(iter(categories))
        matching = [item for item in claims if item[0] == category]
        confidence = (
            AttributionConfidence.CONFIRMED
            if any(item[1] == AttributionConfidence.CONFIRMED for item in matching)
            else AttributionConfidence.HIGH
        )
        return Attribution(
            category,
            confidence,
            "; ".join(item[2] for item in matching),
            signals,
        )
    if len(categories) > 1:
        return Attribution(
            ErrorCategory.UNCLASSIFIED,
            AttributionConfidence.UNRESOLVED,
            "conflicting attribution evidence: "
            + ", ".join(sorted(item.value for item in categories)),
            signals,
        )
    return Attribution(
        ErrorCategory.UNCLASSIFIED,
        AttributionConfidence.UNRESOLVED,
        "insufficient provenance/contract evidence for ownership attribution",
        signals,
    )


@dataclass(frozen=True)
class ErrorEvent:
    schema_version: int
    event_id: str
    occurred_at: str
    run_id: str
    issue: int | None
    stage: str
    case_id: str | None
    category: str
    confidence: str
    error_code: str
    message: str
    source_layer: str
    attribution_reason: str
    signals: dict[str, Any]
    evidence: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    remedy: str | None = None
    resolved: bool = False
    signature: str = ""
    fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _nonempty(value: str, label: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{label} must be non-empty")
    return text


def error_fingerprint(
    *, category: str, error_code: str, source_layer: str, signature: str
) -> str:
    payload = "\x1f".join(
        (
            _nonempty(category, "category"),
            _nonempty(error_code, "error_code"),
            _nonempty(source_layer, "source_layer"),
            _nonempty(signature, "signature"),
        )
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def build_error_event(
    *,
    run_id: str,
    stage: str,
    error_code: str,
    message: str,
    source_layer: str,
    attribution: Attribution,
    issue: int | None = None,
    case_id: str | None = None,
    evidence: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
    remedy: str | None = None,
    resolved: bool = False,
    signature: str | None = None,
) -> ErrorEvent:
    code = _nonempty(error_code, "error_code")
    layer = _nonempty(source_layer, "source_layer")
    sig = _nonempty(signature or code, "signature")
    return ErrorEvent(
        schema_version=SCHEMA_VERSION,
        event_id=uuid4().hex,
        occurred_at=datetime.now(timezone.utc).isoformat(),
        run_id=_nonempty(run_id, "run_id"),
        issue=issue,
        stage=_nonempty(stage, "stage"),
        case_id=str(case_id) if case_id is not None else None,
        category=attribution.category.value,
        confidence=attribution.confidence.value,
        error_code=code,
        message=_nonempty(message, "message"),
        source_layer=layer,
        attribution_reason=attribution.reason,
        signals=attribution.signals.to_dict(),
        evidence=dict(evidence or {}),
        provenance=dict(provenance or {}),
        remedy=remedy,
        resolved=bool(resolved),
        signature=sig,
        fingerprint=error_fingerprint(
            category=attribution.category.value,
            error_code=code,
            source_layer=layer,
            signature=sig,
        ),
    )


def default_ledger_path() -> Path:
    override = os.environ.get("QPX_ERROR_LEDGER")
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".qpx_harness" / "error_ledger.jsonl").resolve()


def append_error_event(path: Path, event: ErrorEvent) -> None:
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def read_error_events(path: Path, *, missing_ok: bool = True) -> list[dict[str, Any]]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        if missing_ok:
            return []
        raise FileNotFoundError(path)
    events: list[dict[str, Any]] = []
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"invalid JSONL at {path}:{line_number}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise ValueError(
                f"error event must be a JSON object at {path}:{line_number}"
            )
        events.append(payload)
    return events


def _counter(events: Iterable[Mapping[str, Any]], key: str) -> dict[str, int]:
    return dict(
        sorted(Counter(str(event.get(key, "UNKNOWN")) for event in events).items())
    )


def summarize_error_events(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    items = [dict(event) for event in events]
    categories = _counter(items, "category")
    total = len(items)
    unresolved = sum(1 for event in items if not bool(event.get("resolved", False)))
    fingerprints = {
        str(event.get("fingerprint"))
        for event in items
        if event.get("fingerprint")
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "event_count": total,
        "unresolved_count": unresolved,
        "resolved_count": total - unresolved,
        "unique_fingerprint_count": len(fingerprints),
        "by_category": categories,
        "category_rates": {
            name: (count / total if total else 0.0)
            for name, count in categories.items()
        },
        "by_confidence": _counter(items, "confidence"),
        "by_error_code": _counter(items, "error_code"),
        "by_stage": _counter(items, "stage"),
        "by_source_layer": _counter(items, "source_layer"),
    }


class ErrorLedger:
    """Dual run-local + persistent append-only error ledger."""

    def __init__(self, *, run_path: Path, persistent_path: Path | None = None) -> None:
        self.run_path = Path(run_path).expanduser().resolve()
        self.persistent_path = (
            Path(persistent_path).expanduser().resolve()
            if persistent_path is not None
            else default_ledger_path()
        )

    @classmethod
    def for_run(
        cls, run_root: Path, *, persistent_path: Path | None = None
    ) -> "ErrorLedger":
        return cls(
            run_path=Path(run_root).expanduser().resolve() / "error_events.jsonl",
            persistent_path=persistent_path,
        )

    def append(self, event: ErrorEvent) -> None:
        append_error_event(self.run_path, event)
        if self.persistent_path != self.run_path:
            append_error_event(self.persistent_path, event)

    def record(self, **kwargs: Any) -> ErrorEvent:
        event = build_error_event(**kwargs)
        self.append(event)
        return event

    def run_events(self) -> list[dict[str, Any]]:
        return read_error_events(self.run_path)

    def persistent_events(self) -> list[dict[str, Any]]:
        return read_error_events(self.persistent_path)

    def run_summary(self) -> dict[str, Any]:
        return summarize_error_events(self.run_events())

    def persistent_summary(self) -> dict[str, Any]:
        return summarize_error_events(self.persistent_events())

    def write_summaries(self, root: Path) -> dict[str, str]:
        root = Path(root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        paths = {
            "run": root / "run_error_stats.json",
            "persistent": root / "error_stats.json",
        }
        paths["run"].write_text(
            json.dumps(self.run_summary(), indent=2, sort_keys=True) + "\n"
        )
        paths["persistent"].write_text(
            json.dumps(self.persistent_summary(), indent=2, sort_keys=True) + "\n"
        )
        return {name: str(path) for name, path in paths.items()}


__all__ = [
    "Attribution",
    "AttributionConfidence",
    "AttributionSignals",
    "ERROR_LEDGER_SCHEMA_VERSION",
    "ErrorCategory",
    "ErrorEvent",
    "ErrorLedger",
    "SCHEMA_VERSION",
    "append_error_event",
    "build_error_event",
    "classify_attribution",
    "default_ledger_path",
    "error_fingerprint",
    "read_error_events",
    "summarize_error_events",
]
