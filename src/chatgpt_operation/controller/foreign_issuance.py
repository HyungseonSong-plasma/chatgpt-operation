"""Bind authenticated *existing* issuance to the journal writer's verification port.

This is not an issuer of new identities. An original authority and complete
historical inventory must already be authenticated by the runtime. In particular,
missing records cannot become a new legacy identity or an empty blocker history.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .foreign_work_admission import ForeignAdmissionBinding
from .foreign_enrollment_contract import ForeignEnrollmentAuthority, ForeignEnrollmentAttestation
from .journal_publication import Registration
from ..repository.legacy_work_identity import HistoryEvidence, RecoveryRequest, recover_work_identity, RecoveryStatus
from ..repository.blocker_triage import BlockerObservation, BlockerSource, logical_intent_id


class IssuanceHold(ValueError):
    pass


def require(ok, reason):
    if ok is not True:
        raise IssuanceHold(reason)


@dataclass(frozen=True)
class IssuanceBatch:
    journal_issue_id: int
    history: HistoryEvidence
    attestation: ForeignEnrollmentAttestation
    registrations: tuple[Registration, ...]

    @property
    def issuer_evidence(self):
        return self.attestation.authority_ref

    @property
    def write_authorized(self):
        return False


class ExistingIssuanceVerifier:
    """Prepare and reverify an exact batch before existing append_enrollment.

    Configured history and blocker ports authenticate original records, including
    provider/status and original alias mapping. Authority independently verifies
    the durable existing issuance. This adapter never writes, grants clearance,
    creates a Work ID or replaces a trusted lease/floor/head verifier.
    """
    def __init__(self, *, binding: ForeignAdmissionBinding, journal_issue_id: int,
                 authority: ForeignEnrollmentAuthority, read_history: Callable,
                 verify_scope: Callable, verify_coverage: Callable,
                 read_original_blocker: Callable, verify_original_blocker: Callable,
                 paths: tuple[str, ...]):
        require(isinstance(binding, ForeignAdmissionBinding) and
                isinstance(authority, ForeignEnrollmentAuthority) and
                type(journal_issue_id) is int and journal_issue_id > 0 and
                isinstance(paths, tuple) and bool(paths) and
                all(callable(x) for x in (read_history, verify_scope, verify_coverage,
                                        read_original_blocker, verify_original_blocker)),
                'TRUSTED_ISSUANCE_CONFIGURATION_REQUIRED')
        self.binding, self.issue_id, self.authority = binding, journal_issue_id, authority
        self._read, self._scope, self._coverage = read_history, verify_scope, verify_coverage
        self._blocker, self._verify_blocker, self._paths = read_original_blocker, verify_original_blocker, paths

    def _collect(self, request):
        require(isinstance(request, RecoveryRequest) and request.scope == self.binding.scope,
                'ISSUANCE_SCOPE_MISMATCH')
        evidence = self._read(request)
        require(isinstance(evidence, HistoryEvidence) and evidence.request == request and
                self._scope(evidence) is True, 'IDENTITY_UNVERIFIED')
        # Recovery deliberately returns known blockers before checking coverage.
        # Require completeness here even on the BLOCKER_PRESENT branch.
        require(evidence.coverage_ref is not None and self._coverage(evidence) is True,
                'HISTORY_INCOMPLETE')
        recovery = recover_work_identity(request, trusted_reader=lambda _: evidence,
                                         verify_scope=self._scope, verify_coverage=self._coverage)
        require(recovery.status in (RecoveryStatus.HISTORY_VERIFIED, RecoveryStatus.BLOCKER_PRESENT)
                and evidence.original_work_id is not None and recovery.work_id == evidence.original_work_id,
                'ORIGINAL_ISSUANCE_UNVERIFIED')
        att = self.authority.observe(self.binding)
        require(att.record.work_id == evidence.original_work_id and
                set(att.record.historical_work_ids) == set(evidence.historical_work_ids),
                'ISSUED_IDENTITY_OR_ALIAS_MISMATCH')
        by_intent = {}
        for r in att.registrations:
            computed = logical_intent_id(repository=r.repository, branch=self.binding.target_branch,
                                         work_id=r.work_id, paths=self._paths)
            require(computed == r.intent_id and computed not in by_intent, 'INVALID_ALIAS_INTENT')
            by_intent[computed] = []
        for original in evidence.blockers:
            typed = self._blocker(original)
            require(isinstance(typed, BlockerObservation) and typed.evidence_ref == original.evidence_ref
                    and typed.logical_intent_id in by_intent and
                    (original.original_intent_id is None or original.original_intent_id == typed.logical_intent_id)
                    and self._verify_blocker(original, typed) is True, 'ORIGINAL_BLOCKER_UNVERIFIED')
            recognized = {s.value: s for s in BlockerSource} | {s.name: s for s in BlockerSource}
            require(original.source not in recognized or recognized[original.source] == typed.source,
                    'ORIGINAL_BLOCKER_CLASSIFICATION_CHANGED')
            by_intent[typed.logical_intent_id].append(typed)
        regs = tuple(Registration(r.intent_id, request.target_head, r.registration_ref,
                                  tuple(by_intent[r.intent_id])) for r in att.registrations)
        return IssuanceBatch(self.issue_id, evidence, att, regs)

    def prepare(self, request: RecoveryRequest) -> IssuanceBatch:
        try:
            first = self._collect(request)
            require(self._collect(request) == first, 'ISSUANCE_CHANGED_DURING_READ')
            return first
        except IssuanceHold:
            raise
        except Exception as exc:
            raise IssuanceHold('ISSUANCE_SOURCE_UNAVAILABLE') from exc

    def publication_verifier(self, expected: IssuanceBatch):
        """Return the exact existing writer port; no write performed here."""
        require(isinstance(expected, IssuanceBatch) and expected.journal_issue_id == self.issue_id
                and expected.history.request.scope == self.binding.scope, 'BATCH_SCOPE_MISMATCH')

        def verify(issue_id, registrations, issuer_evidence):
            try:
                return (type(issue_id) is int and issue_id == self.issue_id and
                        registrations == expected.registrations and issuer_evidence == expected.issuer_evidence
                        and self.prepare(expected.history.request) == expected)
            except Exception:
                return False
        return verify
