"""Bounded Samuel writer orchestration; trust ports belong to the deployment.

Never obtain authority, a lease, a historic inventory, or an anchor from an
ActionPlan. This module has no network credentials or workflow dispatcher.
A successful publication is evidence, not mutation authorization.
"""
from __future__ import annotations
from dataclasses import dataclass
import re
from ..repository.blocker_journal import GitHubIssueBlockerJournal, ZERO, blocker_payload
from ..repository.blocker_checkpoint import JournalCheckpoint, require_checkpoint
from ..repository.blocker_triage import BlockerObservation


class PublicationHold(RuntimeError):
    pass


def require(ok, reason):
    if ok is not True:
        raise PublicationHold(reason)


@dataclass(frozen=True)
class Registration:
    intent: str
    head: str
    evidence_ref: str
    blockers: tuple[BlockerObservation, ...] = ()

    def __post_init__(self):
        require(isinstance(self.intent, str) and bool(re.fullmatch(r'[0-9a-f]{64}', self.intent)), 'INVALID_INTENT')
        require(isinstance(self.head, str) and bool(re.fullmatch(r'[0-9a-f]{40}', self.head)), 'INVALID_HEAD')
        require(isinstance(self.evidence_ref, str) and bool(self.evidence_ref.strip()), 'MISSING_EVIDENCE')
        require(isinstance(self.blockers, tuple) and all(isinstance(b, BlockerObservation) and b.logical_intent_id == self.intent for b in self.blockers), 'INVALID_HISTORY')
        require(len({b.evidence_ref for b in self.blockers}) == len(self.blockers), 'DUPLICATE_HISTORY')


@dataclass(frozen=True)
class PublicationReceipt:
    issue_id: int
    before_sequence: int
    before_tip: str
    sequence: int
    tip: str
    issuer_evidence: str

    @property
    def write_authorized(self):
        return False


def _match_prefix(snapshot, sequence, tip):
    require(type(sequence) is int and 0 <= sequence <= len(snapshot.events), 'JOURNAL_PREFIX_MISSING')
    require((snapshot.events[sequence - 1]['hash'] if sequence else ZERO) == tip, 'JOURNAL_PREFIX_REWRITTEN')


def append_enrollment(*, journal, issue_id, registrations, issuer_evidence,
                      verify_issuance, verify_lease, read_floor, verify_genesis,
                      read_head):
    """Register an authenticated existing identity/alias batch; never clear.

    verify_issuance must prove historic completeness, canonical identity, all
    aliases and the issued scope, not merely validate a supplied string. A
    durable external lease must cover the complete transaction and anchoring.
    Initial empty state requires separately authenticated genesis. A partial
    write remains HOLD; a later invocation must reconcile it, not retry blindly.
    """
    require(isinstance(journal, GitHubIssueBlockerJournal), 'TRUSTED_JOURNAL_REQUIRED')
    require(type(issue_id) is int and issue_id > 0, 'ISSUE_ID_REQUIRED')
    require(isinstance(registrations, tuple) and bool(registrations) and all(isinstance(r, Registration) for r in registrations), 'REGISTRATIONS_REQUIRED')
    require(len({r.intent for r in registrations}) == len(registrations), 'DUPLICATE_INTENT')
    require(isinstance(issuer_evidence, str) and bool(issuer_evidence.strip()), 'ISSUER_EVIDENCE_REQUIRED')
    require(verify_lease() is True, 'LEASE_NOT_ATTESTED')
    require(verify_issuance(issue_id, registrations, issuer_evidence) is True, 'ISSUANCE_NOT_ATTESTED')
    before = journal.read()
    floor = read_floor()
    if floor is None:
        require(not before.events and before.tip == ZERO and verify_genesis(issue_id) is True, 'GENESIS_NOT_ATTESTED')
    else:
        require_checkpoint(before, floor)
    # No write until the entire batch has passed consistency checks.
    for r in registrations:
        require(read_head(r) == r.head, 'STALE_TARGET')
        records = [e['payload'] for e in before.matching(r.intent)]
        require(not any(p['event'] == 'REGISTERED' for p in records), 'ALREADY_REGISTERED_RECONCILE_ONLY')
        expected = {b.evidence_ref: b for b in r.blockers}
        for p in records:
            if p['event'] == 'BLOCKED':
                b = expected.get(p['evidence_ref'])
                require(b is not None and p['source'] == b.source.value and p['provider'] == b.provider and p['http_status'] == b.http_status, 'HISTORY_CONFLICT')
    expected_payloads = [e['payload'] for e in before.events]
    for r in registrations:
        for b in r.blockers:
            require(verify_lease() is True and read_head(r) == r.head, 'LEASE_OR_HEAD_CHANGED')
            journal.record_blocker(b)
            payload = blocker_payload(b)
            if payload not in expected_payloads:
                expected_payloads.append(payload)
        require(verify_lease() is True and read_head(r) == r.head, 'LEASE_OR_HEAD_CHANGED')
        journal.register_work(logical_intent_id=r.intent, exact_head_sha=r.head, evidence_ref=r.evidence_ref)
        expected_payloads.append({'event': 'REGISTERED', 'intent': r.intent, 'head': r.head, 'evidence_ref': r.evidence_ref})
    after = journal.read()
    _match_prefix(after, len(before.events), before.tip)
    require([e['payload'] for e in after.events] == expected_payloads, 'UNEXPECTED_JOURNAL_DELTA')
    require(verify_lease() is True and all(read_head(r) == r.head for r in registrations), 'LEASE_OR_HEAD_CHANGED')
    require(read_floor() == floor, 'ANCHOR_CHANGED_DURING_APPEND')
    return PublicationReceipt(issue_id, len(before.events), before.tip, len(after.events), after.tip, issuer_evidence)


def publish_checkpoint(*, journal, receipt, verify_receipt, read_floor,
                       verify_genesis, verify_lease, verify_ruleset, read_ref,
                       create_once, verify_publication):
    """Independent anchor role: read full journal, verify issuance receipt,
    then create a sequence-specific protected ref. Never update/delete or
    retry an uncertain publication. The trusted publisher must bind the
    payload and its run provenance to an immutable commit and exact ref.
    """
    require(isinstance(journal, GitHubIssueBlockerJournal) and isinstance(receipt, PublicationReceipt), 'TYPED_PUBLICATION_REQUIRED')
    require(type(receipt.issue_id) is int and receipt.issue_id > 0 and type(receipt.sequence) is int and type(receipt.before_sequence) is int and receipt.sequence > receipt.before_sequence >= 0, 'INVALID_RECEIPT_SEQUENCE')
    require(isinstance(receipt.tip, str) and bool(re.fullmatch(r'[0-9a-f]{64}', receipt.tip)) and receipt.tip != ZERO, 'INVALID_TIP')
    require(verify_lease() is True and verify_ruleset() is True, 'ANCHOR_BOUNDARY_NOT_ATTESTED')
    require(verify_receipt(receipt) is True, 'WRITER_PROVENANCE_NOT_ATTESTED')
    floor = read_floor()
    if floor is None:
        require(receipt.before_sequence == 0 and receipt.before_tip == ZERO and verify_genesis(receipt.issue_id) is True, 'GENESIS_NOT_ATTESTED')
    else:
        require(isinstance(floor, JournalCheckpoint) and floor.sequence == receipt.before_sequence and floor.tip == receipt.before_tip, 'STALE_ANCHOR_FLOOR')
    snapshot = journal.read()
    _match_prefix(snapshot, receipt.before_sequence, receipt.before_tip)
    ref = f'refs/heads/samuel/journal-anchors/{receipt.issue_id}-{receipt.sequence:012d}'
    checkpoint = JournalCheckpoint(receipt.sequence, receipt.tip, ref)
    require_checkpoint(snapshot, checkpoint)
    require(read_ref(ref) is None, 'ANCHOR_EXISTS_RECONCILE_ONLY')
    require(verify_lease() is True and verify_ruleset() is True and read_floor() == floor and journal.read() == snapshot, 'PUBLICATION_PRECONDITION_CHANGED')
    # No automatic retry: provider failure is an unknown publication outcome.
    result = create_once(ref, checkpoint, receipt)
    observed = read_ref(ref)
    require(observed is not None and observed == result and verify_publication(ref, checkpoint, receipt, observed) is True, 'ANCHOR_READBACK_FAILED')
    require(verify_ruleset() is True and verify_lease() is True and journal.read() == snapshot, 'POST_PUBLICATION_STATE_CHANGED')
    return checkpoint
