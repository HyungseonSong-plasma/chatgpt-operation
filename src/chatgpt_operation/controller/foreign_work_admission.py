"""Repository-neutral, read-only admission observation for existing work.

The composition root supplies authenticated transports and a configured scope.
This module is not an issuer, does not persist a new identity and cannot
authorize dispatch, a write, a merge or blocker clearance. The existing
codeQA-specific governed-write admission remains a separate policy boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Callable, Protocol
from urllib.parse import quote

from ..repository.legacy_work_identity import (
    HistoryEvidence, LegacyWorkScope, RecoveryRequest, RecoveryResult,
    RecoveryStatus, TrustedReader, TrustedVerifier, recover_work_identity,
)

_SHA = re.compile(r"[0-9a-f]{40}\Z")


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


class ReadTransport(Protocol):
    def get(self, path: str) -> Any: ...


@dataclass(frozen=True)
class ForeignAdmissionBinding:
    """Trusted runtime configuration, never constructed from an ActionPlan."""
    scope: LegacyWorkScope
    issue_number: int
    target_branch: str
    central_revision: str
    issuer_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.scope, LegacyWorkScope):
            raise ValueError("verified bounded-work scope required")
        if type(self.issue_number) is not int or self.issue_number <= 0:
            raise ValueError("positive issue number required")
        branch = self.target_branch
        if (not _text(branch) or branch.startswith(("/", "-"))
                or branch.endswith(("/", ".")) or ".." in branch
                or "@{" in branch or branch == "@"
                or re.search(r"[\x00-\x20\x7f~^:?*\[\\]", branch)
                or any(not part or part.startswith(".") or part.endswith(".lock")
                       for part in branch.split("/"))):
            raise ValueError("invalid exact target branch")
        if not isinstance(self.central_revision, str) or not _SHA.fullmatch(self.central_revision):
            raise ValueError("exact central revision required")
        if not _text(self.issuer_id):
            raise ValueError("trusted issuer identity required")


@dataclass(frozen=True)
class EnrollmentRecord:
    """Previously persisted record, returned by a trusted central reader.

    This type is not proof of authenticity. The independent verifier must
    validate the configured issuer and actual durable enrollment evidence.
    """
    scope: LegacyWorkScope
    work_id: str
    historical_work_ids: tuple[str, ...]
    issuer_id: str
    evidence_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.scope, LegacyWorkScope):
            raise ValueError("bound enrollment scope required")
        if not all(_text(x) for x in (self.work_id, self.issuer_id, self.evidence_ref)):
            raise ValueError("complete enrollment record required")
        aliases = self.historical_work_ids
        if (not isinstance(aliases, tuple) or not all(_text(x) for x in aliases)
                or len(set(aliases)) != len(aliases) or self.work_id not in aliases):
            raise ValueError("canonical identity and all historical aliases required")


class AdmissionStatus(str, Enum):
    TARGET_UNVERIFIED = "TARGET_UNVERIFIED"
    IDENTITY_UNVERIFIED = "IDENTITY_UNVERIFIED"
    HISTORY_INCOMPLETE = "HISTORY_INCOMPLETE"
    BLOCKER_PRESENT = "BLOCKER_PRESENT"
    ENROLLMENT_NOT_ATTESTED = "ENROLLMENT_NOT_ATTESTED"
    EXISTING_ENROLLMENT_OBSERVED = "EXISTING_ENROLLMENT_OBSERVED"


@dataclass(frozen=True)
class ForeignAdmissionObservation:
    status: AdmissionStatus
    request: RecoveryRequest
    recovery: RecoveryResult | None = None
    enrollment: EnrollmentRecord | None = None
    reason: str = ""

    @property
    def work_id(self) -> str | None:
        # Never expose an unregistered legacy candidate as an admitted identity.
        return self.enrollment.work_id if (
            self.status is AdmissionStatus.EXISTING_ENROLLMENT_OBSERVED
            and self.enrollment is not None) else None

    @property
    def mutation_authorized(self) -> bool:
        return False

    @property
    def controller_execution_approved(self) -> bool:
        return False


def _target_readback(binding: ForeignAdmissionBinding, request: RecoveryRequest,
                     transport: ReadTransport) -> None:
    scope = binding.scope
    path = "/repos/" + scope.repository
    repo = transport.get(path)
    if (not isinstance(repo, dict) or type(repo.get("id")) is not int
            or repo["id"] != scope.repository_id or repo.get("full_name") != scope.repository):
        raise ValueError("repository identity mismatch")
    issue = transport.get(path + "/issues/" + str(binding.issue_number))
    if (not isinstance(issue, dict) or type(issue.get("id")) is not int
            or issue["id"] != scope.issue_id or type(issue.get("number")) is not int
            or issue["number"] != binding.issue_number or issue.get("state") != "open"
            or "pull_request" in issue
            or issue.get("url") != "https://api.github.com" + path + "/issues/" + str(binding.issue_number)):
        raise ValueError("live issue identity mismatch")
    ref = transport.get(path + "/git/ref/heads/" + quote(binding.target_branch, safe="/"))
    if (not isinstance(ref, dict) or ref.get("ref") != "refs/heads/" + binding.target_branch
            or not isinstance(ref.get("object"), dict) or ref["object"].get("type") != "commit"
            or ref["object"].get("sha") != request.target_head):
        raise ValueError("exact target HEAD mismatch")


class ForeignWorkAdmission:
    """Compose existing Samuel recovery with independently authenticated enrollment.

    All ports and the binding must originate from the trusted runtime; a model
    may not supply an issuer, work anchor, enrollment, or Boolean verifier.
    ``verify_enrollment`` must check the independently governed durable record
    and current issuer authority under the configured exact central revision.
    Successful observation is not a grant. No provider or journal writes exist
    in this module; ordinary policy, checkpoint and blocker gates still apply.
    """

    def __init__(self, *, binding: ForeignAdmissionBinding, transport: ReadTransport,
                 history_reader: TrustedReader, verify_scope: TrustedVerifier,
                 verify_coverage: TrustedVerifier,
                 read_enrollment: Callable[[ForeignAdmissionBinding], EnrollmentRecord | None],
                 verify_enrollment: Callable[[ForeignAdmissionBinding, EnrollmentRecord], bool]):
        if not isinstance(binding, ForeignAdmissionBinding):
            raise TypeError("trusted binding required")
        if any(not callable(port) for port in (getattr(transport, "get", None), history_reader,
                    verify_scope, verify_coverage, read_enrollment, verify_enrollment)):
            raise TypeError("all trusted ports required")
        self._binding = binding
        self._transport = transport
        self._history_reader = history_reader
        self._verify_scope = verify_scope
        self._verify_coverage = verify_coverage
        self._read_enrollment = read_enrollment
        self._verify_enrollment = verify_enrollment

    def observe(self, request: RecoveryRequest) -> ForeignAdmissionObservation:
        if not isinstance(request, RecoveryRequest):
            raise TypeError("typed request required")
        if request.scope != self._binding.scope:
            return ForeignAdmissionObservation(AdmissionStatus.TARGET_UNVERIFIED, request,
                                               reason="configured scope mismatch")
        try:
            _target_readback(self._binding, request, self._transport)
        except Exception:
            return ForeignAdmissionObservation(AdmissionStatus.TARGET_UNVERIFIED, request,
                                               reason="initial target readback failed")

        captured: list[HistoryEvidence] = []
        def read(req: RecoveryRequest) -> HistoryEvidence:
            value = self._history_reader(req)
            captured.append(value)
            return value

        recovery = recover_work_identity(request, trusted_reader=read,
                        verify_scope=self._verify_scope, verify_coverage=self._verify_coverage)
        if recovery.status is not RecoveryStatus.HISTORY_VERIFIED:
            # Keep original known blockers and aliases, even if evidence is incomplete.
            return ForeignAdmissionObservation(AdmissionStatus(recovery.status.value),
                                               request, recovery, reason=recovery.reason)
        # A derived legacy candidate is not an existing controller-issued ID.
        if len(captured) != 1 or captured[0].original_work_id != recovery.work_id:
            return ForeignAdmissionObservation(AdmissionStatus.ENROLLMENT_NOT_ATTESTED,
                        request, recovery, reason="no previously issued identity authenticated")
        try:
            record = self._read_enrollment(self._binding)
            if (not isinstance(record, EnrollmentRecord) or record.scope != request.scope
                    or record.issuer_id != self._binding.issuer_id
                    or record.work_id != recovery.work_id
                    or set(record.historical_work_ids) != set(recovery.historical_work_ids)
                    or self._verify_enrollment(self._binding, record) is not True):
                raise ValueError("enrollment record mismatch or unattested issuer")
        except Exception:
            return ForeignAdmissionObservation(AdmissionStatus.ENROLLMENT_NOT_ATTESTED,
                                               request, recovery, reason="trusted enrollment unavailable")
        try:
            _target_readback(self._binding, request, self._transport)
        except Exception:
            return ForeignAdmissionObservation(AdmissionStatus.TARGET_UNVERIFIED, request,
                                               recovery, reason="target changed during observation")
        return ForeignAdmissionObservation(AdmissionStatus.EXISTING_ENROLLMENT_OBSERVED,
                                           request, recovery, record,
                                           "read-only observation; ordinary gates still required")
