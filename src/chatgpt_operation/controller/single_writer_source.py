"""Generate bounded, deterministic read-only progress evidence from tracked docs.

This script does not post GitHub comments or modify the authoritative ledger.
The source is the checked out reviewed Git SHA, not user-supplied findings.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .progress_resume import detail_digest

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_LINK = re.compile(r"\[[^\]\n]+\]\(([^)\n]+)\)")
_MAX_SOURCE_BYTES = 180_000
_MAX_LINKS = 500


class SourceEvidenceError(ValueError):
    pass


def make_readonly_document_manifest(
    *, repository_root: Path, unit_id: str, input_sha256: str,
    work_id: str, plan_sha256: str, policy_sha256: str,
    head_sha: str, run_id: int, run_attempt: int = 1,
) -> dict[str, Any]:
    if (
        not isinstance(unit_id, str)
        or not re.fullmatch(r"docs/[a-zA-Z0-9_./-]+\.md", unit_id)
        or ".." in Path(unit_id).parts
    ):
        raise SourceEvidenceError("document path is outside bounded pilot scope")
    if not isinstance(work_id, str) or not work_id.strip() or len(work_id) > 512:
        raise SourceEvidenceError("invalid work ID")
    for field, value in (
        ("input_sha256", input_sha256),
        ("plan_sha256", plan_sha256),
        ("policy_sha256", policy_sha256),
    ):
        if not isinstance(value, str) or not _SHA256.fullmatch(value):
            raise SourceEvidenceError(field + " must be exact SHA-256")
    if not isinstance(head_sha, str) or not _SHA40.fullmatch(head_sha):
        raise SourceEvidenceError("source head must be exact Git commit SHA")
    if type(run_id) is not int or run_id < 1 or run_attempt != 1:
        raise SourceEvidenceError("run identity or attempt invalid")
    root = repository_root.resolve(strict=True)
    target = (root / unit_id).resolve(strict=True)
    if root not in target.parents or not target.is_file() or target.is_symlink():
        raise SourceEvidenceError("unsafe or absent source path")
    if target.stat().st_size > _MAX_SOURCE_BYTES:
        raise SourceEvidenceError("source document exceeds pilot limit")
    raw = target.read_bytes()
    if not raw or len(raw) > _MAX_SOURCE_BYTES:
        raise SourceEvidenceError("empty or oversized document")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != input_sha256:
        raise SourceEvidenceError("document SHA differs from approved input")
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceEvidenceError("non-UTF8 Markdown source") from exc
    links = [
        {"line": index, "target": match.group(1)}
        for index, line in enumerate(content.splitlines(), start=1)
        for match in _LINK.finditer(line)
    ]
    if len(links) > _MAX_LINKS:
        raise SourceEvidenceError("document link inventory exceeds limit")
    details = {
        "file": unit_id,
        "source_sha256": digest,
        "byte_count": len(raw),
        "line_count": len(content.splitlines()),
        "markdown_link_occurrences": links,
    }
    return {
        "schema_version": 1,
        "work_id": work_id,
        "unit_id": unit_id,
        "input_sha256": input_sha256,
        "outcome": "PASS",
        "detail_sha256": detail_digest(details),
        "detail": details,
        "head_sha": head_sha,
        "workflow_run_id": run_id,
        "run_attempt": run_attempt,
        "plan_sha256": plan_sha256,
        "policy_sha256": policy_sha256,
    }


def _main() -> None:
    import argparse
    import os
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    args = p.parse_args()
    manifest = make_readonly_document_manifest(
        repository_root=Path("."),
        unit_id=os.environ["SAMUEL_UNIT_ID"],
        input_sha256=os.environ["SAMUEL_INPUT_SHA256"],
        work_id=os.environ["SAMUEL_WORK_ID"],
        plan_sha256=os.environ["SAMUEL_PLAN_SHA256"],
        policy_sha256=os.environ["SAMUEL_POLICY_SHA256"],
        head_sha=os.environ["GITHUB_SHA"],
        run_id=int(os.environ["GITHUB_RUN_ID"]),
        run_attempt=int(os.environ["GITHUB_RUN_ATTEMPT"]),
    )
    Path(args.output).write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    _main()
