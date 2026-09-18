"""Manifest skeleton generator for governed work."""
from __future__ import annotations

import json
from pathlib import Path
import re


def create_manifest(
    *,
    issue: int,
    kind: str,
    title: str,
    root: str | Path = "automation/manifests",
) -> Path:
    if issue <= 0:
        raise ValueError("issue must be positive")
    if kind not in {"experiments", "refactor"}:
        raise ValueError("kind must be experiments or refactor")
    if not title.strip():
        raise ValueError("title must be non-empty")

    base = Path(root)
    folder = base / ("experiments" if kind == "experiments" else "refactors")
    folder.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(rf"^Issue_{issue}_{re.escape(kind)}(\d+)\.json$")
    used = [
        int(match.group(1))
        for path in folder.glob(f"Issue_{issue}_{kind}*.json")
        if (match := pattern.match(path.name))
    ]
    sequence = max(used, default=0) + 1
    identity = f"Issue_{issue}_{kind}{sequence:02d}"

    if kind == "experiments":
        stages = [
            {
                "id": "P0",
                "name": "configure P0",
                "command": [
                    "python3",
                    "-c",
                    "raise SystemExit('TODO: configure P0')",
                ],
            }
        ]
    else:
        stages = [
            {
                "id": "VALIDATE",
                "name": "configure refactor validation",
                "command": [
                    "python3",
                    "-c",
                    "raise SystemExit('TODO: configure refactor')",
                ],
            }
        ]

    payload = {
        "schema_version": 1,
        "issue": issue,
        "kind": kind,
        "sequence": sequence,
        "title": title,
        "stages": stages,
        "artifacts": [],
    }
    path = folder / f"{identity}.json"
    path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
