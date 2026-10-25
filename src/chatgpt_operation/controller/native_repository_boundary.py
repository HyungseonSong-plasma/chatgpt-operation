"""Authenticated workflow repository boundary for native GitHub execution.

Cross-repository execution remains disabled until a trusted authorization
source and actual target-identity checks are wired to target preflight.
Never derive execution authorization from the ActionPlan or Issue text.
"""
from __future__ import annotations
from .cross_repository_policy import TargetRequest, validate_target_request


class NativeRepositoryBoundaryError(ValueError):
    pass


def require_native_repository_scope(repository: str, workflow_repository: str | None) -> None:
    if not isinstance(workflow_repository, str) or not workflow_repository.strip():
        raise NativeRepositoryBoundaryError("trusted workflow repository identity is required")
    if repository == workflow_repository:
        return
    # Explicitly enter the new cross-repo validator. There is currently no
    # independently verified grant or live target policy; fail closed even
    # when the requested repository is present in an untrusted plan.
    provisional = TargetRequest(
        repository=repository, repository_id=0, base_branch="", head_branch="",
        base_sha="", paths=(), workflows=(), operations=(),
    )
    decision = validate_target_request(provisional, {}, authorization_verified=False)
    raise NativeRepositoryBoundaryError(
        "cross-repository native execution is not authorized: "
        + ",".join(decision.reasons)
    )
