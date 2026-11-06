"""One-shot operator-to-ChatGPT delegation gate for DEA #254 (ordinary work).

A chat statement is intent, never a signed GitHub authorization. The trusted
external host must authenticate the human operator, verify a current
non-revoked grant from an independent authority, and atomically reserve it.
This gate cannot grant workflow-policy clearance, PR review, protected
Environment approval, merge, or human-only emergency privileges.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Callable

from .dea_workflow_authoring_preflight import BRANCH, PATH, REPO, WORK_ID

OPERATOR_LOGIN = "HyungseonSong-plasma"
DELEGATE_ID = "chatgpt-protected-dea-tool"
ACTION = "CREATE_REVIEW_ONLY_PRODUCER_DRAFT"
MAX_DURATION = timedelta(hours=24)
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
GRANT_ID = re.compile(r"[A-Za-z0-9._:-]{8,128}\Z")


class OperatorDelegationError(RuntimeError):
    pass


@dataclass(frozen=True)
class OperatorDelegationGrant:
    """Typed claims whose authenticity must be checked outside model control."""

    grant_id: str
    operator_login: str
    delegate_id: str
    repository: str
    work_id: str
    action: str
    branch: str
    target_path: str
    expected_main_sha: str
    issued_at: datetime
    expires_at: datetime
    evidence_ref: str


class OperatorDelegationGate:
    """Accept only a fresh, externally verified and atomically reserved grant.

    The three callbacks must belong to a trusted host, never an ActionPlan,
    model-supplied parameter, editable issue comment, or untrusted PR branch.
    The reservation must be an atomic one-use operation with a durable,
    separately governed ledger; after uncertain side effects, fail closed.
    """

    def __init__(
        self, *,
        trusted_grant_reader: Callable[[], OperatorDelegationGrant],
        trusted_grant_verifier: Callable[[OperatorDelegationGrant], bool],
        atomic_grant_reserver: Callable[[OperatorDelegationGrant], bool],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if any(not callable(x) for x in (
            trusted_grant_reader, trusted_grant_verifier, atomic_grant_reserver,
        )):
            raise OperatorDelegationError("TRUSTED_DELEGATION_BOUNDARY_REQUIRED")
        self._read = trusted_grant_reader
        self._verify = trusted_grant_verifier
        self._reserve = atomic_grant_reserver
        self._clock = clock if clock is not None else (
            lambda: datetime.now(timezone.utc)
        )
        if not callable(self._clock):
            raise OperatorDelegationError("TRUSTED_CLOCK_REQUIRED")

    def require_and_reserve(self, *, expected_main_sha: str) -> OperatorDelegationGrant:
        """Check the exact ordinary draft scope, then consume the one-use grant.

        This is a necessary condition, not a replacement for GitHub policy,
        CommonPreWriteGate, protected review, or operator-only actions.
        """
        if not isinstance(expected_main_sha, str) or not SHA40.fullmatch(expected_main_sha):
            raise OperatorDelegationError("EXPECTED_MAIN_SHA_INVALID")
        try:
            grant = self._read()
        except Exception as exc:
            raise OperatorDelegationError("DELEGATION_READ_UNAVAILABLE") from exc
        if not isinstance(grant, OperatorDelegationGrant):
            raise OperatorDelegationError("TYPED_DELEGATION_REQUIRED")
        if not isinstance(grant.grant_id, str) or not GRANT_ID.fullmatch(grant.grant_id):
            raise OperatorDelegationError("DELEGATION_ID_INVALID")
        if (
            grant.operator_login != OPERATOR_LOGIN
            or grant.delegate_id != DELEGATE_ID
            or grant.repository != REPO
            or grant.work_id != WORK_ID
            or grant.action != ACTION
            or grant.branch != BRANCH
            or grant.target_path != PATH
            or grant.expected_main_sha != expected_main_sha
        ):
            raise OperatorDelegationError("DELEGATION_SCOPE_MISMATCH")
        if not isinstance(grant.evidence_ref, str) or not grant.evidence_ref.strip():
            raise OperatorDelegationError("DELEGATION_EVIDENCE_MISSING")
        if (
            not isinstance(grant.issued_at, datetime)
            or not isinstance(grant.expires_at, datetime)
            or grant.issued_at.tzinfo is None
            or grant.expires_at.tzinfo is None
            or grant.issued_at.utcoffset() is None
            or grant.expires_at.utcoffset() is None
        ):
            raise OperatorDelegationError("DELEGATION_TIME_INVALID")
        try:
            now = self._clock()
        except Exception as exc:
            raise OperatorDelegationError("DELEGATION_CLOCK_UNAVAILABLE") from exc
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise OperatorDelegationError("DELEGATION_CLOCK_INVALID")
        if not (
            grant.issued_at <= now < grant.expires_at
            and timedelta(0) < grant.expires_at - grant.issued_at <= MAX_DURATION
        ):
            raise OperatorDelegationError("DELEGATION_EXPIRED_OR_OUT_OF_BOUNDS")
        try:
            verified = self._verify(grant)
        except Exception as exc:
            raise OperatorDelegationError("DELEGATION_VERIFIER_UNAVAILABLE") from exc
        if verified is not True:
            raise OperatorDelegationError("DELEGATION_NOT_AUTHENTIC_OR_REVOKED")
        try:
            reserved = self._reserve(grant)
        except Exception as exc:
            raise OperatorDelegationError("DELEGATION_RESERVATION_UNAVAILABLE") from exc
        if reserved is not True:
            raise OperatorDelegationError("DELEGATION_ALREADY_USED_OR_NOT_RESERVED")
        return grant
