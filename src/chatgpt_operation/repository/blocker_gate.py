"""Shared pre-write blocker gate backed by a complete trusted journal read.

This guard checks blocker history, not repository write authorization. The
caller must still enforce normal permissions, branch protection, CI and review.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .blocker_journal import GitHubIssueBlockerJournal, JournalError
from .blocker_triage import BlockerObservation, BlockerSource
from .blocker_resolution import (
    BlockerState, ClearanceEvidence, ClearanceKind, Verifier, evaluate_clearance,
)


class BlockerGateError(RuntimeError):
    pass


@dataclass(frozen=True)
class GateDecision:
    no_active_blocker: bool
    reason: str
    checked_events: int
    tip: str
    # This is NEVER general write authorization.
    write_authorized: bool = False


class CommonPreWriteGate:
    """Fail-closed same-work gate intended for every mutating dispatch path.

    All callbacks and the journal transport must be instantiated from trusted
    controller configuration, not supplied in a model-generated ActionPlan.
    """

    def __init__(self, *, journal: GitHubIssueBlockerJournal,
                 trusted_head_reader: Callable[[], str],
                 technical_verifier: Verifier, authority_verifier: Verifier):
        if not isinstance(journal, GitHubIssueBlockerJournal):
            raise BlockerGateError("configured trusted journal required")
        if any(not callable(f) for f in (
            trusted_head_reader, technical_verifier, authority_verifier,
        )):
            raise BlockerGateError("trusted head and evidence verification adapters required")
        self.journal = journal
        self.read_head = trusted_head_reader
        self.technical_verifier = technical_verifier
        self.authority_verifier = authority_verifier

    def evaluate(self, *, logical_intent_id: str, expected_head_sha: str) -> GateDecision:
        try:
            observed_head = self.read_head()
        except Exception as exc:
            raise BlockerGateError("trusted current HEAD readback unavailable") from exc
        if observed_head != expected_head_sha:
            raise BlockerGateError("stale or unverifiable target HEAD")
        try:
            snapshot = self.journal.read()
            events = snapshot.matching(logical_intent_id)
        except (JournalError, KeyError, ValueError, TypeError) as exc:
            raise BlockerGateError("complete trusted journal unavailable") from exc
        # Without a trusted controller-issued work registration we cannot
        # distinguish a brand-new task from historical denials not yet
        # migrated to this journal. Fail closed, not 'empty means safe'.
        enrollment = [e for e in events if e["payload"]["event"] == "REGISTERED"]
        if len(enrollment) != 1:
            return GateDecision(False, "WORK_REGISTRATION_NOT_ATTESTED",
                                len(events), snapshot.tip)
        blockers = [e["payload"] for e in events if e["payload"]["event"] == "BLOCKED"]
        for payload in blockers:
            blocker = BlockerObservation(
                BlockerSource(payload["source"]), payload["intent"],
                payload["provider"], payload["evidence_ref"], payload["http_status"],
            )
            clearances = [
                e["payload"] for e in events
                if e["payload"]["event"] == "CLEARED"
                and e["payload"]["blocker_evidence_ref"] == blocker.evidence_ref
            ]
            resolved = False
            for c in clearances:
                proof = ClearanceEvidence(
                    c["intent"], c["blocker_evidence_ref"], ClearanceKind(c["kind"]),
                    c["head"], c["evidence_ref"],
                )
                decision = evaluate_clearance(
                    blocker, proof, expected_head_sha=observed_head,
                    verify_technical=self.technical_verifier,
                    verify_authority=self.authority_verifier,
                )
                if decision.state in {
                    BlockerState.RESOLVED_AUTOMATICALLY,
                    BlockerState.RESOLVED_BY_AUTHORITY,
                }:
                    resolved = True
                    break
            if not resolved:
                return GateDecision(
                    False, "ACTIVE_BLOCKER_" + blocker.source.value.upper(),
                    len(events), snapshot.tip,
                )
        return GateDecision(True, "NO_ACTIVE_BLOCKER_NOT_WRITE_AUTHORIZATION",
                            len(events), snapshot.tip)

    def require_clear(self, *, logical_intent_id: str, expected_head_sha: str) -> GateDecision:
        result = self.evaluate(logical_intent_id=logical_intent_id,
                               expected_head_sha=expected_head_sha)
        if not result.no_active_blocker:
            raise BlockerGateError(result.reason)
        return result
