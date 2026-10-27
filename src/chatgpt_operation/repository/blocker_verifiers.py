"""Read-only GitHub-backed technical clearance validators for Samuel blockers.

A read-only GitHub verification result is not permission to mutate. Unsupported
kinds fail closed instead of trusting the clearance event's own string claims.
"""
from __future__ import annotations

import re
from typing import Any, Protocol
from urllib.parse import quote

from .blocker_resolution import ClearanceEvidence, ClearanceKind


class GitHubReadTransport(Protocol):
    def get(self, path: str, *, query: dict[str, str] | None = None) -> Any: ...


class TrustedGitHubReadbacks:
    """Inject from trusted runtime configuration, never from an ActionPlan.

    Restrict verification to the configured repository and branch, and refuse
    ambiguous access, missing required keys, or unsupported evidence kinds.
    """

    def __init__(self, transport: GitHubReadTransport, *,
                 repository: str, branch: str):
        if not isinstance(repository, str) or not re.fullmatch(
            r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository
        ):
            raise ValueError("trusted repository required")
        if (not isinstance(branch, str) or not branch.strip()
                or branch.startswith("/") or ".." in branch
                or "//" in branch or branch.endswith("/")):
            raise ValueError("normalized trusted branch required")
        self.transport = transport
        self.repository = repository
        self.branch = branch

    def read_head(self) -> str:
        data = self.transport.get(
            "/git/ref/heads/" + quote(self.branch, safe="/")
        )
        if (not isinstance(data, dict)
                or data.get("ref") != "refs/heads/" + self.branch
                or not isinstance(data.get("object"), dict)):
            raise ValueError("GitHub exact head ref unreadable")
        sha = data["object"].get("sha")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("GitHub exact ref SHA malformed")
        return sha

    def verify_technical(self, proof: ClearanceEvidence) -> bool:
        if not isinstance(proof, ClearanceEvidence):
            return False
        try:
            head = self.read_head()
            if head != proof.verified_head_sha:
                return False
            if proof.kind is ClearanceKind.SHA_REPLANNED:
                return proof.evidence_ref == "github-head:" + self.branch + "@" + head
            if proof.kind is ClearanceKind.TRANSIENT_RECOVERED:
                # This establishes only that the exact target head is readable
                # again. Normal write preconditions still apply.
                return proof.evidence_ref == "github-head:" + self.branch + "@" + head
            if proof.kind is ClearanceKind.EXACT_HEAD_CI_PASS:
                m = re.fullmatch(r"github-actions-run:([1-9][0-9]{0,18})",
                                 proof.evidence_ref)
                if m is None:
                    return False
                result = self.transport.get("/actions/runs/" + m.group(1))
                return (
                    isinstance(result, dict)
                    and result.get("id") == int(m.group(1))
                    and result.get("status") == "completed"
                    and result.get("conclusion") == "success"
                    and result.get("head_sha") == head
                    and isinstance(result.get("repository"), dict)
                    and result["repository"].get("full_name") == self.repository
                )
            # The following require separate specialized trusted adapters:
            # - workflow catalog/provenance full census and blob check
            # - PR review freshness / independent reasoning provenance
            # - full target write-scope permission (not mere GET/200)
            # Do NOT accept these from self-attested Issue text.
            return False
        except Exception:
            return False

    @staticmethod
    def verify_authority(_proof: ClearanceEvidence) -> bool:
        # No generic GitHub account or comment can clear a platform-tool
        # safety refusal. Authority-specific adapters must be explicit.
        return False
