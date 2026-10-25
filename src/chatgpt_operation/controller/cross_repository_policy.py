"""Non-executing, fail-closed cross-repository target preflight.

This module never grants credentials, dispatches actions, or verifies user
authorization. The caller must provide independently verified authorization
and a separately reviewed target policy before execution can be considered.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Any

_SHA = re.compile(r"^[0-9a-f]{40}$")
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_ALLOWED_OPERATIONS = frozenset({"branch.create", "file.create", "file.update", "pr.create", "ci.inspect"})
_FORBIDDEN_BRANCHES = frozenset({"main", "master"})


@dataclass(frozen=True)
class TargetRequest:
    repository: str
    repository_id: int
    base_branch: str
    head_branch: str
    base_sha: str
    paths: tuple[str, ...]
    workflows: tuple[str, ...]
    operations: tuple[str, ...]


@dataclass(frozen=True)
class TargetDecision:
    allowed: bool
    reasons: tuple[str, ...]


def validate_target_request(
    request: TargetRequest,
    policy: Mapping[str, Any],
    *,
    authorization_verified: bool = False,
) -> TargetDecision:
    """Check request constraints, without converting the result to execution permission.

    authorization_verified must originate from an independent trusted check,
    not a user-controlled Issue field. An allow decision is necessary but not
    sufficient for any subsequent GitHub mutation.
    """
    reasons: list[str] = []
    if authorization_verified is not True:
        reasons.append("independent_authorization_missing")
    if policy.get("schema_version") != 1 or policy.get("enabled") is not True:
        reasons.append("policy_not_enabled")
    if not isinstance(request.repository, str) or not _REPO.fullmatch(request.repository):
        reasons.append("invalid_repository")
    if request.repository != policy.get("repository"):
        reasons.append("repository_not_allowlisted")
    if type(request.repository_id) is not int or request.repository_id <= 0 or request.repository_id != policy.get("repository_id"):
        reasons.append("repository_id_mismatch")
    if not isinstance(request.base_branch, str) or not request.base_branch:
        reasons.append("invalid_base_branch")
    if request.base_branch != policy.get("base_branch"):
        reasons.append("base_branch_mismatch")
    if not isinstance(request.head_branch, str) or not request.head_branch or request.head_branch in _FORBIDDEN_BRANCHES:
        reasons.append("invalid_head_branch")
    if request.head_branch != policy.get("head_branch"):
        reasons.append("head_branch_mismatch")
    if not isinstance(request.base_sha, str) or not _SHA.fullmatch(request.base_sha):
        reasons.append("invalid_base_sha")
    if request.base_sha != policy.get("base_sha"):
        reasons.append("stale_or_unpinned_base_sha")

    def check_members(values: object, permitted: object, kind: str) -> None:
        if not isinstance(values, tuple) or not values or not all(isinstance(v, str) and v for v in values):
            reasons.append("invalid_" + kind)
            return
        if not isinstance(permitted, list) or not permitted or not all(isinstance(v, str) and v for v in permitted):
            reasons.append("missing_" + kind + "_allowlist")
            return
        if len(values) != len(set(values)) or any(v not in permitted for v in values):
            reasons.append("unauthorized_" + kind)

    check_members(request.workflows, policy.get("workflows"), "workflows")
    check_members(request.operations, policy.get("operations"), "operations")
    if any(op not in _ALLOWED_OPERATIONS for op in request.operations):
        reasons.append("unsafe_operation")
    prefixes = policy.get("path_prefixes")
    if not isinstance(request.paths, tuple) or not request.paths or not isinstance(prefixes, list) or not prefixes:
        reasons.append("missing_paths_or_prefixes")
    elif not all(isinstance(p, str) and p and
                 not p.startswith("/") and "\\" not in p and
                 all(segment not in (".", "..", "") for segment in p.split("/")) and
                 any(isinstance(prefix, str) and prefix.endswith("/") and
                     p.startswith(prefix) and prefix.count("/") > 0 for prefix in prefixes)
                 for p in request.paths):
        reasons.append("unauthorized_paths")
    if policy.get("merge_enabled") is not False:
        reasons.append("merge_boundary_not_disabled")
    return TargetDecision(not reasons, tuple(reasons))
