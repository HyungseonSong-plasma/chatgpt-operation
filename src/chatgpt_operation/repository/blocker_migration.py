"""Trusted legacy blocker reconciliation before Journal work registration.

This helper cannot attest source completeness. That duty belongs to an
independently configured authoritative source verifier, never to a caller's
self-reported inventory, a GitHub Issue comment, or a model-authored plan.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .blocker_journal import GitHubIssueBlockerJournal, JournalError, JournalSnapshot
from .blocker_triage import BlockerObservation, BlockerSource


class HistoricalMigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class HistoricalBlockerInventory:
    logical_intent_id: str
    source_ref: str
    completeness_ref: str
    blockers: tuple[BlockerObservation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.logical_intent_id, str) or len(self.logical_intent_id) != 64:
            raise ValueError("work identity missing")
        if not isinstance(self.source_ref, str) or not self.source_ref.strip():
            raise ValueError("historical source identity missing")
        if not isinstance(self.completeness_ref, str) or not self.completeness_ref.strip():
            raise ValueError("independently verified completeness receipt required")
        if not isinstance(self.blockers, tuple) or not self.blockers:
            # A known-legacy work item MUST contain historical blockers.
            # New clean work needs a different trusted enrollment contract.
            raise ValueError("empty history is not proof of clean prior work")
        keys: set[str] = set()
        for b in self.blockers:
            if not isinstance(b, BlockerObservation):
                raise ValueError("historical event must be a typed blocker")
            if b.logical_intent_id != self.logical_intent_id:
                raise ValueError("historical blocker not bound to same work")
            if b.evidence_ref in keys:
                raise ValueError("ambiguous historical blocker references")
            keys.add(b.evidence_ref)


InventoryVerifier = Callable[[HistoricalBlockerInventory], bool]


def reconcile_legacy_blockers(
    journal: GitHubIssueBlockerJournal, *,
    inventory: HistoricalBlockerInventory,
    exact_head_sha: str,
    registration_evidence_ref: str,
    trusted_inventory_verifier: InventoryVerifier,
) -> JournalSnapshot:
    """Persist all independently verified historical denials, then register.

    On interruption, replay is idempotent for identical records. An altered
    source record or mismatched registration is rejected by the journal.
    IMPORTANT: this does not resolve the blockers and never grants write.
    """
    if not isinstance(journal, GitHubIssueBlockerJournal):
        raise HistoricalMigrationError("trusted owner journal required")
    if not isinstance(inventory, HistoricalBlockerInventory):
        raise HistoricalMigrationError("typed legacy history required")
    if not callable(trusted_inventory_verifier):
        raise HistoricalMigrationError("trusted completeness verifier missing")
    if not isinstance(exact_head_sha, str) or len(exact_head_sha) != 40 or any(
        c not in "0123456789abcdef" for c in exact_head_sha
    ):
        raise HistoricalMigrationError("exact Git HEAD required")
    if not isinstance(registration_evidence_ref, str) or not registration_evidence_ref.strip():
        raise HistoricalMigrationError("registration receipt missing")

    try:
        verified = trusted_inventory_verifier(inventory)
    except Exception as exc:
        raise HistoricalMigrationError("historical completeness verification failed") from exc
    if verified is not True:
        raise HistoricalMigrationError("historical completeness not independently attested")

    try:
        before = journal.read()
        if any(e["payload"]["event"] == "REGISTERED" for e in before.matching(inventory.logical_intent_id)):
            # Never retroactively justify an existing registration with newly
            # supplied proof: enforcement may already have run before import.
            raise HistoricalMigrationError("legacy work registered before verified migration")
        for b in inventory.blockers:
            matches = [e["payload"] for e in journal.read().matching(inventory.logical_intent_id)
                       if e["payload"]["event"] == "BLOCKED"
                       and e["payload"]["evidence_ref"] == b.evidence_ref]
            if matches:
                if len(matches) != 1 or matches[0] != {
                    "event": "BLOCKED", "intent": b.logical_intent_id,
                    "source": b.source.value, "provider": b.provider,
                    "evidence_ref": b.evidence_ref, "http_status": b.http_status,
                }:
                    raise HistoricalMigrationError("historical record conflict")
            else:
                journal.record_blocker(b)
        after = journal.read()
        actual = {e["payload"]["evidence_ref"] for e in after.matching(inventory.logical_intent_id)
                  if e["payload"]["event"] == "BLOCKED"}
        required = {b.evidence_ref for b in inventory.blockers}
        if not required.issubset(actual):
            raise HistoricalMigrationError("durable blocker import incomplete")
        # Enrollment happens last. It is NOT a clearance, and the common
        # gate will continue to stop on every imported active blocker.
        return journal.register_work(
            logical_intent_id=inventory.logical_intent_id,
            exact_head_sha=exact_head_sha,
            evidence_ref=registration_evidence_ref,
        )
    except JournalError as exc:
        raise HistoricalMigrationError("journal rejected historical migration") from exc
