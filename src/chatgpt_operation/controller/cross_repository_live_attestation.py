"""Live read-only verification of a reviewed cross-repository target policy.

This is NOT permission to execute mutations. Never accept request/policy
identity from free-form Issue text or infer token rights from connector access.
The caller must supply a trusted target-scoped GitHub transport.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

from .cross_repository_policy import TargetRequest, validate_target_request


class TargetReadTransport(Protocol):
    def get(self, path: str) -> Any: ...


@dataclass(frozen=True)
class LiveTargetAttestation:
    ready: bool
    reasons: tuple[str, ...]
    observed_repository_id: int | None
    observed_base_sha: str | None


def attest_live_target(
    request: TargetRequest,
    policy: dict[str, Any],
    *,
    transport: TargetReadTransport,
    independent_authorization_verified: bool,
) -> LiveTargetAttestation:
    """Fail closed on missing target facts, stale refs, or denied credential.

    'ready' is only a precondition for separately approved mutation; even a
    successful readback does not prove PR write permission or ActionPlan origin.
    """
    decision = validate_target_request(
        request, policy, authorization_verified=independent_authorization_verified
    )
    reasons = list(decision.reasons)
    repo_id: int | None = None
    base_sha: str | None = None
    if reasons:
        return LiveTargetAttestation(False, tuple(reasons), None, None)

    path = "/repos/" + request.repository
    try:
        observed = transport.get(path)
        if not isinstance(observed, dict):
            raise ValueError("malformed repository response")
        observed_id = observed.get("id")
        repo_id = observed_id if type(observed_id) is int else None
        if repo_id != request.repository_id or observed.get("full_name") != request.repository:
            reasons.append("target_repository_identity_mismatch")
        if observed.get("default_branch") != request.base_branch:
            reasons.append("target_default_branch_mismatch")
        permissions = observed.get("permissions")
        if not isinstance(permissions, dict) or permissions.get("push") is not True:
            reasons.append("target_token_push_not_attested")
        # The exact base SHA must be independently read from target GitHub,
        # never taken from the proposed ActionPlan or policy alone.
        ref = transport.get(
            path + "/git/ref/heads/" + quote(request.base_branch, safe="")
        )
        if not isinstance(ref, dict) or ref.get("ref") != "refs/heads/" + request.base_branch:
            raise ValueError("malformed exact base ref")
        obj = ref.get("object")
        base_sha = obj.get("sha") if isinstance(obj, dict) else None
        if base_sha != request.base_sha:
            reasons.append("live_base_sha_mismatch")
        # Exact selected workflows must exist and be active; no count-only test.
        for name in request.workflows:
            if "/" in name or name.startswith("."):
                reasons.append("unsafe_workflow_identifier")
                continue
            wf = transport.get(path + "/actions/workflows/" + quote(name, safe=""))
            if not isinstance(wf, dict) or wf.get("path") != ".github/workflows/" + name or wf.get("state") != "active":
                reasons.append("workflow_not_active:" + name)
    except Exception:
        reasons.append("target_readback_failed")
    return LiveTargetAttestation(not reasons, tuple(reasons), repo_id, base_sha)
