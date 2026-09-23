"""Exact artifact staging with fail-closed source/destination contracts."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from typing import Any

SCHEMA_VERSION = 1
_FORBIDDEN_SELECTOR = re.compile(r"[*?[]")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class StagingError(ValueError):
    pass


def _exact_path(value: str, field: str, *, allow_absolute: bool) -> str:
    if not isinstance(value, str) or not value:
        raise StagingError(f"{field} must be a non-empty string")
    if _FORBIDDEN_SELECTOR.search(value):
        raise StagingError(f"{field} must identify one exact path; globs are forbidden: {value!r}")
    path = PurePosixPath(value)
    if ".." in path.parts:
        raise StagingError(f"{field} must not contain '..': {value!r}")
    if path.is_absolute() and not allow_absolute:
        raise StagingError(f"{field} must be workspace-relative: {value!r}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def load_spec(path: str | Path) -> dict[str, Any]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise StagingError(f"invalid staging JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise StagingError("staging root must be an object")
    extra = set(raw) - {"schema_version", "entries"}
    if extra:
        raise StagingError(f"staging: unknown fields {sorted(extra)}")
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise StagingError(f"schema_version must be {SCHEMA_VERSION}")
    entries = raw.get("entries")
    if not isinstance(entries, list) or not entries or len(entries) > 64:
        raise StagingError("entries must contain 1..64 items")

    allowed = {
        "id", "source", "destination", "producer", "location_evidence",
        "source_type", "symlink_policy", "overwrite", "expected_sha256",
    }
    seen_ids: set[str] = set()
    seen_destinations: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(entries):
        where = f"entries[{index}]"
        if not isinstance(item, dict):
            raise StagingError(f"{where} must be an object")
        extra = set(item) - allowed
        if extra:
            raise StagingError(f"{where}: unknown fields {sorted(extra)}")
        item_id = item.get("id")
        if not isinstance(item_id, str) or not _ID.fullmatch(item_id):
            raise StagingError(f"{where}.id is invalid")
        if item_id in seen_ids:
            raise StagingError(f"duplicate staging id: {item_id}")
        seen_ids.add(item_id)
        source = _exact_path(item.get("source", ""), f"{where}.source", allow_absolute=True)
        destination = _exact_path(
            item.get("destination", ""), f"{where}.destination", allow_absolute=False
        )
        if destination in seen_destinations:
            raise StagingError(f"duplicate staging destination: {destination}")
        seen_destinations.add(destination)
        producer = item.get("producer")
        evidence = item.get("location_evidence")
        if not isinstance(producer, str) or not producer.strip():
            raise StagingError(f"{where}.producer must be non-empty")
        if not isinstance(evidence, str) or not evidence.strip():
            raise StagingError(f"{where}.location_evidence must be non-empty")
        if item.get("source_type", "file") != "file":
            raise StagingError(f"{where}.source_type must be 'file' in v1")
        symlink_policy = item.get("symlink_policy", "reject")
        if symlink_policy not in {"reject", "materialize"}:
            raise StagingError(f"{where}.symlink_policy must be reject or materialize")
        overwrite = item.get("overwrite", False)
        if not isinstance(overwrite, bool):
            raise StagingError(f"{where}.overwrite must be boolean")
        expected = item.get("expected_sha256")
        if expected is not None:
            if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
                raise StagingError(f"{where}.expected_sha256 must be 64 hex characters")
            expected = expected.lower()
        normalized.append({
            "id": item_id,
            "source": source,
            "destination": destination,
            "producer": producer.strip(),
            "location_evidence": evidence.strip(),
            "symlink_policy": symlink_policy,
            "overwrite": overwrite,
            "expected_sha256": expected,
        })
    return {"schema_version": SCHEMA_VERSION, "entries": normalized}


def stage(*, spec_path: str | Path, workspace: str | Path) -> dict[str, Any]:
    spec = load_spec(spec_path)
    root = Path(workspace).resolve()
    if not root.is_dir():
        raise StagingError(f"workspace does not exist: {root}")
    results: list[dict[str, Any]] = []
    for entry in spec["entries"]:
        raw = Path(entry["source"])
        source = raw if raw.is_absolute() else root / raw
        if not source.exists() and not source.is_symlink():
            raise StagingError(
                f"ARTIFACT_LOCATION_UNRESOLVED: {entry['id']}: "
                f"source does not exist: {entry['source']}"
            )
        materialized = False
        if source.is_symlink():
            if entry["symlink_policy"] != "materialize":
                raise StagingError(f"{entry['id']}: source is a symlink but symlink_policy=reject")
            try:
                resolved = source.resolve(strict=True)
            except OSError as exc:
                raise StagingError(f"{entry['id']}: cannot resolve source symlink: {exc}") from exc
            materialized = True
        else:
            resolved = source.resolve()
        if not resolved.is_file():
            raise StagingError(f"{entry['id']}: source is not a regular file: {resolved}")

        digest = _sha256(resolved)
        if entry["expected_sha256"] and digest != entry["expected_sha256"]:
            raise StagingError(
                f"{entry['id']}: source SHA256 mismatch: actual={digest} "
                f"expected={entry['expected_sha256']}"
            )

        destination = root / entry["destination"]
        if not _under(destination.parent, root):
            raise StagingError(f"{entry['id']}: destination escapes workspace")
        destination.parent.mkdir(parents=True, exist_ok=True)

        status = "COPIED"
        if destination.exists() or destination.is_symlink():
            if destination.is_file() and not destination.is_symlink() and _sha256(destination) == digest:
                status = "NO_MUTATION_NEEDED"
            elif not entry["overwrite"]:
                raise StagingError(f"{entry['id']}: destination already exists with different content")
        if status == "COPIED":
            if destination.exists() or destination.is_symlink():
                destination.unlink()
            shutil.copy2(resolved, destination, follow_symlinks=True)

        staged_digest = _sha256(destination)
        if staged_digest != digest:
            raise StagingError(f"{entry['id']}: staged SHA256 mismatch after copy")
        mode = stat.S_IMODE(destination.stat().st_mode)
        results.append({
            "id": entry["id"],
            "status": status,
            "source": entry["source"],
            "resolved_source": str(resolved),
            "destination": entry["destination"],
            "producer": entry["producer"],
            "location_evidence": entry["location_evidence"],
            "symlink_materialized": materialized,
            "sha256": staged_digest,
            "mode": f"{mode:04o}",
            "size_bytes": destination.stat().st_size,
        })
    return {"schema_version": 1, "status": "PASS", "entries": results}


def self_test() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        real = root / "libx.so.0"
        real.write_bytes(b"payload")
        link = root / "libx.so"
        link.symlink_to(real.name)
        workspace = root / "workspace"
        workspace.mkdir()
        spec = root / "stage.json"
        spec.write_text(json.dumps({
            "schema_version": 1,
            "entries": [{
                "id": "libx",
                "source": str(link),
                "destination": "runtime/libx.so",
                "producer": "self-test build",
                "location_evidence": "self-test exact source",
                "symlink_policy": "materialize",
            }],
        }), encoding="utf-8")
        result = stage(spec_path=spec, workspace=workspace)
        assert result["status"] == "PASS"
        assert (workspace / "runtime/libx.so").read_bytes() == b"payload"
        bad = root / "bad.json"
        bad.write_text(json.dumps({
            "schema_version": 1,
            "entries": [{
                "id": "bad",
                "source": "/tmp/lib*.so",
                "destination": "runtime/lib.so",
                "producer": "test",
                "location_evidence": "test",
            }],
        }), encoding="utf-8")
        try:
            load_spec(bad)
        except StagingError:
            pass
        else:
            raise AssertionError("glob source must be rejected")
    print("ARTIFACT_STAGING_SELF_TEST=PASS")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="artifact-staging")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("stage")
    run.add_argument("--spec", required=True)
    run.add_argument("--workspace", required=True)
    run.add_argument("--evidence")
    sub.add_parser("self-test")
    args = parser.parse_args(argv)
    if args.command == "self-test":
        return self_test()
    try:
        result = stage(spec_path=args.spec, workspace=args.workspace)
    except (OSError, StagingError) as exc:
        print(f"ARTIFACT_STAGING=HARD_STOP {exc}")
        return 2
    if args.evidence:
        Path(args.evidence).write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print("ARTIFACT_STAGING=PASS")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
