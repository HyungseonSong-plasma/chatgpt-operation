"""Closed-world manifest schema for governed repository work."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

SCHEMA_VERSION = 1
KINDS = {"experiments", "refactor"}
_STAGE = re.compile(r"^[A-Z][A-Z0-9_-]{0,31}$")


class ManifestError(ValueError):
    pass


def _relative_path(value: str, field: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ManifestError(
            f"{field} must be a repository-relative path without '..': {value!r}"
        )
    return value


@dataclass(frozen=True)
class Stage:
    stage_id: str
    name: str
    command: tuple[str, ...]
    cwd: str = "."
    timeout_seconds: int = 900


@dataclass(frozen=True)
class WorkManifest:
    issue: int
    kind: str
    sequence: int
    title: str
    stages: tuple[Stage, ...]
    artifacts: tuple[str, ...] = ()

    @property
    def identity(self) -> str:
        return f"Issue_{self.issue}_{self.kind}{self.sequence:02d}"


def _require_keys(raw: dict[str, Any], allowed: set[str], where: str) -> None:
    extra = set(raw) - allowed
    if extra:
        raise ManifestError(f"{where}: unknown fields {sorted(extra)}")


def load_manifest(path: str | Path) -> WorkManifest:
    source = Path(path).resolve()
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ManifestError(f"invalid manifest JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ManifestError("manifest root must be an object")
    _require_keys(
        raw,
        {
            "schema_version",
            "issue",
            "kind",
            "sequence",
            "title",
            "stages",
            "artifacts",
        },
        "manifest",
    )
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ManifestError(f"schema_version must be {SCHEMA_VERSION}")
    issue = raw.get("issue")
    sequence = raw.get("sequence")
    kind = raw.get("kind")
    title = raw.get("title")
    if not isinstance(issue, int) or issue <= 0:
        raise ManifestError("issue must be a positive integer")
    if not isinstance(sequence, int) or sequence <= 0:
        raise ManifestError("sequence must be a positive integer")
    if kind not in KINDS:
        raise ManifestError(f"kind must be one of {sorted(KINDS)}")
    if not isinstance(title, str) or not title.strip():
        raise ManifestError("title must be a non-empty string")
    raw_stages = raw.get("stages")
    if not isinstance(raw_stages, list) or not raw_stages:
        raise ManifestError("stages must be a non-empty array")

    stages: list[Stage] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_stages):
        if not isinstance(item, dict):
            raise ManifestError(f"stage[{index}] must be an object")
        _require_keys(
            item,
            {"id", "name", "command", "cwd", "timeout_seconds"},
            f"stage[{index}]",
        )
        stage_id = item.get("id")
        name = item.get("name")
        command = item.get("command")
        cwd = item.get("cwd", ".")
        timeout = item.get("timeout_seconds", 900)
        if not isinstance(stage_id, str) or not _STAGE.fullmatch(stage_id):
            raise ManifestError(f"stage[{index}].id is invalid")
        if stage_id in seen:
            raise ManifestError(f"duplicate stage id: {stage_id}")
        seen.add(stage_id)
        if not isinstance(name, str) or not name.strip():
            raise ManifestError(f"stage[{index}].name must be non-empty")
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(value, str) or not value for value in command)
        ):
            raise ManifestError(
                f"stage[{index}].command must be a non-empty string array"
            )
        if not isinstance(cwd, str):
            raise ManifestError(f"stage[{index}].cwd must be a string")
        if cwd != ".":
            _relative_path(cwd, f"stage[{index}].cwd")
        if not isinstance(timeout, int) or not (1 <= timeout <= 7200):
            raise ManifestError(
                f"stage[{index}].timeout_seconds must be 1..7200"
            )
        stages.append(Stage(stage_id, name.strip(), tuple(command), cwd, timeout))

    if kind == "experiments":
        ids = [stage.stage_id for stage in stages]
        allowed = ["P0", "P1", "P2", "P3"]
        if ids != allowed[: len(ids)]:
            raise ManifestError(
                f"experiment stages must be a contiguous P0..Pn prefix; got {ids}"
            )

    raw_artifacts = raw.get("artifacts", [])
    if (
        not isinstance(raw_artifacts, list)
        or any(not isinstance(value, str) for value in raw_artifacts)
    ):
        raise ManifestError("artifacts must be a string array")
    artifacts = tuple(
        _relative_path(value, "artifact") for value in raw_artifacts
    )
    return WorkManifest(
        issue, kind, sequence, title.strip(), tuple(stages), artifacts
    )


def validate_dispatch(
    manifest: WorkManifest, *, kind: str, issue: int, sequence: int
) -> None:
    expected_kind = "experiments" if kind == "experiments" else "refactor"
    if (
        manifest.kind != expected_kind
        or manifest.issue != issue
        or manifest.sequence != sequence
    ):
        raise ManifestError(
            f"dispatch identity mismatch: manifest={manifest.identity} "
            f"dispatch=Issue_{issue}_{expected_kind}{sequence:02d}"
        )
