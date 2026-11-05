"""Fail-closed checks for caller-supplied, immutable source inventories.

This module does not fetch or discover repository files by itself.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Iterable


class RefinementError(ValueError):
    """A source, content or preservation gate failed."""


def repository_path(value: str) -> str:
    """Validate a repository-relative, normalized POSIX path."""
    if not isinstance(value, str) or not value or "\\" in value:
        raise RefinementError("repository path must be a nonempty POSIX path")
    if value.startswith("/") or any(ch in value for ch in "\r\n\0"):
        raise RefinementError("repository path must be relative and single-line")
    path = PurePosixPath(value)
    if (
        value != str(path)
        or str(path) == "."
        or any(part in {".", ".."} for part in value.split("/"))
    ):
        raise RefinementError(f"unsafe or noncanonical repository path: {value!r}")
    return value


def discover_source_inventory(
    snapshot_sha: str, paths: Iterable[str], *, inventory_complete: bool
) -> frozenset[str]:
    """Validate an attested path inventory for one exact source commit.

    A caller's complete=True assertion is not independently verified here.
    """
    if not isinstance(snapshot_sha, str) or not re.fullmatch(
        r"[0-9a-f]{40}", snapshot_sha
    ):
        raise RefinementError("snapshot_sha must be an exact 40-hex commit")
    if inventory_complete is not True:
        raise RefinementError("source inventory is not attested complete")
    if isinstance(paths, (str, bytes)) or paths is None:
        raise RefinementError("source_inventory must be a nonempty path collection")
    try:
        items = [repository_path(item) for item in paths]
    except TypeError as exc:
        raise RefinementError("source_inventory must be iterable") from exc
    if not items or len(items) != len(set(items)):
        raise RefinementError("source_inventory is empty or contains duplicates")
    return frozenset(items)
