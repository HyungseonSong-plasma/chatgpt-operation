"""Governed build-once / fan-out / fan-in matrix mechanics."""
from __future__ import annotations

from dataclasses import dataclass
import argparse
import glob
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from typing import Any

from chatgpt_operation.work.manifest import load_manifest, validate_dispatch

SCHEMA_VERSION = 1
_CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_FORBIDDEN_GLOB = re.compile(r"[*?[]")
_BUNDLE_EPHEMERAL_DIRS = {".git", ".jitcache", "__pycache__", ".pytest_cache"}


class MatrixError(ValueError):
    pass


def _relative_path(value: str, field: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise MatrixError(
            f"{field} must be a repository-relative path without '..': {value!r}"
        )
    return value


def _manifest_path(value: str, field: str) -> str:
    value = _relative_path(value, field)
    prefix = "automation/manifests/experiments/"
    if not value.startswith(prefix) or not value.endswith(".json"):
        raise MatrixError(f"{field} must be below {prefix} and end in .json")
    return value


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _git_head(workspace: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(workspace), "rev-parse", "HEAD"], text=True
    ).strip()


@dataclass(frozen=True)
class RunSpec:
    spec_id: str
    name: str
    command: tuple[str, ...]
    cwd: str
    timeout_seconds: int
    artifacts: tuple[str, ...]


@dataclass(frozen=True)
class MatrixManifest:
    issue: int
    sequence: int
    title: str
    prepare_manifest: str
    bundle_paths: tuple[str, ...]
    max_parallel: int
    cases: tuple[RunSpec, ...]
    aggregate: RunSpec | None


def _require_keys(raw: dict[str, Any], allowed: set[str], where: str) -> None:
    extra = set(raw) - allowed
    if extra:
        raise MatrixError(f"{where}: unknown fields {sorted(extra)}")


def _run_spec(raw: Any, where: str, *, require_id: bool) -> RunSpec:
    if not isinstance(raw, dict):
        raise MatrixError(f"{where} must be an object")
    allowed = {"id", "name", "command", "cwd", "timeout_seconds", "artifacts"}
    _require_keys(raw, allowed, where)
    spec_id = raw.get("id", "aggregate")
    if require_id and (not isinstance(spec_id, str) or not _CASE_ID.fullmatch(spec_id)):
        raise MatrixError(f"{where}.id is invalid")
    name = raw.get("name")
    command = raw.get("command")
    cwd = raw.get("cwd", ".")
    timeout = raw.get("timeout_seconds", 900)
    artifacts = raw.get("artifacts", [])
    if not isinstance(name, str) or not name.strip():
        raise MatrixError(f"{where}.name must be non-empty")
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(value, str) or not value for value in command)
    ):
        raise MatrixError(f"{where}.command must be a non-empty string array")
    if not isinstance(cwd, str):
        raise MatrixError(f"{where}.cwd must be a string")
    if cwd != ".":
        _relative_path(cwd, f"{where}.cwd")
    if not isinstance(timeout, int) or not (1 <= timeout <= 7200):
        raise MatrixError(f"{where}.timeout_seconds must be 1..7200")
    if (
        not isinstance(artifacts, list)
        or any(not isinstance(value, str) for value in artifacts)
    ):
        raise MatrixError(f"{where}.artifacts must be a string array")
    return RunSpec(
        str(spec_id),
        name.strip(),
        tuple(command),
        cwd,
        timeout,
        tuple(_relative_path(value, f"{where}.artifact") for value in artifacts),
    )


def load_matrix_manifest(path: str | Path) -> MatrixManifest:
    source = Path(path).resolve()
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except Exception as exc:
        raise MatrixError(f"invalid matrix manifest JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise MatrixError("matrix manifest root must be an object")
    _require_keys(
        raw,
        {
            "schema_version",
            "issue",
            "sequence",
            "title",
            "prepare_manifest",
            "bundle_paths",
            "max_parallel",
            "cases",
            "aggregate",
        },
        "matrix manifest",
    )
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise MatrixError(f"schema_version must be {SCHEMA_VERSION}")
    issue = raw.get("issue")
    sequence = raw.get("sequence")
    title = raw.get("title")
    if not isinstance(issue, int) or issue <= 0:
        raise MatrixError("issue must be a positive integer")
    if not isinstance(sequence, int) or sequence <= 0:
        raise MatrixError("sequence must be a positive integer")
    if not isinstance(title, str) or not title.strip():
        raise MatrixError("title must be a non-empty string")

    prepare_manifest = _manifest_path(raw.get("prepare_manifest", ""), "prepare_manifest")
    bundle = raw.get("bundle_paths")
    if (
        not isinstance(bundle, list)
        or not bundle
        or any(not isinstance(value, str) for value in bundle)
    ):
        raise MatrixError("bundle_paths must be a non-empty string array")
    bundle_paths: list[str] = []
    for index, value in enumerate(bundle):
        value = _relative_path(value, f"bundle_paths[{index}]")
        if _FORBIDDEN_GLOB.search(value):
            raise MatrixError("bundle_paths must be exact files/directories, not globs")
        bundle_paths.append(value)
    if len(set(bundle_paths)) != len(bundle_paths):
        raise MatrixError("bundle_paths must be unique")
    pure = [PurePosixPath(value) for value in bundle_paths]
    for i, left in enumerate(pure):
        for j, right in enumerate(pure):
            if i != j and left in right.parents:
                raise MatrixError("bundle_paths must not overlap")

    max_parallel = raw.get("max_parallel", 4)
    if not isinstance(max_parallel, int) or not (1 <= max_parallel <= 8):
        raise MatrixError("max_parallel must be 1..8")

    raw_cases = raw.get("cases")
    if not isinstance(raw_cases, list) or not (1 <= len(raw_cases) <= 16):
        raise MatrixError("cases must contain 1..16 entries")
    cases = tuple(
        _run_spec(item, f"cases[{index}]", require_id=True)
        for index, item in enumerate(raw_cases)
    )
    ids = [case.spec_id for case in cases]
    if len(ids) != len(set(ids)):
        raise MatrixError("case ids must be unique")

    raw_aggregate = raw.get("aggregate")
    aggregate = (
        None
        if raw_aggregate is None
        else _run_spec(raw_aggregate, "aggregate", require_id=False)
    )
    return MatrixManifest(
        issue,
        sequence,
        title.strip(),
        prepare_manifest,
        tuple(bundle_paths),
        max_parallel,
        cases,
        aggregate,
    )


def _matrix_path(control_root: Path, manifest_path: Path) -> None:
    expected = control_root / "automation" / "manifests" / "experiments"
    if not _under(manifest_path, expected):
        raise MatrixError(f"matrix manifest must be below {expected}")


def validate_matrix(
    manifest: MatrixManifest,
    *,
    control_root: Path,
    issue: int,
    sequence: int,
) -> None:
    if manifest.issue != issue or manifest.sequence != sequence:
        raise MatrixError(
            f"dispatch identity mismatch: manifest=Issue_{manifest.issue}_experiments"
            f"{manifest.sequence:02d} dispatch=Issue_{issue}_experiments{sequence:02d}"
        )
    prepare_path = control_root / manifest.prepare_manifest
    prepare = load_manifest(prepare_path)
    validate_dispatch(prepare, kind="experiments", issue=issue, sequence=sequence)


def plan(
    *,
    manifest_path: str | Path,
    control_root: str | Path,
    issue: int,
    sequence: int,
) -> dict[str, object]:
    root = Path(control_root).resolve()
    source = Path(manifest_path).resolve()
    _matrix_path(root, source)
    manifest = load_matrix_manifest(source)
    validate_matrix(manifest, control_root=root, issue=issue, sequence=sequence)
    return {
        "matrix": {"include": [{"id": case.spec_id} for case in manifest.cases]},
        "max_parallel": manifest.max_parallel,
        "prepare_manifest": manifest.prepare_manifest,
        "has_aggregate": manifest.aggregate is not None,
    }


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_bundle(
    *,
    manifest_path: str | Path,
    control_root: str | Path,
    workspace: str | Path,
    issue: int,
    sequence: int,
    output: str | Path,
) -> dict[str, object]:
    root = Path(control_root).resolve()
    source = Path(manifest_path).resolve()
    work = Path(workspace).resolve()
    _matrix_path(root, source)
    manifest = load_matrix_manifest(source)
    validate_matrix(manifest, control_root=root, issue=issue, sequence=sequence)
    target = Path(output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    def safe_info(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        name = PurePosixPath(info.name)
        if any(part in _BUNDLE_EPHEMERAL_DIRS for part in name.parts):
            return None
        if info.issym() or info.islnk():
            raise MatrixError(f"bundle refuses link member: {info.name}")
        return info

    with tarfile.open(target, "w:gz") as archive:
        for relative in manifest.bundle_paths:
            item = work / relative
            if not item.exists() or not _under(item, work):
                raise MatrixError(f"bundle path missing/outside workspace: {relative}")
            if item.is_symlink():
                try:
                    resolved = item.resolve(strict=True)
                except OSError as exc:
                    raise MatrixError(f"bundle symlink cannot be resolved: {relative}: {exc}") from exc
                if not _under(resolved, work) or not resolved.is_file():
                    raise MatrixError(
                        f"bundle symlink target must be a file inside workspace: {relative}"
                    )
                archive.add(
                    resolved,
                    arcname=relative,
                    recursive=False,
                    filter=safe_info,
                )
            else:
                archive.add(item, arcname=relative, recursive=True, filter=safe_info)
    return {
        "path": str(target),
        "sha256": _hash_file(target),
        "bundle_paths": list(manifest.bundle_paths),
    }


def extract_bundle(*, archive_path: str | Path, workspace: str | Path) -> dict[str, object]:
    archive_path = Path(archive_path).resolve()
    work = Path(workspace).resolve()
    work.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts:
                raise MatrixError(f"unsafe archive member: {member.name}")
            if member.issym() or member.islnk():
                raise MatrixError(f"archive links are forbidden: {member.name}")
            if not _under(work / member.name, work):
                raise MatrixError(f"archive member escapes workspace: {member.name}")
        archive.extractall(work)
    return {"sha256": _hash_file(archive_path), "members": len(members)}


def _copy_artifacts(
    workspace: Path, patterns: tuple[str, ...], target: Path
) -> list[str]:
    copied: list[str] = []
    for pattern in patterns:
        for raw in sorted(glob.glob(str(workspace / pattern), recursive=True)):
            source = Path(raw)
            if not source.is_file() or not _under(source, workspace):
                continue
            relative = source.resolve().relative_to(workspace.resolve())
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied.append(str(relative))
    return copied


def _execute_spec(
    *,
    manifest: MatrixManifest,
    spec: RunSpec,
    workspace: Path,
    base_sha: str,
    results: Path,
    phase: str,
    extra_env: dict[str, str] | None = None,
) -> int:
    actual = _git_head(workspace)
    if actual != base_sha:
        raise MatrixError(f"workspace SHA mismatch: actual={actual} expected={base_sha}")
    cwd = workspace if spec.cwd == "." else workspace / spec.cwd
    if not cwd.is_dir() or not _under(cwd, workspace):
        raise MatrixError(f"invalid {phase} cwd: {cwd}")
    results.mkdir(parents=True, exist_ok=True)
    log_path = results / f"{phase}.log"
    env = os.environ.copy()
    env.update(
        {
            "CHATGPT_MATRIX_ISSUE": str(manifest.issue),
            "CHATGPT_MATRIX_SEQUENCE": str(manifest.sequence),
            "CHATGPT_MATRIX_PHASE": phase,
            "CHATGPT_MATRIX_RESULTS_DIR": str(results),
        }
    )
    if extra_env:
        env.update(extra_env)
    record: dict[str, object] = {
        "schema_version": 1,
        "issue": manifest.issue,
        "sequence": manifest.sequence,
        "title": manifest.title,
        "phase": phase,
        "id": spec.spec_id,
        "name": spec.name,
        "base_sha": base_sha,
        "command": list(spec.command),
        "cwd": spec.cwd,
        "timeout_seconds": spec.timeout_seconds,
        "result": "FAIL",
    }
    started = time.perf_counter()
    failure: dict[str, object] | None = None
    try:
        with log_path.open("w", encoding="utf-8") as log:
            completed = subprocess.run(
                list(spec.command),
                cwd=cwd,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=spec.timeout_seconds,
                check=False,
                text=True,
            )
        record["returncode"] = completed.returncode
        if completed.returncode == 0:
            record["result"] = "PASS"
        else:
            failure = {
                "class": "NONZERO_EXIT",
                "returncode": completed.returncode,
            }
    except subprocess.TimeoutExpired:
        record["returncode"] = 124
        failure = {"class": "TIMEOUT", "returncode": 124}
    except Exception as exc:
        record["returncode"] = None
        failure = {"class": "EXECUTION_ERROR", "detail": str(exc)}
    record["wall_seconds"] = round(time.perf_counter() - started, 6)
    record["artifacts"] = _copy_artifacts(
        workspace, spec.artifacts, results / "artifacts"
    )
    if failure is not None:
        record["failure"] = failure
    evidence_path = results / "evidence.json"
    evidence_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"MATRIX_PHASE={phase}")
    print(f"MATRIX_ID={spec.spec_id}")
    print(f"RESULT={record['result']}")
    print(f"EVIDENCE={evidence_path}")
    return 0 if record["result"] == "PASS" else 1


def run_case(args: argparse.Namespace) -> int:
    root = Path(args.control_root).resolve()
    source = Path(args.manifest).resolve()
    _matrix_path(root, source)
    manifest = load_matrix_manifest(source)
    validate_matrix(
        manifest, control_root=root, issue=args.issue, sequence=args.sequence
    )
    by_id = {case.spec_id: case for case in manifest.cases}
    if args.case not in by_id:
        raise MatrixError(f"unknown case id: {args.case}")
    return _execute_spec(
        manifest=manifest,
        spec=by_id[args.case],
        workspace=Path(args.workspace).resolve(),
        base_sha=args.base_sha,
        results=Path(args.results).resolve(),
        phase=f"case-{args.case}",
    )


def run_aggregate(args: argparse.Namespace) -> int:
    root = Path(args.control_root).resolve()
    source = Path(args.manifest).resolve()
    _matrix_path(root, source)
    manifest = load_matrix_manifest(source)
    validate_matrix(
        manifest, control_root=root, issue=args.issue, sequence=args.sequence
    )
    if manifest.aggregate is None:
        print("MATRIX_AGGREGATE=SKIPPED")
        return 0
    evidence_root = Path(args.evidence_root).resolve()
    return _execute_spec(
        manifest=manifest,
        spec=manifest.aggregate,
        workspace=Path(args.workspace).resolve(),
        base_sha=args.base_sha,
        results=Path(args.results).resolve(),
        phase="aggregate",
        extra_env={"CHATGPT_MATRIX_EVIDENCE_ROOT": str(evidence_root)},
    )


def self_test() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        control = root / "control"
        workspace = root / "workspace"
        manifests = control / "automation" / "manifests" / "experiments"
        manifests.mkdir(parents=True)
        workspace.mkdir()
        subprocess.run(["git", "init", "-q", str(workspace)], check=True)
        subprocess.run(
            ["git", "-C", str(workspace), "config", "user.email", "test@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(workspace), "config", "user.name", "test"],
            check=True,
        )
        executable = workspace / "tool"
        executable.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
        executable.chmod(0o755)
        payload = workspace / "payload"
        real_library = workspace / "libreal.so.1"
        real_library.write_text("shared-library-bytes\n", encoding="utf-8")
        explicit_link = workspace / "libalias.so.0"
        explicit_link.symlink_to(real_library.name)
        cache = payload / ".jitcache"
        cache.mkdir(parents=True)
        (payload / "input.txt").write_text("input\n", encoding="utf-8")
        (cache / "root-owned-cache").write_text("ephemeral\n", encoding="utf-8")
        cache.chmod(0)
        subprocess.run(
            ["git", "-C", str(workspace), "add", "tool", "payload/input.txt", "libreal.so.1", "libalias.so.0"],
            check=True,
        )
        subprocess.run(["git", "-C", str(workspace), "commit", "-qm", "x"], check=True)
        sha = _git_head(workspace)
        prep = manifests / "prep.json"
        prep.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "issue": 1,
                    "kind": "experiments",
                    "sequence": 1,
                    "title": "prep",
                    "stages": [
                        {"id": "P0", "name": "pass", "command": ["python3", "-c", "print('ok')"]}
                    ],
                    "artifacts": [],
                }
            ),
            encoding="utf-8",
        )
        matrix = manifests / "matrix.json"
        matrix.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "issue": 1,
                    "sequence": 1,
                    "title": "matrix",
                    "prepare_manifest": "automation/manifests/experiments/prep.json",
                    "bundle_paths": ["tool", "payload", "libalias.so.0"],
                    "max_parallel": 2,
                    "cases": [
                        {
                            "id": "a",
                            "name": "a",
                            "command": ["python3", "-c", "open('case.txt','w').write('a')"],
                            "artifacts": ["case.txt"],
                        }
                    ],
                    "aggregate": {
                        "name": "aggregate",
                        "command": ["python3", "-c", "open('summary.txt','w').write('ok')"],
                        "artifacts": ["summary.txt"],
                    },
                }
            ),
            encoding="utf-8",
        )
        planned = plan(
            manifest_path=matrix, control_root=control, issue=1, sequence=1
        )
        assert planned["matrix"]["include"] == [{"id": "a"}]
        bundle = root / "bundle.tar.gz"
        try:
            create_bundle(
                manifest_path=matrix,
                control_root=control,
                workspace=workspace,
                issue=1,
                sequence=1,
                output=bundle,
            )
        finally:
            cache.chmod(0o700)
        extracted = root / "extracted"
        extract_bundle(archive_path=bundle, workspace=extracted)
        assert os.access(extracted / "tool", os.X_OK)
        assert (extracted / "payload" / "input.txt").is_file()
        assert not (extracted / "payload" / ".jitcache").exists()
        extracted_alias = extracted / "libalias.so.0"
        assert extracted_alias.is_file()
        assert not extracted_alias.is_symlink()
        assert extracted_alias.read_text(encoding="utf-8") == "shared-library-bytes\n"
        args = argparse.Namespace(
            manifest=str(matrix),
            control_root=str(control),
            workspace=str(workspace),
            base_sha=sha,
            issue=1,
            sequence=1,
            case="a",
            results=str(root / "case-results"),
        )
        assert run_case(args) == 0
        assert (root / "case-results" / "artifacts" / "case.txt").is_file()
    print("GOVERNED_MATRIX_SELF_TEST=PASS")
    return 0
