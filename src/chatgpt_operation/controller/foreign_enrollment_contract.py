"""Read-only foreign enrollment contract. No issuance or implicit migration.

The trusted composition root owns the independently authenticated authority
reader and its freshness/revocation verifier. A record or an Issue author alone
is not evidence of issuer authority. Never construct these ports from a plan.
"""
from __future__ import annotations
from dataclasses import dataclass
import re
from typing import Callable
from .foreign_work_admission import ForeignAdmissionBinding, EnrollmentRecord


class EnrollmentError(ValueError):
    pass


@dataclass(frozen=True)
class IntentRegistration:
    repository: str
    work_id: str
    intent_id: str
    registration_ref: str

    def __post_init__(self):
        if (not isinstance(self.repository, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', self.repository)
                or not isinstance(self.intent_id, str) or not re.fullmatch(r'[0-9a-f]{64}', self.intent_id)
                or any(not isinstance(x, str) or not x or x != x.strip()
                       for x in (self.work_id, self.registration_ref))):
            raise EnrollmentError('invalid intent registration')
        # Reuse Samuel's work-level identity rule; branch/path are not identity.
        # Verify the digest with the authoritative identity helper in the journal adapter.


@dataclass(frozen=True)
class ForeignEnrollmentAttestation:
    record: EnrollmentRecord
    central_revision: str
    generation: int
    authority_ref: str
    registrations: tuple[IntentRegistration, ...]

    def __post_init__(self):
        if (not isinstance(self.record, EnrollmentRecord)
                or not isinstance(self.central_revision, str) or not re.fullmatch(r'[0-9a-f]{40}', self.central_revision)
                or type(self.generation) is not int or self.generation < 1
                or not isinstance(self.authority_ref, str) or not self.authority_ref.strip()
                or not isinstance(self.registrations, tuple) or not self.registrations
                or any(not isinstance(x, IntentRegistration) for x in self.registrations)):
            raise EnrollmentError('invalid authority attestation')
        if len({x.intent_id for x in self.registrations}) != len(self.registrations):
            raise EnrollmentError('duplicate intent identity')
        if {x.work_id for x in self.registrations} != set(self.record.historical_work_ids):
            raise EnrollmentError('historical alias coverage mismatch')
        canonical = [x for x in self.registrations if x.repository == self.record.scope.repository
                     and x.work_id == self.record.work_id]
        if len(canonical) != 1 or canonical[0].registration_ref != self.record.evidence_ref:
            raise EnrollmentError('canonical registration mismatch')


class ForeignEnrollmentAuthority:
    """Observe existing records only; absent or unstable authority fails closed.

    verify_authority must authenticate the source, full alias/repository census,
    original issuance, current revocation/version and minimum durable generation.
    The verifier is independent of request data and the record's own claims.
    """
    def __init__(self, *, read: Callable, verify_authority: Callable,
                 minimum_generation: int):
        if (not callable(read) or not callable(verify_authority)
                or type(minimum_generation) is not int or minimum_generation < 1):
            raise EnrollmentError('trusted authority and durable floor required')
        self._read, self._verify, self._minimum = read, verify_authority, minimum_generation

    def observe(self, binding: ForeignAdmissionBinding) -> ForeignEnrollmentAttestation:
        if not isinstance(binding, ForeignAdmissionBinding):
            raise EnrollmentError('trusted binding required')
        first = self._read(binding)
        if (not isinstance(first, ForeignEnrollmentAttestation)
                or first.record.scope != binding.scope or first.record.issuer_id != binding.issuer_id
                or first.central_revision != binding.central_revision or first.generation < self._minimum
                or self._verify(binding, first) is not True):
            raise EnrollmentError('foreign enrollment not independently attested')
        second = self._read(binding)
        if second != first or self._verify(binding, second) is not True:
            raise EnrollmentError('enrollment changed during readback')
        return first

    def read_enrollment(self, binding: ForeignAdmissionBinding) -> EnrollmentRecord:
        return self.observe(binding).record

    def verify_enrollment(self, binding: ForeignAdmissionBinding, record: EnrollmentRecord) -> bool:
        try:
            return self.observe(binding).record == record
        except Exception:
            return False
