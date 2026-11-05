"""Evidence-scoped, read-only documentation refinement pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .compact import compact_document
from .design import PRESETS, render_markdown
from .diagrams import render_evidence_diagram
from .discovery import RefinementError, discover_source_inventory
from .anchors import heading_anchors
from .quality import ReadabilityBudget, ReadmeAudit, audit_markdown_v02, enforce_markdown_v02
from .structure import build_document
from .validation import validate_rendered

__all__ = ["PRESETS", "RefinementError", "RefinementResult", "refine_document", "heading_anchors", "ReadabilityBudget", "ReadmeAudit", "audit_markdown_v02", "enforce_markdown_v02", "render_evidence_diagram"]


@dataclass(frozen=True)
class RefinementResult:
    markdown: str
    snapshot_sha: str
    preset: str
    preserved_link_count: int
    preserved_claim_count: int


def refine_document(
    *,
    payload: dict[str, Any],
    source_inventory: Iterable[str],
    inventory_complete: bool,
    baseline_markdown: str,
    required_claims: list[str],
    preset: str = "minimal",
    diagram: dict[str, Any] | None = None,
) -> RefinementResult:
    """Produce a proposed README; never write or authorize a repository change.

    The caller owns evidence acquisition, semantic review, exact-head GitHub
    mutation, CI and merge acceptance.
    """
    if not isinstance(payload, dict):
        raise RefinementError("payload must be an object")
    inventory = discover_source_inventory(
        payload.get("snapshot_sha"),
        source_inventory,
        inventory_complete=inventory_complete,
    )
    document = compact_document(build_document(payload, inventory))
    markdown = render_markdown(document, preset=preset, inventory=inventory)
    if diagram is not None:
        # Optional, source-witnessed explanation; no semantic relation is inferred.
        illustration = render_evidence_diagram(diagram, inventory=inventory)
        position = markdown.rfind("\n---\n")
        if position < 0:
            raise RefinementError("document renderer omitted closing divider")
        markdown = markdown[:position] + "\n" + illustration + markdown[position:]
    links, claims = validate_rendered(
        document=document,
        markdown=markdown,
        inventory=inventory,
        baseline_markdown=baseline_markdown,
        required_claims=required_claims,
    )
    return RefinementResult(
        markdown=markdown,
        snapshot_sha=document.snapshot_sha,
        preset=preset,
        preserved_link_count=links,
        preserved_claim_count=claims,
    )
