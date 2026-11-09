"""Produce a read-only, exact-HEAD Markdown audit receipt for one Child unit.

The source file's raw bytes must equal the parent-approved input SHA-256.
No code changes, PR merge, policy evaluation or cross-repository access.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .agent_issue_partition import (
    AgentIssueError, make_receipt, validate_assignment,
)

_MAX_BYTES = 180_000
_MAX_LINKS = 500
_DOC_PATH = re.compile(r"docs/[A-Za-z0-9_./-]+\.md\Z")
_LINK = re.compile(r"\[[^\]\n]+\]\(([^)\n]+)\)")


class AgentSourceError(AgentIssueError):
    pass


def build_readonly_document_receipt(
    assignment: dict[str, Any], *,
    unit_id: str, run_id: int,
    source_sha: str, root: Path,
) -> dict[str, Any]:
    """Read the reviewed checkout; do not treat arbitrary files as units."""
    a = validate_assignment(assignment)
    if source_sha != a["source_head_sha"]:
        raise AgentSourceError("workflow HEAD differs from approved Child source")
    if not isinstance(unit_id, str) or _DOC_PATH.fullmatch(unit_id) is None:
        raise AgentSourceError("only scoped Markdown document audits are qualified")
    parts=Path(unit_id).parts
    if not parts or ".." in parts:
        raise AgentSourceError("path traversal is not allowed")
    expected = next((u for u in a["units"] if u["id"] == unit_id), None)
    if expected is None:
        raise AgentSourceError("unit not in parent-approved Child assignment")
    basedir = root.resolve(strict=True)
    candidate = basedir / unit_id
    if candidate.is_symlink():
        raise AgentSourceError("symlinked document is not a trusted source")
    final = candidate.resolve(strict=True)
    if basedir not in final.parents or not final.is_file():
        raise AgentSourceError("unsafe source path")
    if not 0 < final.stat().st_size <= _MAX_BYTES:
        raise AgentSourceError("empty or oversized source document")
    raw=final.read_bytes()
    if not 0 < len(raw) <= _MAX_BYTES:
        raise AgentSourceError("invalid source content size")
    raw_sha=hashlib.sha256(raw).hexdigest()
    if raw_sha != expected["input_sha256"]:
        raise AgentSourceError("reviewed source content SHA changed")
    try:
        decoded=raw.decode("utf-8")
    except UnicodeError as exc:
        raise AgentSourceError("unreadable UTF-8 document") from exc
    links=[
        {"line":line_no,"target":match.group(1)}
        for line_no,line in enumerate(decoded.splitlines(),1)
        for match in _LINK.finditer(line)
    ]
    if len(links) > _MAX_LINKS:
        raise AgentSourceError("document references exceed bounded audit")
    detail={
        "kind":"readonly_markdown_reference_inventory",
        "file":unit_id, "source_sha256":raw_sha,
        "byte_count":len(raw),
        "line_count":len(decoded.splitlines()),
        "links":links,
    }
    return make_receipt(
        a,unit_id=unit_id,input_sha256=raw_sha,
        outcome="PASS",detail=detail,source_run_id=run_id,
    )
