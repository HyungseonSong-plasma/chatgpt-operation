"""Trusted source verification for developer/local execution."""
from __future__ import annotations
import re
import subprocess
from pathlib import Path

SHA40 = re.compile(r"^[0-9a-f]{40}$")

class SourceVerificationError(RuntimeError):
    pass

def canonical_github_repository(remote: str) -> str | None:
    remote = remote.strip()
    for prefix in ("https://github.com/","ssh://git@github.com/","git@github.com:"):
        if remote.startswith(prefix):
            tail = remote[len(prefix):]
            if tail.endswith(".git"):
                tail = tail[:-4]
            parts = tail.split("/")
            if len(parts) == 2 and all(parts):
                return f"{parts[0]}/{parts[1]}"
    return None

def verify_git_source(path: str, *, repository: str, expected_sha: str) -> None:
    if not SHA40.fullmatch(expected_sha):
        raise SourceVerificationError("expected_sha must be lowercase 40-hex")
    root = str(Path(path).resolve())
    try:
        remote = subprocess.check_output(
            ["git","-C",root,"remote","get-url","origin"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
        head = subprocess.check_output(
            ["git","-C",root,"rev-parse","HEAD"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SourceVerificationError("cannot inspect Git source") from exc
    if canonical_github_repository(remote) != repository:
        raise SourceVerificationError("unexpected source repository")
    if head != expected_sha:
        raise SourceVerificationError(
            f"unexpected source commit: actual={head} expected={expected_sha}"
        )
