"""Fail-closed source Issue write scope for non-Bootstrap Samuel workers.

The codeQA foreign-cycle and proposal-ingress workflows require issues:write
for source review Issue #220. This guard confines their shared API to that
review ledger and refuses writes targeting Issue #44, including comment-ID
PATCH operations whose Issue number is absent from the URL.

This is NOT token-level authorization. External calls that bypass this module
remain possible until credential isolation is deployed.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

SOURCE = "HyungseonSong-plasma/chatgpt-operation"
REVIEW_ISSUE = 220
_ISSUE_PREFIX = f"/repos/{SOURCE}/issues/"
_COMMENT_RE = re.compile(re.escape(_ISSUE_PREFIX) + r"comments/([1-9][0-9]*)\Z")
_REVIEW_POST = f"{_ISSUE_PREFIX}{REVIEW_ISSUE}/comments"
_REVIEW_URL = f"https://api.github.com/repos/{SOURCE}/issues/{REVIEW_ISSUE}"
_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})


class ScopedIssueWriteError(ValueError):
    pass


def require_source_review_ledger_write(
    method: str, path: str, *, current_comment: Mapping[str, Any] | None = None,
) -> None:
    """Allow only source Issue #220 comment POST or attested comment PATCH.

    Callers MUST independently GET the exact comment before a PATCH.
    """
    if not isinstance(method, str) or not isinstance(path, str):
        raise ScopedIssueWriteError("invalid GitHub write endpoint")
    if method.upper() not in _METHODS or not path.startswith(_ISSUE_PREFIX):
        return
    if method == "POST" and path == _REVIEW_POST:
        return
    match = _COMMENT_RE.fullmatch(path)
    if method == "PATCH" and match is not None:
        if (
            not isinstance(current_comment, Mapping)
            or current_comment.get("id") != int(match.group(1))
            or current_comment.get("issue_url") != _REVIEW_URL
        ):
            raise ScopedIssueWriteError(
                "source comment PATCH requires verified Issue #220 ownership"
            )
        return
    raise ScopedIssueWriteError(
        "non-Bootstrap source Issue mutation is limited to Issue #220 review comments"
    )


def needs_source_comment_ownership_lookup(method: str, path: str) -> bool:
    return (
        method == "PATCH"
        and isinstance(path, str)
        and _COMMENT_RE.fullmatch(path) is not None
    )
