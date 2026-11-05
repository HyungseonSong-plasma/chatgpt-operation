"""DEA v0.1: read-only historical source replay, not an Arena competition.

Verifies two exact codeQA commits against local Git object bytes, measures
identical Pipeline file selections, and refuses to infer a champion or approval.
No branch creation, checkout, repository mutation, API or model invocation.
"""
from __future__ import annotations

import argparse
import ast
from hashlib import sha1
import json
from pathlib import Path
import re
import subprocess
from typing import Any

SHA = re.compile(r"[0-9a-f]{40}\Z")
PREFIX = "src/codeqa/pipeline/"


class ReplayError(ValueError):
    pass


def _sha(value: str, label: str) -> None:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ReplayError(f"{label} requires a lowercase 40-digit SHA")


def _git(root: Path, *args: str) -> bytes:
    if args[0] not in {"rev-parse", "ls-tree", "cat-file", "merge-base"}:
        raise ReplayError("non-read-only command")
    try:
        result = subprocess.run(["git", *args], cwd=root,
                                capture_output=True, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReplayError("Git read failed") from exc
    if result.returncode != 0:
        raise ReplayError("pinned Git evidence unavailable or inconsistent")
    return result.stdout


def _direct_sites(data: bytes, path: str) -> list[int]:
    try:
        tree = ast.parse(data, filename=path)
    except (SyntaxError, ValueError, UnicodeError) as exc:
        raise ReplayError("unparseable source: " + path) from exc
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            lines.extend(node.lineno for alias in node.names
                         if alias.name == "subprocess" or alias.name.startswith("subprocess."))
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            lines.append(node.lineno)
    if len(lines) != len(set(lines)):
        raise ReplayError("ambiguous duplicate import lines")
    return sorted(lines)


def _snapshot(root: Path, commit: str) -> list[dict[str, Any]]:
    if _git(root, "rev-parse", f"{commit}^{{commit}}").decode("ascii").strip() != commit:
        raise ReplayError("commit resolution drift")
    raw = _git(root, "ls-tree", "-rz", commit, "--", PREFIX.rstrip("/"))
    items: list[dict[str, Any]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, path_bytes = record.split(b"\t", 1)
            mode, kind, blob = metadata.decode("ascii").split(" ")
            path = path_bytes.decode("utf-8", errors="strict")
        except (ValueError, UnicodeError) as exc:
            raise ReplayError("invalid Git tree entry") from exc
        if not path.startswith(PREFIX) or not path.endswith(".py"):
            continue
        if path.count("/") != PREFIX.count("/"):
            continue
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ReplayError("invalid source object")
        _sha(blob, "blob")
        data = _git(root, "cat-file", "blob", blob)
        sealed = sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
        if sealed != blob:
            raise ReplayError("blob SHA mismatch")
        if any(item["path"] == path for item in items):
            raise ReplayError("duplicate source path")
        items.append({"path": path, "git_blob_sha": blob,
                      "direct_subprocess_import_lines": _direct_sites(data, path)})
    items.sort(key=lambda item: item["path"])
    if not items:
        raise ReplayError("empty source selection")
    return items


def replay(root: Path, *, before: str, after: str) -> dict[str, Any]:
    """Evidence-only comparison. No competing candidates or trusted fitness oracle."""
    _sha(before, "before")
    _sha(after, "after")
    if before == after:
        raise ReplayError("before and after must differ")
    root = Path(root).resolve()
    if not root.is_dir():
        raise ReplayError("repository absent")
    _git(root, "merge-base", "--is-ancestor", before, after)
    a, b = _snapshot(root, before), _snapshot(root, after)
    if [x["path"] for x in a] != [x["path"] for x in b]:
        raise ReplayError("changed denominator")
    n0 = sum(len(x["direct_subprocess_import_lines"]) for x in a)
    n1 = sum(len(x["direct_subprocess_import_lines"]) for x in b)
    return {
        "schema_version": 1,
        "comparison_kind": "historical_same_scope_not_competing_candidates",
        "before_sha": before,
        "after_sha": after,
        "selected_python_files": len(a),
        "source_before": a,
        "source_after": b,
        "direct_subprocess_import_sites_before": n0,
        "direct_subprocess_import_sites_after": n1,
        "site_delta": n1 - n0,
        "measured_source_fact": "REDUCED" if n1 < n0 else "UNCHANGED" if n1 == n0 else "INCREASED",
        "evidence_assurance": "INDEPENDENT_LOCAL_GIT_OBJECT_READBACK",
        "semantic_compatibility": "NOT_EVALUATED",
        "external_consumers": "NOT_EVALUATED",
        "equal_candidate_fitness_oracle": "NOT_EVALUATED",
        "champion": None,
        "champion_promoted": False,
        "repository_mutation_authorized": False,
        "decision": "EVIDENCE_ONLY",
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", required=True, type=Path)
    p.add_argument("--before", required=True)
    p.add_argument("--after", required=True)
    args = p.parse_args()
    try:
        result = replay(args.repo, before=args.before, after=args.after)
    except ReplayError as exc:
        p.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
