"""Deterministic, source-witnessed Mermaid diagrams for README candidates.

This renderer accepts an explicitly caller-declared graph. It does not infer
architecture, execute Mermaid, read source files or write a repository.
"""

from __future__ import annotations

from html import escape
import re
from typing import Any

from .discovery import RefinementError, repository_path


_NODE_ID = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}\Z")
_SAFE_EVIDENCE = re.compile(r"[A-Za-z0-9_./-]{1,220}\Z")
_MAX_NODES = 24
_MAX_EDGES = 40


def _object(value: Any, keys: set[str], field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise RefinementError(f"{field} must have exactly {sorted(keys)}")
    return value


def _text(value: Any, field: str, *, limit: int) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)):
        raise RefinementError(f"{field} must be nonempty, bounded, single-line text")
    return value.strip()


def _witness(value: Any, inventory: frozenset[str], field: str) -> str:
    path = repository_path(value)
    if not _SAFE_EVIDENCE.fullmatch(path) or path not in inventory:
        raise RefinementError(f"{field} not in exact source inventory")
    return path


def _mermaid_text(value: str) -> str:
    # No user-supplied Mermaid tokens, directives or fences are interpolated.
    # HTML entities are used inside quoted Mermaid labels, not raw Markdown.
    return (escape(value, quote=True)
            .replace("[", "&#91;")
            .replace("]", "&#93;")
            .replace("|", "&#124;")
            .replace("`", "&#96;")
            .replace("{", "&#123;")
            .replace("}", "&#125;"))


def _markdown_text(value: str) -> str:
    return (escape(value, quote=False).replace("\\", "\\\\")
            .replace("`", "\\`").replace("*", "\\*")
            .replace("[", "\\[").replace("]", "\\]")
            .replace("|", "\\|"))


def render_evidence_diagram(
    spec: dict[str, Any],
    *,
    inventory: frozenset[str],
) -> str:
    """Render one optional diagram with provenance and explicit limitations.

    Required spec fields:
      title: single-line human title
      caption: descriptive, caller-grounded explanation
      nodes: [{id, label, evidence_path}, ...]
      edges: [{source, target, label, evidence_path}, ...]
    All edges and nodes require a path present in the caller-attested exact
    source inventory. A witness is NOT proof of a semantic relationship.
    """
    source = _object(spec, {"title", "caption", "nodes", "edges"}, "diagram")
    title = _text(source["title"], "diagram title", limit=90)
    caption = _text(source["caption"], "diagram caption", limit=240)
    nodes = source["nodes"]
    edges = source["edges"]
    if (not isinstance(nodes, list) or not 2 <= len(nodes) <= _MAX_NODES
            or not isinstance(edges, list) or not 1 <= len(edges) <= _MAX_EDGES):
        raise RefinementError("diagram requires 2..24 nodes and 1..40 edges")

    names: set[str] = set()
    declared: list[tuple[str, str]] = []
    witness_paths: set[str] = set()
    for node in nodes:
        data = _object(node, {"id", "label", "evidence_path"}, "diagram node")
        identifier = data["id"]
        if (not isinstance(identifier, str)
                or _NODE_ID.fullmatch(identifier) is None or identifier in names):
            raise RefinementError("duplicate or unsafe diagram node ID")
        names.add(identifier)
        label = _text(data["label"], "diagram node label", limit=90)
        witness_paths.add(_witness(data["evidence_path"], inventory, "node evidence"))
        declared.append((identifier, label))

    relationships: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in edges:
        data = _object(edge, {"source", "target", "label", "evidence_path"}, "diagram edge")
        src, dst = data["source"], data["target"]
        if (not isinstance(src, str) or not isinstance(dst, str)
                or src not in names or dst not in names or src == dst):
            raise RefinementError("diagram edge must connect two distinct declared nodes")
        label = _text(data["label"], "diagram edge label", limit=90)
        key = (src, dst, label)
        if key in seen:
            raise RefinementError("duplicate diagram edge")
        seen.add(key)
        witness_paths.add(_witness(data["evidence_path"], inventory, "edge evidence"))
        relationships.append(key)

    lines = [
        "### " + _markdown_text(title),
        "",
        "```mermaid",
        "flowchart LR",
    ]
    for identifier, label in sorted(declared):
        lines.append(f'  {identifier}["{_mermaid_text(label)}"]')
    for src, dst, label in sorted(relationships):
        lines.append(f'  {src} -->|{_mermaid_text(label)}| {dst}')
    lines.extend([
        "```",
        "",
        _markdown_text(caption),
        "",
        "Source witnesses (caller-attested, not independently verified): "
        + ", ".join(f"`{path}`" for path in sorted(witness_paths)) + ".",
        "",
        "**Boundary:** This is a declared explanatory relationship diagram, "
        "not proof of runtime calls, semantic correctness, complete coverage "
        "or quality PASS.",
        "",
    ])
    return "\n".join(lines)
