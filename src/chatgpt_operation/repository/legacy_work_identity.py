"""Read-only recovery of legacy work identity; never mutation authorization.

A trusted runtime owns the evidence reader and must authenticate the original
work scope and coverage across historical identities, branches and providers.
This module does not establish trust in a GitHub comment or a caller's claim.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Callable

_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class RecoveryStatus(str, Enum):
    IDENTITY_UNVERIFIED = "IDENTITY_UNVERIFIED"
    HISTORY_INCOMPLETE = "HISTORY_INCOMPLETE"
    BLOCKER_PRESENT = "BLOCKER_PRESENT"
    HISTORY_VERIFIED = "HISTORY_VERIFIED"


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _positive(value: object) -> bool:
    return type(value) is int and value > 0


@dataclass(frozen=True)
class LegacyWorkScope:
    repository: str
    repository_id: int
    issue_id: int
    # A trusted, stable bounded-work anchor, NOT the current branch or PR.
    # It must distinguish independent work packages under one Issue.
    work_anchor: str

    def __post_init__(self) -> None:
        if not isinstance(self.repository, str) or not _REPO.fullmatch(self.repository):
            raise ValueError("invalid repository")
        if not _positive(self.repository_id) or not _positive(self.issue_id):
            raise ValueError("immutable GitHub identities required")
        if not _nonblank(self.work_anchor):
            raise ValueError("trusted bounded-work anchor required")

    def legacy_work_id(self) -> str:
        """Proposed stable ID, usable only after independent verification."""
        body = ["samuel.legacy-work.v1", self.repository_id, self.issue_id, self.work_anchor]
        return "legacy-v1:" + hashlib.sha256(json.dumps(body, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


@dataclass(frozen=True)
class RecoveryRequest:
    scope: LegacyWorkScope
    target_head: str

    def __post_init__(self) -> None:
        if not isinstance(self.scope, LegacyWorkScope) or not isinstance(self.target_head, str) or not _SHA.fullmatch(self.target_head):
            raise ValueError("exact work scope and current head required")


@dataclass(frozen=True)
class HistoricalRecord:
    # Preserve the original source reference and identity verbatim. A source
    # without an old ID remains associated by the trusted history reader.
    evidence_ref: str
    original_intent_id: str | None
    source: str

    def __post_init__(self) -> None:
        if not _nonblank(self.evidence_ref) or not _nonblank(self.source):
            raise ValueError("historical blocker evidence required")
        if self.original_intent_id is not None and (not isinstance(self.original_intent_id, str) or not _DIGEST.fullmatch(self.original_intent_id)):
            raise ValueError("invalid original intent")


@dataclass(frozen=True)
class HistoryEvidence:
    request: RecoveryRequest
    scope_ref: str
    source_ref: str
    coverage_ref: str | None
    # Canonical original ID if recovered; aliases remain in scope forever.
    original_work_id: str | None
    historical_work_ids: tuple[str, ...]
    blockers: tuple[HistoricalRecord, ...]
    # True ONLY if trusted source establishes that no original ID was issued.
    no_original_id_issued: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.request, RecoveryRequest) or not _nonblank(self.scope_ref) or not _nonblank(self.source_ref):
            raise ValueError("bound evidence required")
        if self.coverage_ref is not None and not _nonblank(self.coverage_ref):
            raise ValueError("invalid coverage reference")
        if type(self.no_original_id_issued) is not bool:
            raise ValueError("strict no-original-ID assertion required")
        if self.original_work_id is not None and not _nonblank(self.original_work_id):
            raise ValueError("invalid original work ID")
        if not isinstance(self.historical_work_ids, tuple) or any(not _nonblank(x) for x in self.historical_work_ids) or len(set(self.historical_work_ids)) != len(self.historical_work_ids):
            raise ValueError("invalid historical aliases")
        if self.original_work_id is not None and self.original_work_id not in self.historical_work_ids:
            raise ValueError("original ID missing from history scope")
        if self.no_original_id_issued and (self.original_work_id is not None or self.historical_work_ids):
            raise ValueError("contradictory identity evidence")
        if not isinstance(self.blockers, tuple) or any(not isinstance(x, HistoricalRecord) for x in self.blockers):
            raise ValueError("invalid historical blockers")
        if len({x.evidence_ref for x in self.blockers}) != len(self.blockers):
            raise ValueError("ambiguous historical blocker records")


@dataclass(frozen=True)
class RecoveryResult:
    status: RecoveryStatus
    work_id: str | None = None
    historical_work_ids: tuple[str, ...] = ()
    blockers: tuple[HistoricalRecord, ...] = ()
    reason: str = ""

    @property
    def mutation_authorized(self) -> bool:
        return False


TrustedReader = Callable[[RecoveryRequest], HistoryEvidence]
TrustedVerifier = Callable[[HistoryEvidence], bool]


def recover_work_identity(request: RecoveryRequest, *, trusted_reader: TrustedReader,
                          verify_scope: TrustedVerifier,
                          verify_coverage: TrustedVerifier) -> RecoveryResult:
    """Observe verified historical scope; preserve known blockers even if incomplete.

    The reader/verifiers are runtime-injected trusted adapters, not user/model
    data. Coverage must include prior work identities and original denial
    sources, not merely currently visible PR comments. A missing original ID
    is not proof that none was ever issued. No verdict clears any blocker.
    """
    try:
        evidence = trusted_reader(request)
        if not isinstance(evidence, HistoryEvidence) or evidence.request != request or verify_scope(evidence) is not True:
            raise ValueError("scope verification failed")
    except Exception:
        return RecoveryResult(RecoveryStatus.IDENTITY_UNVERIFIED, reason="trusted scope unavailable")
    # Known blocker dominates even missing identity or incomplete coverage.
    if evidence.blockers:
        return RecoveryResult(RecoveryStatus.BLOCKER_PRESENT, evidence.original_work_id,
                              evidence.historical_work_ids, evidence.blockers,
                              "preserve original records; existing clearance contract applies")
    try:
        complete = evidence.coverage_ref is not None and verify_coverage(evidence) is True
    except Exception:
        complete = False
    if not complete:
        return RecoveryResult(RecoveryStatus.HISTORY_INCOMPLETE, evidence.original_work_id,
                              evidence.historical_work_ids, reason="historical coverage not verified")
    work_id = evidence.original_work_id
    if work_id is None:
        if not evidence.no_original_id_issued:
            return RecoveryResult(RecoveryStatus.IDENTITY_UNVERIFIED, reason="original identity unresolved")
        work_id = request.scope.legacy_work_id()
    return RecoveryResult(RecoveryStatus.HISTORY_VERIFIED, work_id,
                          evidence.historical_work_ids,
                          reason="history verified; ordinary mutation gates still required")
