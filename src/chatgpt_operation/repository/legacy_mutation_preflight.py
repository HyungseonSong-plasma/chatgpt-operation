"""Read-only bridge for repository-mutation; not a provider dispatcher."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from .legacy_work_identity import (
    RecoveryRequest, RecoveryResult, RecoveryStatus, TrustedReader, TrustedVerifier,
    recover_work_identity,
)
from .legacy_github_history import GitHubHistoryReader, GitHubHistorySnapshot
from .legacy_work_identity import HistoryEvidence


class HistoryDisposition(str, Enum):
    RESTORE_IDENTITY = "RESTORE_IDENTITY"
    RESTORE_COVERAGE = "RESTORE_COVERAGE"
    EXISTING_BLOCKER_GATE = "EXISTING_BLOCKER_GATE"
    CONTINUE_ORDINARY_PREFLIGHT = "CONTINUE_ORDINARY_PREFLIGHT"


@dataclass(frozen=True)
class HistoryPreflight:
    request: RecoveryRequest
    recovery: RecoveryResult

    @property
    def disposition(self) -> HistoryDisposition:
        return {
            RecoveryStatus.IDENTITY_UNVERIFIED: HistoryDisposition.RESTORE_IDENTITY,
            RecoveryStatus.HISTORY_INCOMPLETE: HistoryDisposition.RESTORE_COVERAGE,
            RecoveryStatus.BLOCKER_PRESENT: HistoryDisposition.EXISTING_BLOCKER_GATE,
            RecoveryStatus.HISTORY_VERIFIED: HistoryDisposition.CONTINUE_ORDINARY_PREFLIGHT,
        }[self.recovery.status]

    @property
    def mutation_authorized(self) -> bool:
        return False


def observe_history(request: RecoveryRequest, *, reader: TrustedReader,
                    verify_scope: TrustedVerifier, verify_coverage: TrustedVerifier) -> HistoryPreflight:
    """Distinguish missing evidence from a recorded blocker before branch preflight.

    A verified observation allows only the next ordinary read-only preflight
    step. Existing installed CommonPreWriteGate and all provider guards remain.
    Known historical records are passed intact to existing triage/clearance.
    """
    if not isinstance(request, RecoveryRequest):
        raise TypeError("typed recovery request required")
    return HistoryPreflight(request, recover_work_identity(
        request, trusted_reader=reader, verify_scope=verify_scope,
        verify_coverage=verify_coverage))


def observe_github_history(request: RecoveryRequest, *, reader: GitHubHistoryReader,
                           resolve: Callable[[GitHubHistorySnapshot], HistoryEvidence],
                           verify_scope: TrustedVerifier,
                           verify_coverage: TrustedVerifier) -> HistoryPreflight:
    """Compose S2's GitHub collector with the S1 recovery contract."""
    return observe_history(request, reader=lambda req: reader.read_evidence(req, resolve=resolve),
                           verify_scope=verify_scope, verify_coverage=verify_coverage)
