"""Read-only adapter over Samuel's existing journal, checkpoint and blocker gate.

No Issue creation, comments, registration, clearance, anchor advancement or
provider writes. Independent storage/authority must be proven by trusted runtime,
not inferred from distinct labels or a matching hash.
"""
from __future__ import annotations
from dataclasses import dataclass
import re
from typing import Callable
from ..repository.blocker_journal import GitHubIssueBlockerJournal
from ..repository.blocker_checkpoint import JournalCheckpoint, require_checkpoint
from ..repository.blocker_gate import CommonPreWriteGate
from ..repository.blocker_triage import BlockerObservation, BlockerSource, logical_intent_id
from ..repository.legacy_work_identity import HistoricalRecord
from .foreign_enrollment_contract import ForeignEnrollmentAttestation


class JournalBindingError(ValueError):
    pass


@dataclass(frozen=True)
class JournalBinding:
    repository: str
    repository_id: int
    issue_number: int
    issue_id: int
    actor_login: str
    actor_id: int
    journal_boundary: str
    anchor_boundary: str

    def __post_init__(self):
        if (not isinstance(self.repository, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', self.repository)
                or any(type(x) is not int or x < 1 for x in (self.repository_id,self.issue_number,self.issue_id,self.actor_id))
                or any(not isinstance(x,str) or not x or x != x.strip() for x in
                       (self.actor_login,self.journal_boundary,self.anchor_boundary))
                or self.journal_boundary == self.anchor_boundary):
            raise JournalBindingError('fixed journal and distinct anchor boundary required')


@dataclass(frozen=True)
class AnchorAttestation:
    binding: JournalBinding
    checkpoint: JournalCheckpoint
    boundary: str
    authority_ref: str

    def __post_init__(self):
        if (not isinstance(self.binding, JournalBinding) or not isinstance(self.checkpoint, JournalCheckpoint)
                or self.boundary != self.binding.anchor_boundary
                or not isinstance(self.authority_ref,str) or not self.authority_ref.strip()):
            raise JournalBindingError('invalid independently sourced checkpoint')


class ReadOnlyJournalTransport:
    def __init__(self, binding, transport):
        self.binding, self.transport = binding, transport
        self.base = '/repos/' + binding.repository
        self.issue = '/issues/' + str(binding.issue_number)

    def verify_identity(self):
        b = self.binding
        r = self.transport.get(self.base)
        i = self.transport.get(self.base + self.issue)
        if (not isinstance(r,dict) or type(r.get('id')) is not int or r['id'] != b.repository_id
                or r.get('full_name') != b.repository or not isinstance(i,dict)
                or type(i.get('id')) is not int or i['id'] != b.issue_id
                or i.get('number') != b.issue_number or 'pull_request' in i
                or i.get('url') != 'https://api.github.com' + self.base + self.issue):
            raise JournalBindingError('journal repository/issue identity mismatch')

    def get(self, path, *, query=None):
        from ..repository.blocker_journal import MARKER
        if path != self.issue + '/comments':
            raise JournalBindingError('outside fixed journal read scope')
        self.verify_identity()
        rows = self.transport.get(self.base + path, query=query)
        if not isinstance(rows,list):
            raise JournalBindingError('journal page malformed')
        for row in rows:
            if not isinstance(row,dict) or not isinstance(row.get('body'),str):
                raise JournalBindingError('journal comment malformed')
            if row['body'].startswith(MARKER):
                u = row.get('user')
                if not isinstance(u,dict) or type(u.get('id')) is not int or u['id'] != self.binding.actor_id or u.get('login') != self.binding.actor_login:
                    raise JournalBindingError('journal writer identity mismatch')
        return rows

    def request(self, *args, **kwargs):
        raise JournalBindingError('read-only journal transport')


class AnchoredForeignJournal:
    def __init__(self, *, binding: JournalBinding, transport, read_anchor: Callable,
                 verify_anchor: Callable, durable_floor: JournalCheckpoint,
                 technical_verifier: Callable, authority_verifier: Callable,
                 read_head: Callable,
                 verify_historical_blocker: Callable[[HistoricalRecord, BlockerObservation], bool] | None = None):
        if (not isinstance(binding,JournalBinding) or not isinstance(durable_floor,JournalCheckpoint)
                or any(not callable(x) for x in (getattr(transport,'get',None),read_anchor,verify_anchor,
                                                 technical_verifier,authority_verifier,read_head))):
            raise JournalBindingError('all trusted journal/anchor ports and durable floor required')
        if verify_historical_blocker is not None and not callable(verify_historical_blocker):
            raise JournalBindingError('invalid original blocker verifier')
        self._verify_historical_blocker = verify_historical_blocker
        self.binding, self._floor = binding, durable_floor
        self._read_anchor,self._verify_anchor = read_anchor,verify_anchor
        self._head,self._tech,self._authority = read_head,technical_verifier,authority_verifier
        self._transport = ReadOnlyJournalTransport(binding,transport)
        self._journal = GitHubIssueBlockerJournal(self._transport,issue_number=binding.issue_number,
                                                  trusted_actor=binding.actor_login)

    def _anchor(self):
        a = self._read_anchor(self.binding)
        if (not isinstance(a,AnchorAttestation) or a.binding != self.binding
                or a.checkpoint.sequence < self._floor.sequence
                or self._verify_anchor(self.binding,a) is not True):
            raise JournalBindingError('independent anchor not verified')
        return a

    def _require_historical_records(self, snapshot, attestation, historical_blockers):
        """Require the anchored journal to preserve every authenticated original denial.

        HistoricalRecord carries no provider or HTTP status. The trusted
        original-source verifier must authenticate the full typed observation,
        including classification, provider/status and any legacy intent mapping.
        A matching evidence reference alone cannot authenticate those fields.
        """
        if (not isinstance(historical_blockers, tuple)
                or any(not isinstance(r, HistoricalRecord) for r in historical_blockers)):
            raise JournalBindingError('typed historical records required')
        if not historical_blockers:
            return
        if self._verify_historical_blocker is None:
            raise JournalBindingError('original blocker verifier required')
        intents = {r.intent_id for r in attestation.registrations}
        for original in historical_blockers:
            matches = [e['payload'] for e in snapshot.events
                       if e['payload']['event'] == 'BLOCKED'
                       and e['payload']['intent'] in intents
                       and e['payload']['evidence_ref'] == original.evidence_ref]
            if len(matches) != 1:
                raise JournalBindingError('historical blocker missing or ambiguous in anchored journal')
            p = matches[0]
            if original.original_intent_id is not None and original.original_intent_id != p['intent']:
                raise JournalBindingError('historical blocker intent mismatch')
            typed = BlockerObservation(BlockerSource(p['source']), p['intent'],
                                       p['provider'], p['evidence_ref'], p['http_status'])
            # When the legacy source already names a recognized classification,
            # it cannot be replaced by a less restrictive category.
            for source in BlockerSource:
                if original.source in (source.value, source.name) and typed.source is not source:
                    raise JournalBindingError('historical blocker source mismatch')
            try:
                verified = self._verify_historical_blocker(original, typed) is True
            except Exception:
                verified = False
            if not verified:
                raise JournalBindingError('original blocker observation not authenticated')

    def observe(self, attestation: ForeignEnrollmentAttestation, *, branch: str, paths: tuple[str,...], head: str,
                historical_blockers: tuple[HistoricalRecord, ...] = ()) -> str:
        if not isinstance(attestation,ForeignEnrollmentAttestation):
            raise JournalBindingError('attested enrollment required')
        # The issuer must authenticate historical repository aliases as well as IDs.
        for reg in attestation.registrations:
            if logical_intent_id(repository=reg.repository,branch=branch,work_id=reg.work_id,paths=paths) != reg.intent_id:
                raise JournalBindingError('logical intent mismatch')
        if self._head() != head:
            raise JournalBindingError('stale target HEAD')
        anchor = self._anchor()
        snapshot = self._journal.read()
        require_checkpoint(snapshot,anchor.checkpoint)
        if snapshot.events[self._floor.sequence-1]['hash'] != self._floor.tip:
            raise JournalBindingError('journal rollback or rewritten floor')
        self._require_historical_records(snapshot, attestation, historical_blockers)
        gate = CommonPreWriteGate(journal=self._journal,trusted_head_reader=self._head,
                    technical_verifier=self._tech,authority_verifier=self._authority,
                    trusted_checkpoint_reader=lambda: self._same_anchor(anchor))
        for reg in attestation.registrations:
            registered = [x['payload'] for x in snapshot.matching(reg.intent_id) if x['payload']['event']=='REGISTERED']
            if len(registered)!=1 or registered[0]['evidence_ref'] != reg.registration_ref:
                raise JournalBindingError('registration evidence mismatch')
            verdict = gate.require_clear(logical_intent_id=reg.intent_id,expected_head_sha=head)
            if verdict.tip != anchor.checkpoint.tip:
                raise JournalBindingError('gate journal tip changed')
        final = self._journal.read()
        require_checkpoint(final,self._same_anchor(anchor))
        if final != snapshot or self._head() != head:
            raise JournalBindingError('journal or target changed during observation')
        return 'journal:' + str(self.binding.issue_id) + '@' + final.tip

    def _same_anchor(self, expected):
        actual = self._anchor()
        if actual != expected:
            raise JournalBindingError('anchor changed during observation')
        return actual.checkpoint
