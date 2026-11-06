"""Deterministic, read-only documentation status badges and consistency checks.

This module validates label *presentation* against caller-supplied evidence.
It never decides consumer architecture adoption, semantic correctness or review.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import PurePosixPath
import posixpath
import re
from typing import Mapping, Iterable
from urllib.parse import urlsplit


class LabelError(ValueError):
    """Invalid status declaration or untrustworthy snapshot input."""


STATUS_COLORS = {
    "decision": {
        "PROPOSED": "0969DA",
        "ADOPTED": "2DA44E",
        "SUPERSEDED": "6E7781",
        "NOT_EVALUATED": "6E7781",
    },
    "implementation": {
        "IMPLEMENTED": "2DA44E",
        "PARTIAL": "BF8700",
        "NOT_IMPLEMENTED": "CF222E",
        "NOT_EVALUATED": "6E7781",
    },
    "review": {
        "REVIEWED": "2DA44E",
        "REVIEW_REQUIRED": "BF8700",
        "NOT_EVALUATED": "6E7781",
    },
}
AXES = ("decision", "implementation", "review")
# Soft-background, rounded status chips; accent colours remain semantic IDs.
# Each entry is (background, foreground, border) in six-digit hex.
BADGE_PALETTE = {
    "2DA44E": ("DAFBE1", "116329", "ACE6BF"),
    "0969DA": ("DDF4FF", "0550AE", "B6DEFA"),
    "BF8700": ("FFF8C5", "7D4E00", "E7D08A"),
    "CF222E": ("FFEBE9", "B42318", "F5B5B4"),
    "6E7781": ("EAECEF", "57606A", "D0D7DE"),
}
SHA = re.compile(r"^[0-9a-f]{40}$")
IMAGE = re.compile(r"!\[([A-Za-z]+): ([A-Z_]+)\]\(([^)\n]+)\)")


@dataclass(frozen=True)
class DocumentLabelAudit:
    """Display-only result; never a semantic or domain acceptance verdict."""

    status: str
    issues: tuple[str, ...]
    snapshot_sha: str
    semantic_status: str = "NOT_EVALUATED"


def _validate_values(labels: Mapping[str, str]) -> None:
    if not isinstance(labels, Mapping) or set(labels) != set(AXES):
        raise LabelError("labels must contain exactly decision, implementation, review")
    for axis in AXES:
        if labels[axis] not in STATUS_COLORS[axis]:
            raise LabelError(f"unsupported {axis} status: {labels[axis]!r}")


def badge_filename(axis: str, value: str) -> str:
    if axis not in STATUS_COLORS or value not in STATUS_COLORS[axis]:
        raise LabelError("unknown badge axis or status")
    return f"{axis}-{value.lower().replace('_', '-')}.svg"


def render_badge_svg(axis: str, value: str) -> str:
    """Render a self-contained, rounded, one-piece status chip like chat badges."""
    if axis not in STATUS_COLORS or value not in STATUS_COLORS[axis]:
        raise LabelError("unknown badge axis or status")
    title = axis.title()
    shown = value
    width = max(78, len(shown) * 7 + 22)
    background, ink, border = BADGE_PALETTE[STATUS_COLORS[axis][value]]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="22" '
        f'role="img" aria-label="{escape(title)}: {escape(shown)}">\n'
        f'  <title>{escape(title)}: {escape(shown)}</title>\n'
        f'  <rect x="0.5" y="0.5" width="{width - 1}" height="21" rx="11" '
        f'fill="#{background}" stroke="#{border}"/>\n'
        f'  <text x="{width // 2}" y="15" font-family="DejaVu Sans,Verdana,sans-serif" '
        f'font-size="11" font-weight="600" text-anchor="middle" fill="#{ink}">'
        f'{escape(shown)}</text>\n'
        f'</svg>\n'
    )

def render_badge_header(labels: Mapping[str, str], *, asset_dir: str) -> str:
    """Emit three local Markdown image links, to be placed just below H1."""
    _validate_values(labels)
    if (not asset_dir or asset_dir.startswith("/") or ":" in asset_dir
            or "\\" in asset_dir or "?" in asset_dir or "#" in asset_dir):
        raise LabelError("asset_dir must be a repository-relative Markdown path")
    return " ".join(
        f"![{axis.title()}: {labels[axis]}]"
        f"({asset_dir.rstrip('/')}/{badge_filename(axis, labels[axis])})"
        for axis in AXES
    )


def audit_document_labels(
    *,
    markdown: str,
    document_path: str,
    labels: Mapping[str, str],
    snapshot_sha: str,
    source_inventory: Iterable[str],
    inventory_complete: bool,
    badge_sources: Mapping[str, str],
) -> DocumentLabelAudit:
    """Check declared header labels, referenced local asset bytes and exact inventory.

    This cannot establish adoption authority, implementation behavior or
    independent human review. It is only a deterministic display integrity gate.
    """
    _validate_values(labels)
    if not isinstance(snapshot_sha, str) or SHA.fullmatch(snapshot_sha) is None:
        raise LabelError("snapshot_sha must be an exact 40-character lowercase hex SHA")
    if not inventory_complete:
        raise LabelError("source inventory not attested complete")
    if (not isinstance(document_path, str) or document_path.startswith("/")
            or "\\" in document_path or ":" in document_path
            or ".." in PurePosixPath(document_path).parts
            or not document_path.endswith(".md")):
        raise LabelError("unsafe document_path")
    inventory = set(source_inventory)
    if document_path not in inventory:
        raise LabelError("document_path missing from attested inventory")
    issues: list[str] = []
    lines = markdown.splitlines()
    if not lines or not lines[0].startswith("# "):
        issues.append("document must begin with Markdown H1")
    # The badge row is part of the H1 header, not a search anywhere in the
    # first ten lines. Permit a single blank line after H1, but no prose,
    # fenced-code opener, extra blank line, inline text, or reordered badges.
    row_index = 1
    if row_index < len(lines) and not lines[row_index].strip():
        row_index += 1
    row = lines[row_index] if row_index < len(lines) else ""
    matches = list(IMAGE.finditer(row))
    observed = [match.groups() for match in matches]
    exact_row = (
        len(matches) == len(AXES)
        and tuple(axis.casefold() for axis, _, _ in observed) == AXES
        and not row[:matches[0].start()].strip()
        and not row[matches[-1].end():].strip()
        and all(
            row[left.end():right.start()].isspace()
            for left, right in zip(matches, matches[1:])
        )
    ) if matches else False
    if not exact_row:
        issues.append("badges must form the exact Decision/Implementation/Review row immediately after H1")
    # A second status row near the top is ambiguous even when the first one
    # matches. This is a display-integrity failure, never semantic evidence.
    if IMAGE.search("\n".join(lines[row_index + 1:row_index + 10])):
        issues.append("duplicate status badge outside the canonical H1 row")
    for axis in AXES:
        rows = [(status, url) for axis_name, status, url in observed
                if axis_name.casefold() == axis]
        if len(rows) != 1:
            issues.append(f"expected exactly one {axis} badge after H1")
            continue
        status, href = rows[0]
        if status != labels[axis]:
            issues.append(f"{axis} badge differs from declared metadata")
            continue
        parsed = urlsplit(href)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or not parsed.path:
            issues.append(f"{axis} badge must reference a local SVG")
            continue
        normalized = posixpath.normpath(posixpath.join(
            posixpath.dirname(document_path), parsed.path))
        if normalized == ".." or normalized.startswith("../"):
            issues.append(f"{axis} badge path escapes repository")
            continue
        if posixpath.basename(normalized) != badge_filename(axis, status):
            issues.append(f"{axis} badge asset name does not match status")
            continue
        if normalized not in inventory:
            issues.append(f"{axis} badge not found in attested inventory")
            continue
        if badge_sources.get(normalized) != render_badge_svg(axis, status):
            issues.append(f"{axis} badge bytes differ from canonical palette")
    if len(observed) != len(AXES):
        issues.append("header must contain exactly three status badges")
    return DocumentLabelAudit(
        status="MATCH" if not issues else "MISMATCH",
        issues=tuple(issues),
        snapshot_sha=snapshot_sha,
    )
