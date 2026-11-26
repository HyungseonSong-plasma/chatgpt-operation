"""Trusted composition of existing foreign enrollment and anchored journal ports."""
from __future__ import annotations
from dataclasses import dataclass
from .foreign_work_admission import (
    ForeignAdmissionBinding, ForeignWorkAdmission, AdmissionStatus, ForeignAdmissionObservation,
)
from .foreign_enrollment_contract import ForeignEnrollmentAuthority, ForeignEnrollmentAttestation
from .foreign_anchored_journal import AnchoredForeignJournal
from ..repository.legacy_work_identity import RecoveryRequest


@dataclass(frozen=True)
class InitEnrollmentObservation:
    """Cycle-local evidence, not a clearance or execution permission."""
    attestation: ForeignEnrollmentAttestation
    admission: ForeignAdmissionObservation

    @property
    def record(self):
        # Preserve the Moose consumer's evidence-ref interface.
        return self.attestation.record


class ForeignInitRuntime:
    def __init__(self, *, binding: ForeignAdmissionBinding, authority: ForeignEnrollmentAuthority,
                 journal: AnchoredForeignJournal, transport, history_reader, verify_scope,
                 verify_coverage, paths: tuple[str,...]):
        if (not isinstance(binding, ForeignAdmissionBinding) or not isinstance(authority, ForeignEnrollmentAuthority)
                or not isinstance(journal, AnchoredForeignJournal) or not isinstance(paths,tuple) or not paths):
            raise ValueError('trusted runtime configuration required')
        self.binding,self._authority,self._journal,self._paths = binding,authority,journal,paths
        self._admission=ForeignWorkAdmission(binding=binding,transport=transport,history_reader=history_reader,
                    verify_scope=verify_scope,verify_coverage=verify_coverage,
                    read_enrollment=authority.read_enrollment,verify_enrollment=authority.verify_enrollment)

    def _enrollment(self, request):
        if request['repository'] != self.binding.scope.repository or request['target_branch'] != self.binding.target_branch:
            raise ValueError('runtime scope mismatch')
        observation=self._admission.observe_for_blocker_gate(RecoveryRequest(self.binding.scope,request['target_sha']))
        if observation.status not in (AdmissionStatus.EXISTING_ENROLLMENT_OBSERVED,
                                      AdmissionStatus.ENROLLMENT_OBSERVED_BLOCKER_CHECK_REQUIRED):
            raise ValueError(observation.status.value)
        attestation=self._authority.observe(self.binding)
        if attestation.record != observation.enrollment or request['work_id'] != attestation.record.work_id:
            raise ValueError('request/enrollment identity mismatch')
        return InitEnrollmentObservation(attestation, observation)

    def observe_enrollment(self,request):
        return self._enrollment(request)

    def observe_blockers(self,request,expected):
        before=self._enrollment(request)
        if before != expected:
            raise ValueError('enrollment or history changed within INIT')
        ref=self._journal.observe(before.attestation,branch=self.binding.target_branch,paths=self._paths,
                                  head=request['target_sha'],historical_blockers=before.admission.recovery.blockers)
        if self._enrollment(request) != before:
            raise ValueError('enrollment or history changed after blocker observation')
        return ref
