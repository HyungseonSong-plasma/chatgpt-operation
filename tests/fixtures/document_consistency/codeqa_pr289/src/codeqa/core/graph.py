"""Immutable, language-independent CCG v0.1 model; no I/O or language ASTs."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class Snapshot:
    id: str


@dataclass(frozen=True, slots=True)
class Provenance:
    producer: str
    method: str


@dataclass(frozen=True, slots=True)
class SourceLocation:
    path: str
    start_line: int
    end_line: int
    start_column: int | None = None
    end_column: int | None = None


@dataclass(frozen=True, slots=True)
class Node:
    id: str
    kind: str
    name: str
    provenance: Provenance
    location: SourceLocation | None = None


@dataclass(frozen=True, slots=True)
class Edge:
    source: str
    kind: str
    resolution: str
    provenance: Provenance
    target: str | None = None
    target_hint: str | None = None
    location: SourceLocation | None = None


@dataclass(frozen=True, slots=True)
class Unprocessed:
    path: str
    reason: str


@dataclass(frozen=True, slots=True)
class Coverage:
    status: str
    analyzed_paths: tuple[str, ...]
    unprocessed: tuple[Unprocessed, ...]


@dataclass(frozen=True, slots=True)
class Diagnostic:
    severity: str
    code: str
    message: str
    location: SourceLocation | None = None
    path: str | None = None


@dataclass(frozen=True, slots=True)
class Graph:
    schema_version: str
    snapshot: Snapshot
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    coverage: Coverage
    diagnostics: tuple[Diagnostic, ...] = ()

    @classmethod
    def from_document(cls, doc: Mapping[str, Any]) -> Graph:
        """Construct from structurally validated data; prefer parse_graph for input."""
        def loc(value: Mapping[str, Any] | None) -> SourceLocation | None:
            return SourceLocation(**value) if value is not None else None

        return cls(
            schema_version=doc["schema_version"],
            snapshot=Snapshot(**doc["snapshot"]),
            nodes=tuple(
                Node(
                    id=n["id"], kind=n["kind"], name=n["name"],
                    provenance=Provenance(**n["provenance"]),
                    location=loc(n.get("location")),
                ) for n in doc["nodes"]
            ),
            edges=tuple(
                Edge(
                    source=e["source"], kind=e["kind"], resolution=e["resolution"],
                    provenance=Provenance(**e["provenance"]),
                    target=e.get("target"), target_hint=e.get("target_hint"),
                    location=loc(e.get("location")),
                ) for e in doc["edges"]
            ),
            coverage=Coverage(
                status=doc["coverage"]["status"],
                analyzed_paths=tuple(doc["coverage"]["analyzed_paths"]),
                unprocessed=tuple(Unprocessed(**u) for u in doc["coverage"]["unprocessed"]),
            ),
            diagnostics=tuple(
                Diagnostic(
                    severity=d["severity"], code=d["code"], message=d["message"],
                    location=loc(d.get("location")), path=d.get("path"),
                ) for d in doc.get("diagnostics", ())
            ),
        )

    def to_document(self) -> dict[str, Any]:
        """Serialize exactly the v0.1 fields, omitting absent optional members."""
        def normalize(value: Any) -> Any:
            if isinstance(value, dict):
                return {k: normalize(v) for k, v in value.items() if v is not None}
            if isinstance(value, (tuple, list)):
                return [normalize(v) for v in value]
            return value

        return normalize(asdict(self))
