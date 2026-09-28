"""Append-only durable raw evidence for the Paul weekly cycle."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class RawEvidence:
    """One immutable observation retained by the weekly collection boundary."""

    identity: str
    payload: dict[str, Any]


class RawEvidenceStore:
    """Persist raw observations as idempotent, append-only JSON lines."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @staticmethod
    def identity(payload: Mapping[str, Any]) -> str:
        canonical = json.dumps(
            dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        return sha256(canonical).hexdigest()

    def append(self, payload: Mapping[str, Any]) -> RawEvidence:
        """Append an observation once and return its stable evidence identity."""
        normalized = dict(payload)
        identity = self.identity(normalized)
        existing = self._read_identities()
        if identity not in existing:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            record = {"identity": identity, "payload": normalized}
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True) + "\n")
                stream.flush()
        return RawEvidence(identity=identity, payload=normalized)

    def read(self) -> tuple[RawEvidence, ...]:
        if not self.path.exists():
            return ()
        result: list[RawEvidence] = []
        with self.path.open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                record = json.loads(line)
                result.append(
                    RawEvidence(
                        identity=str(record["identity"]),
                        payload=dict(record["payload"]),
                    )
                )
        return tuple(result)

    def _read_identities(self) -> set[str]:
        return {item.identity for item in self.read()}
