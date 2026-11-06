"""Run a bounded, pinned Gate 1 manifest over caller-supplied source bytes.

The manifest is consumer-specific policy, not a trusted remote attestation.
GitHub/source acquisition and manifest review remain outside this pure module.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path, PurePosixPath
from typing import Mapping

from .semantic_gates_v01 import AutomatedGateV01, verify_automated_gate_v01
from .status_labels import LabelError


def _path_ok(path: object) -> bool:
    return (
        isinstance(path, str)
        and bool(path)
        and not path.startswith("/")
        and chr(92) not in path
        and ":" not in path
        and all(p not in ("", ".", "..") for p in path.split("/"))
        and PurePosixPath(path).as_posix() == path
    )


def run_gate1_manifest_v01(
    *, manifest: Mapping[str, object], source_files: Mapping[str, str],
) -> AutomatedGateV01:
    """Evaluate every pinned check, rejecting added sources and skipped checks.

    A check's expected Git blob SHA is read from the versioned manifest, not
    computed from the supplied content. This prevents substituted source
    bytes from silently changing the expected identity.
    """
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != 1:
        raise LabelError("unsupported Gate 1 manifest version")
    if set(manifest) != {
        "schema_version", "description", "consumer_repository",
        "revision", "scope", "checks",
    }:
        raise LabelError("Gate 1 manifest must have exactly the known fields")
    definitions = manifest["checks"]
    if not isinstance(definitions, list) or not definitions:
        raise LabelError("Gate 1 manifest needs a nonempty check list")
    if not isinstance(source_files, Mapping):
        raise LabelError("source_files must be a mapping")
    required_ids: list[str] = []
    required_paths: set[str] = set()
    for c in definitions:
        if not isinstance(c, Mapping):
            raise LabelError("manifest check must be an object")
        needed = {"id", "kind", "path", "blob_sha", "subject"}
        if not needed <= set(c) or not set(c) <= needed | {"expected"}:
            raise LabelError("manifest check has missing or unknown fields")
        if not isinstance(c["id"], str) or not c["id"]:
            raise LabelError("manifest check id must be nonempty")
        if not _path_ok(c["path"]):
            raise LabelError("manifest check has unsafe path")
        if not isinstance(c["blob_sha"], str) or not isinstance(c["subject"], str):
            raise LabelError("manifest check has invalid blob/subject")
        if not isinstance(c["kind"], str):
            raise LabelError("manifest check has invalid kind")
        if c["kind"] == "JSON_POINTER_EQUALS" and not isinstance(c.get("expected"), str):
            raise LabelError("JSON check missing expected string")
        required_ids.append(c["id"])
        required_paths.add(c["path"])
    if len(set(required_ids)) != len(required_ids):
        raise LabelError("duplicate Gate 1 check id")
    if any(not _path_ok(k) or not isinstance(v, str)
           for k, v in source_files.items()):
        raise LabelError("invalid source file mapping")
    if set(source_files) - required_paths:
        raise LabelError("unrequested source file supplied")
    bound_checks: dict[str, dict[str, str]] = {}
    for c in definitions:
        path = c["path"]
        if path not in source_files:
            continue
        bound_checks[c["id"]] = {
            "kind": c["kind"],
            "repository": manifest["consumer_repository"],
            "revision": manifest["revision"],
            "scope": manifest["scope"],
            "path": path,
            "blob_sha": c["blob_sha"],
            "content": source_files[path],
            "subject": c["subject"],
        }
        if "expected" in c:
            bound_checks[c["id"]]["expected"] = c["expected"]
    return verify_automated_gate_v01(
        repository=manifest["consumer_repository"],
        revision=manifest["revision"],
        scope=manifest["scope"],
        required_checks=tuple(required_ids),
        checks=bound_checks,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pinned static Gate 1 checks")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--snapshot-root", required=True, type=Path)
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    files: dict[str, str] = {}
    for check in manifest["checks"]:
        name = check["path"]
        if not _path_ok(name):
            raise LabelError("unsafe manifest path")
        candidate = args.snapshot_root.joinpath(*name.split("/"))
        if candidate.is_symlink():
            raise LabelError("snapshot file symlink is forbidden")
        if candidate.is_file():
            files[name] = candidate.read_text(encoding="utf-8")
    outcome = run_gate1_manifest_v01(manifest=manifest, source_files=files)
    print(json.dumps(asdict(outcome), indent=2, sort_keys=True))
    return 0 if outcome.status == "SCOPED_CHECKS_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
