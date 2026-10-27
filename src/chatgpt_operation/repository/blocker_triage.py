"""Fail-closed repository mutation blocker classification (Samuel issue #236).

This module makes no GitHub calls and grants no mutation permissions. An
upstream safety denial is not a provider-local outage or a fallback signal.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
import re
from typing import Iterable

_SHA = re.compile(r"^[0-9a-f]{64}$")
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class BlockerSource(str, Enum):
    TOOL_SAFETY = "tool_safety"
    REPOSITORY_POLICY = "repository_policy"
    GITHUB_HTTP = "github_http"
    STALE_IDENTITY = "stale_identity"
    WORKFLOW_GOVERNANCE = "workflow_governance"
    CI = "ci"
    REVIEW = "review"
    PROVIDER_TRANSPORT = "provider_transport"
    UNKNOWN = "unknown"


class RecoveryAction(str, Enum):
    ESCALATE_NO_WRITE = "ESCALATE_NO_WRITE"
    READ_ONLY_REPLAN = "READ_ONLY_REPLAN"
    REPAIR_AND_REVALIDATE = "REPAIR_AND_REVALIDATE"
    RETRY_SAME_PROVIDER = "RETRY_SAME_PROVIDER"


@dataclass(frozen=True)
class BlockerObservation:
    source: BlockerSource
    logical_intent_id: str
    provider: str
    evidence_ref: str
    http_status: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, BlockerSource):
            raise ValueError("unknown blocker source: fail closed")
        if not isinstance(self.logical_intent_id, str) or not _SHA.fullmatch(self.logical_intent_id):
            raise ValueError("logical intent id must be a 64-hex digest")
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ValueError("provider identity missing")
        if not isinstance(self.evidence_ref, str) or not self.evidence_ref.strip():
            raise ValueError("durable blocker evidence reference missing")
        if self.source is BlockerSource.GITHUB_HTTP:
            if type(self.http_status) is not int or not 100 <= self.http_status <= 599:
                raise ValueError("GitHub HTTP blocker requires observed status")
        elif self.http_status is not None:
            raise ValueError("HTTP status is only valid for GitHub HTTP blocker")


@dataclass(frozen=True)
class BlockerVerdict:
    category: str
    action: RecoveryAction
    evidence_ref: str
    provider: str


def logical_intent_id(*, repository: str, branch: str, work_id: str,
                      paths: Iterable[str]) -> str:
    """Identity of desired effect, NOT of API, endpoint or execution provider.

    Operations that try to produce the same change through Contents API, Git
    Trees, git push or Actions must keep the same work_id/scope identity.
    A different tool cannot clear a recorded safety denial.
    """
    if not isinstance(repository, str) or not _REPO.fullmatch(repository):
        raise ValueError("invalid repository")
    if not isinstance(branch, str) or not branch.strip() or branch in {"main", "master"}:
        raise ValueError("missing, default or invalid target branch")
    if not isinstance(work_id, str) or not work_id.strip():
        raise ValueError("missing durable work identity")
    if isinstance(paths, str):
        raise ValueError("paths must be a collection")
    p = tuple(paths)
    if not p or any(not isinstance(x, str) or not x or x.startswith("/")
                    or "\\" in x or any(y in {"", ".", ".."} for y in x.split("/"))
                    for x in p) or len(set(p)) != len(p):
        raise ValueError("empty, duplicate or non-normalized path scope")
    payload = {"repository": repository, "branch": branch,
               "work_id": work_id, "paths": sorted(p)}
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def classify_blocker(observation: BlockerObservation) -> BlockerVerdict:
    """Use observed source, never infer a cause from prose such as 'blocked'."""
    source = observation.source
    category: str
    action: RecoveryAction
    if source is BlockerSource.TOOL_SAFETY:
        category, action = "EXTERNAL_SAFETY_DENIAL", RecoveryAction.ESCALATE_NO_WRITE
    elif source is BlockerSource.REPOSITORY_POLICY:
        category, action = "OWNER_POLICY_DENIAL", RecoveryAction.ESCALATE_NO_WRITE
    elif source is BlockerSource.GITHUB_HTTP:
        status = observation.http_status
        if status in {401, 403, 404}:
            # 403 may be ruleset, token scope or resource policy; 404 may
            # deliberately hide inaccessible resources. Do not overdiagnose.
            category, action = "ACCESS_OR_RESOURCE_UNDETERMINED", RecoveryAction.ESCALATE_NO_WRITE
        elif status in {409, 412, 422}:
            category, action = "IDENTITY_OR_VALIDATION_CONFLICT", RecoveryAction.READ_ONLY_REPLAN
        elif status in {429, 500, 502, 503, 504}:
            category, action = "TRANSIENT_PROVIDER_ERROR", RecoveryAction.RETRY_SAME_PROVIDER
        else:
            category, action = "UNCLASSIFIED_HTTP", RecoveryAction.ESCALATE_NO_WRITE
    elif source is BlockerSource.STALE_IDENTITY:
        category, action = "STALE_OR_DIVERGED_SHA", RecoveryAction.READ_ONLY_REPLAN
    elif source is BlockerSource.WORKFLOW_GOVERNANCE:
        category, action = "WORKFLOW_MANIFEST_DRIFT", RecoveryAction.REPAIR_AND_REVALIDATE
    elif source is BlockerSource.CI:
        category, action = "EXACT_HEAD_CI_NOT_SUCCESS", RecoveryAction.REPAIR_AND_REVALIDATE
    elif source is BlockerSource.REVIEW:
        category, action = "REVIEW_NOT_CURRENT", RecoveryAction.REPAIR_AND_REVALIDATE
    elif source is BlockerSource.PROVIDER_TRANSPORT:
        # Transport failures without an independently observed retryable
        # status might be ambiguous (including access revocation).
        category, action = "PROVIDER_FAILURE_UNDETERMINED", RecoveryAction.ESCALATE_NO_WRITE
    else:
        category, action = "UNKNOWN_BLOCKER", RecoveryAction.ESCALATE_NO_WRITE
    return BlockerVerdict(category, action, observation.evidence_ref, observation.provider)


def decide_mutation_continuation(history: Iterable[BlockerObservation], *,
                                 logical_intent_id: str, provider: str) -> BlockerVerdict:
    """Same-intent denial dominates later provider errors or endpoint changes.

    Called before any retry/fallback; this is a necessary guard, NOT permission
    to write. Even RETRY_SAME_PROVIDER still requires fresh normal preflight.
    """
    if not isinstance(logical_intent_id, str) or not _SHA.fullmatch(logical_intent_id):
        raise ValueError("invalid logical intent id")
    if not isinstance(provider, str) or not provider.strip():
        raise ValueError("missing candidate provider")
    seen = [x for x in history if x.logical_intent_id == logical_intent_id]
    if not seen:
        return BlockerVerdict("NO_BLOCKER_RECORD_NOT_AUTHORIZATION",
                              RecoveryAction.ESCALATE_NO_WRITE, "no-blocker-record", provider)
    classified = [(x, classify_blocker(x)) for x in seen]
    for x, verdict in classified:
        if x.source in {BlockerSource.TOOL_SAFETY, BlockerSource.REPOSITORY_POLICY}:
            return BlockerVerdict(verdict.category, RecoveryAction.ESCALATE_NO_WRITE,
                                  x.evidence_ref, x.provider)
    prior, verdict = classified[-1]
    if verdict.action is RecoveryAction.RETRY_SAME_PROVIDER and prior.provider != provider:
        return BlockerVerdict("ALTERNATE_PROVIDER_RETRY_NOT_AUTHORIZED",
                              RecoveryAction.ESCALATE_NO_WRITE, prior.evidence_ref, prior.provider)
    return verdict
