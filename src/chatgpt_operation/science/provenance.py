"""Stable reference-only provenance envelope for scientific runs.

The envelope records lineage and artifact references. It never embeds subsystem
payload schemas owned by Execution, Evidence, Analysis, Diagnose, or protocols.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Literal

ArtifactKind = Literal["execution", "evidence", "analysis", "diagnosis", "protocol"]


@dataclass(frozen=True)
class ArtifactRef:
    kind: ArtifactKind
    path: str
    schema_version: int | None = None
    sha256: str | None = None


@dataclass(frozen=True)
class FileIdentity:
    path: str
    sha256: str | None = None


@dataclass(frozen=True)
class RunEnvelope:
    run_id: str
    experiment_id: str
    protocol: str
    source_revision: str | None = None
    executable: FileIdentity | None = None
    input: FileIdentity | None = None
    artifacts: tuple[ArtifactRef, ...] = field(default_factory=tuple)
    schema_version: int = 1

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def write_run_envelope(path: str | Path, envelope: RunEnvelope) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(
        json.dumps(envelope.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp.replace(target)
    return target


def read_run_envelope(path: str | Path) -> RunEnvelope:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1:
        raise ValueError(f"unsupported RunEnvelope schema_version: {raw.get('schema_version')!r}")
    artifacts = tuple(ArtifactRef(**item) for item in raw.get("artifacts", ()))
    executable = FileIdentity(**raw["executable"]) if raw.get("executable") else None
    input_identity = FileIdentity(**raw["input"]) if raw.get("input") else None
    return RunEnvelope(
        schema_version=1,
        run_id=raw["run_id"],
        experiment_id=raw["experiment_id"],
        protocol=raw["protocol"],
        source_revision=raw.get("source_revision"),
        executable=executable,
        input=input_identity,
        artifacts=artifacts,
    )


__all__ = [
    "ArtifactKind",
    "ArtifactRef",
    "FileIdentity",
    "RunEnvelope",
    "read_run_envelope",
    "write_run_envelope",
]
