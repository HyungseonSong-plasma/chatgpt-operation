"""Typed, evidence-gated blocker lifecycle; no mutation or permission grants.

Verification callbacks must be provided by trusted readback/authority adapters.
Untrusted Issue text, model output, or a self-attested bool is NOT evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Callable

from .blocker_triage import BlockerObservation, BlockerSource

_SHA40 = re.compile(r"^[0-9a-f]{40}$")


class BlockerState(str, Enum):
    ACTIVE = "ACTIVE"
    RESOLVED_AUTOMATICALLY = "RESOLVED_AUTOMATICALLY"
    RESOLVED_BY_AUTHORITY = "RESOLVED_BY_AUTHORITY"
    SUPERSEDED = "SUPERSEDED"
    ESCALATED = "ESCALATED"


class ClearanceKind(str, Enum):
    SHA_REPLANNED = "SHA_REPLANNED"
    EXACT_HEAD_CI_PASS = "EXACT_HEAD_CI_PASS"
    WORKFLOW_PROVENANCE_PASS = "WORKFLOW_PROVENANCE_PASS"
    CURRENT_HEAD_REVIEW = "CURRENT_HEAD_REVIEW"
    TARGET_ACCESS_RESTORED = "TARGET_ACCESS_RESTORED"
    TRANSIENT_RECOVERED = "TRANSIENT_RECOVERED"
    OWNER_POLICY_AUTHORIZED = "OWNER_POLICY_AUTHORIZED"
    UPSTREAM_SAFETY_CLEARED = "UPSTREAM_SAFETY_CLEARED"


@dataclass(frozen=True)
class ClearanceEvidence:
    logical_intent_id: str
    blocker_evidence_ref: str
    kind: ClearanceKind
    verified_head_sha: str
    evidence_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ClearanceKind):
            raise ValueError("unsupported clearance kind")
        if not isinstance(self.logical_intent_id, str) or not re.fullmatch(r"[0-9a-f]{64}", self.logical_intent_id):
            raise ValueError("missing stable logical intent identity")
        if not isinstance(self.verified_head_sha, str) or not _SHA40.fullmatch(self.verified_head_sha):
            raise ValueError("clearance must bind exact head")
        if any(not isinstance(v, str) or not v.strip()
               for v in (self.blocker_evidence_ref, self.evidence_ref)):
            raise ValueError("clearance and blocker evidence references required")
        if self.blocker_evidence_ref == self.evidence_ref:
            raise ValueError("new clearance evidence must differ from blocker record")


@dataclass(frozen=True)
class ResolutionDecision:
    state: BlockerState
    reason: str
    blocker_evidence_ref: str
    clearance_evidence_ref: str | None
    # A resolution NEVER authorizes a GitHub write. All ordinary gates remain.
    write_authorized: bool = False


Verifier = Callable[[ClearanceEvidence], bool]


def _eligible_kind(blocker: BlockerObservation) -> ClearanceKind | None:
    source = blocker.source
    if source is BlockerSource.TOOL_SAFETY:
        return ClearanceKind.UPSTREAM_SAFETY_CLEARED
    if source is BlockerSource.REPOSITORY_POLICY:
        return ClearanceKind.OWNER_POLICY_AUTHORIZED
    if source is BlockerSource.STALE_IDENTITY:
        return ClearanceKind.SHA_REPLANNED
    if source is BlockerSource.WORKFLOW_GOVERNANCE:
        return ClearanceKind.WORKFLOW_PROVENANCE_PASS
    if source is BlockerSource.CI:
        return ClearanceKind.EXACT_HEAD_CI_PASS
    if source is BlockerSource.REVIEW:
        return ClearanceKind.CURRENT_HEAD_REVIEW
    if source is BlockerSource.GITHUB_HTTP:
        status = blocker.http_status
        if status in (401, 403, 404):
            return ClearanceKind.TARGET_ACCESS_RESTORED
        if status in (409, 412, 422):
            return ClearanceKind.SHA_REPLANNED
        if status in (429, 500, 502, 503, 504):
            return ClearanceKind.TRANSIENT_RECOVERED
    return None


def evaluate_clearance(
    blocker: BlockerObservation,
    evidence: ClearanceEvidence | None,
    *,
    expected_head_sha: str,
    verify_technical: Verifier | None = None,
    verify_authority: Verifier | None = None,
) -> ResolutionDecision:
    """Evaluate eligibility of new evidence without clearing the original event.

    A trusted caller supplies exact live HEAD and *independent* verification
    callbacks. The helper cannot attest a GitHub run or policy itself. Tool
    safety and repository-policy denials only accept a verified clearance from
    the corresponding responsible authority. No review of technical blocker
    release is required in addition to the existing normal PR review.
    """
    if not isinstance(expected_head_sha, str) or not _SHA40.fullmatch(expected_head_sha):
        raise ValueError("independently observed current head SHA required")
    if not isinstance(blocker, BlockerObservation):
        raise ValueError("real blocker observation required")
    kind = _eligible_kind(blocker)
    exceptional = blocker.source in (BlockerSource.TOOL_SAFETY, BlockerSource.REPOSITORY_POLICY)
    def reject(reason: str) -> ResolutionDecision:
        return ResolutionDecision(
            BlockerState.ESCALATED if exceptional or kind is None else BlockerState.ACTIVE,
            reason, blocker.evidence_ref, None,
        )
    if kind is None:
        return reject("UNKNOWN_OR_UNSUPPORTED_BLOCKER_CANNOT_AUTO_CLEAR")
    if evidence is None:
        return reject("NO_NEW_RESOLUTION_EVIDENCE")
    if not isinstance(evidence, ClearanceEvidence):
        raise ValueError("typed clearance evidence required")
    if (evidence.logical_intent_id != blocker.logical_intent_id
        or evidence.blocker_evidence_ref != blocker.evidence_ref
        or evidence.kind is not kind
        or evidence.verified_head_sha != expected_head_sha):
        return reject("EVIDENCE_SCOPE_KIND_OR_HEAD_MISMATCH")
    verifier = verify_authority if exceptional else verify_technical
    if verifier is None:
        return reject("TRUSTED_VERIFIER_UNAVAILABLE")
    # A thrown/false/non-boolean verifier result fails closed.
    try:
        verified = verifier(evidence)
    except Exception:
        verified = False
    if verified is not True:
        return reject("CLEARANCE_NOT_INDEPENDENTLY_VERIFIED")
    state = (BlockerState.RESOLVED_BY_AUTHORITY if exceptional
             else BlockerState.RESOLVED_AUTOMATICALLY)
    return ResolutionDecision(state, "EVIDENCE_VERIFIED_NOT_WRITE_AUTHORIZATION",
                              blocker.evidence_ref, evidence.evidence_ref)
