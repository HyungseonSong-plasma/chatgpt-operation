"""Exact-SHA guarded GitHub branch deletion for Samuel."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


class BranchDeleteError(RuntimeError):
    pass


@dataclass(frozen=True)
class BranchDeleteResult:
    status: str
    branch: str
    expected_sha: str


def _request(
    repository: str,
    token: str,
    method: str,
    path: str,
    *,
    allow_not_found: bool = False,
) -> Any:
    url = f"https://api.github.com/repos/{repository}{path}"
    req = Request(url, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    try:
        with urlopen(req, timeout=30) as response:
            body = response.read()
    except HTTPError as exc:
        if exc.code == 404 and allow_not_found:
            return None
        raise BranchDeleteError(f"GitHub API {method} {path} -> {exc.code}") from exc
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def delete_branch(*, repository: str, token: str, branch: str, expected_sha: str) -> BranchDeleteResult:
    if branch == "main":
        raise BranchDeleteError("default branch deletion is denied")
    if len(expected_sha) != 40 or any(c not in "0123456789abcdef" for c in expected_sha):
        raise BranchDeleteError("expected_sha must be lowercase 40-hex")

    encoded = quote(branch, safe="/")
    get_path = "/git/ref/heads/" + encoded
    delete_path = "/git/refs/heads/" + encoded

    current = _request(repository, token, "GET", get_path, allow_not_found=True)
    if current is None:
        return BranchDeleteResult("NO_MUTATION_NEEDED", branch, expected_sha)
    actual = current.get("object", {}).get("sha")
    if actual != expected_sha:
        raise BranchDeleteError(f"stale branch identity: actual={actual} expected={expected_sha}")

    _request(repository, token, "DELETE", delete_path)
    if _request(repository, token, "GET", get_path, allow_not_found=True) is not None:
        raise BranchDeleteError("post-delete verification mismatch: branch still exists")
    return BranchDeleteResult("PASS", branch, expected_sha)
