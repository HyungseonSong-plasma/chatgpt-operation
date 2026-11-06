"""Read-only GitHub acquisition of an entire Core package for bounded Gate 1.

Uses GitHub's exact-commit Git tree/blob APIs. Read source only; no mutations,
no review authentication, no source-code execution and no global semantic PASS.
The transport can be injected for deterministic adversarial unit tests.
"""
from __future__ import annotations

import argparse
import base64
import binascii
from dataclasses import asdict, dataclass
import hashlib
import json
import re
import subprocess
from typing import Callable, Mapping

from chatgpt_operation.documentation.gate1_manifest_v01 import run_gate1_manifest_v01
from chatgpt_operation.documentation.semantic_gates_v01 import AutomatedGateV01
from chatgpt_operation.documentation.status_labels import LabelError


_SHA = re.compile(r"^[0-9a-f]{40}$")
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_ROOT = "src/codeqa/core/"
_SCHEMA = "contracts/ccg/graph-v0.1.schema.json"
_MAX_CORE_FILES = 256
_MAX_BYTES_PER_FILE = 1_000_000
_MAX_REPO_ENTRIES = 100_000


@dataclass(frozen=True)
class LiveCoreGate1Report:
    consumer_repository: str
    pr_number: int
    exact_head_sha: str
    git_tree_sha: str
    core_python_files: tuple[str, ...]
    blob_shas: Mapping[str, str]
    gate1: AutomatedGateV01
    acquisition: str = "GITHUB_EXACT_COMMIT_TREE_AND_BLOBS"
    independent_approval: str = "REVIEW_REQUIRED"
    semantic_certification: str = "NOT_EVALUATED"


def github_read_json(endpoint: str) -> Mapping[str, object]:
    """Only GitHub read API calls, authenticated through the local gh CLI."""
    if not endpoint.startswith("repos/") or "?" in endpoint.split("repos/", 1)[0]:
        raise LabelError("invalid GitHub API endpoint")
    completed = subprocess.run(
        ["gh", "api", endpoint], check=True, capture_output=True, text=True,
        timeout=45,
    )
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise LabelError("GitHub returned a non-object API response")
    return value


def _require_sha(value: object) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise LabelError("expected a full lowercase Git SHA-1")
    return value


def _git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(data)).encode("ascii") + bytes([0]) + data
    ).hexdigest()


def _decode_blob(blob: Mapping[str, object], sha: str) -> str:
    if blob.get("sha") != sha or blob.get("encoding") != "base64":
        raise LabelError("GitHub blob identity or encoding mismatch")
    encoded = blob.get("content")
    if not isinstance(encoded, str):
        raise LabelError("missing GitHub blob content")
    try:
        data = base64.b64decode("".join(encoded.split()), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise LabelError("invalid GitHub blob encoding") from exc
    if (len(data) > _MAX_BYTES_PER_FILE or blob.get("size") != len(data)
            or _git_blob_sha(data) != sha):
        raise LabelError("GitHub blob size or content does not match its SHA")
    if bytes([0]) in data:
        raise LabelError("binary source content is not allowed")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LabelError("source is not valid UTF-8") from exc


def collect_live_core_gate1_v01(
    *, repository: str, pr_number: int,
    read_json: Callable[[str], Mapping[str, object]] = github_read_json,
    expected_head_sha: str | None = None,
) -> LiveCoreGate1Report:
    """Check complete Core Python tree at pinned PR HEAD, then re-read HEAD.

    Requires an untruncated recursive Git tree. A missing or nonblob Python
    path, symlink, malformed API response or PR-head race fails closed.
    """
    if not isinstance(repository, str) or not _REPO.fullmatch(repository):
        raise LabelError("consumer_repository must be owner/repo")
    if type(pr_number) is not int or pr_number < 1:
        raise LabelError("PR number must be a positive integer")
    if expected_head_sha is not None:
        _require_sha(expected_head_sha)
    api = f"repos/{repository}"
    pr_endpoint = f"{api}/pulls/{pr_number}"
    start = read_json(pr_endpoint)
    if not isinstance(start, Mapping):
        raise LabelError("PR response invalid")
    state = start.get("state")
    merged = start.get("merged") is True
    if not (state == "open" or state == "closed" and merged):
        raise LabelError("PR must be open or verifiably merged")
    h = start.get("head")
    if not isinstance(h, Mapping) or not isinstance(h.get("repo"), Mapping):
        raise LabelError("PR head repository missing")
    if h["repo"].get("full_name") != repository:
        raise LabelError("cross-repository fork head requires separate acquisition")
    head = _require_sha(h.get("sha"))
    if expected_head_sha is not None and head != expected_head_sha:
        raise LabelError("PR head changed from expected revision")

    commit = read_json(f"{api}/git/commits/{head}")
    if not isinstance(commit, Mapping) or commit.get("sha") != head:
        raise LabelError("Git commit identity mismatch")
    tree_ref = commit.get("tree")
    if not isinstance(tree_ref, Mapping):
        raise LabelError("Git commit has no tree reference")
    tree_sha = _require_sha(tree_ref.get("sha"))
    tree = read_json(f"{api}/git/trees/{tree_sha}?recursive=1")
    if (not isinstance(tree, Mapping) or tree.get("sha") != tree_sha
            or tree.get("truncated") is not False):
        raise LabelError("Git tree identity invalid or listing truncated")
    entries = tree.get("tree")
    if not isinstance(entries, list) or len(entries) > _MAX_REPO_ENTRIES:
        raise LabelError("invalid or oversized Git tree listing")

    selected: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("path"), str):
            raise LabelError("malformed Git tree entry")
        path = entry["path"]
        if not (path == _SCHEMA or
                path.startswith(_ROOT) and path.endswith(".py")):
            continue
        if (path in selected or entry.get("type") != "blob"
                or entry.get("mode") not in ("100644", "100755")):
            raise LabelError("duplicate, symlink or nonblob required source")
        selected[path] = _require_sha(entry.get("sha"))
    core_paths = sorted(p for p in selected if p.startswith(_ROOT))
    if (not core_paths or f"{_ROOT}__init__.py" not in selected
            or len(core_paths) > _MAX_CORE_FILES or _SCHEMA not in selected):
        raise LabelError("incomplete Core inventory or missing CCG schema")

    source: dict[str, str] = {}
    for path in [_SCHEMA, *core_paths]:
        blob = read_json(f"{api}/git/blobs/{selected[path]}")
        if not isinstance(blob, Mapping):
            raise LabelError("invalid GitHub blob response")
        source[path] = _decode_blob(blob, selected[path])

    # Require HEAD to remain unchanged throughout acquisition.
    finish = read_json(pr_endpoint)
    final_head = finish.get("head") if isinstance(finish, Mapping) else None
    if (not isinstance(final_head, Mapping) or final_head.get("sha") != head
            or finish.get("state") != state
            or (finish.get("merged") is True) != merged):
        raise LabelError("PR identity or state changed during GitHub source acquisition")

    scope = "ccg-core-package-direct-import-v0.1"
    checks = [{
        "id": "ccg_contract_id",
        "kind": "JSON_POINTER_EQUALS",
        "path": _SCHEMA,
        "blob_sha": selected[_SCHEMA],
        "subject": "/$id",
        "expected": "urn:codeqa:ccg:graph:v0.1",
    }]
    for path in core_paths:
        checks.append({
            "id": "core." + path[len(_ROOT):].replace("/", "."),
            "kind": "PYTHON_PACKAGE_IMPORT_ABSENT",
            "path": path,
            "blob_sha": selected[path],
            "subject": "codeqa.adapters",
        })
    manifest = {
        "schema_version": 1,
        "description": "Full discovered Core Python tree; GitHub exact PR head",
        "consumer_repository": repository,
        "revision": head,
        "scope": scope,
        "checks": checks,
    }
    gate = run_gate1_manifest_v01(manifest=manifest, source_files=source)
    return LiveCoreGate1Report(
        consumer_repository=repository, pr_number=pr_number,
        exact_head_sha=head, git_tree_sha=tree_sha,
        core_python_files=tuple(core_paths),
        blob_shas=dict(sorted(selected.items())), gate1=gate,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only live Core source Gate 1")
    parser.add_argument("--repository", default="HyungseonSong-plasma/codeQA")
    parser.add_argument("--pr", type=int, default=289)
    parser.add_argument("--expected-head")
    args = parser.parse_args(argv)
    report = collect_live_core_gate1_v01(
        repository=args.repository, pr_number=args.pr,
        expected_head_sha=args.expected_head,
    )
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0 if report.gate1.status == "SCOPED_CHECKS_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
