from dataclasses import replace
import unittest
from chatgpt_operation.controller.journal_publication import (
    Registration, PublicationHold, append_enrollment, publish_checkpoint,
)
from chatgpt_operation.repository.blocker_journal import GitHubIssueBlockerJournal, JournalError
from chatgpt_operation.repository.blocker_triage import BlockerObservation, BlockerSource


class Fixture:
    def __init__(self):
        self.rows = []
        self.refs = {}
        self.floor = None
        self.head = 'a' * 40
        self.journal = GitHubIssueBlockerJournal(self, issue_number=329, trusted_actor='fixture')
        self.reg = Registration('1' * 64, self.head, 'verified:fixture', (
            BlockerObservation(BlockerSource.TOOL_SAFETY, '1' * 64, 'original-provider', 'original-denial'),
        ))

    def get(self, path, *, query=None):
        return self.rows if query['page'] == '1' else []

    def request(self, method, path, *, payload):
        row = {'id': len(self.rows)+1, 'body': payload['body'], 'user': {'login': 'fixture'}}
        self.rows.append(row)
        return {'id': row['id']}

    def append(self, **kw):
        args = dict(journal=self.journal, issue_id=6624795458, registrations=(self.reg,), issuer_evidence='issuer:fixture',
                    verify_issuance=lambda *_: True, verify_lease=lambda: True, read_floor=lambda: self.floor,
                    verify_genesis=lambda _: True, read_head=lambda _: self.head)
        args.update(kw)
        return append_enrollment(**args)

    def create(self, ref, checkpoint, receipt):
        assert ref not in self.refs
        self.refs[ref] = 'commit:fixture'
        return self.refs[ref]

    def publish(self, receipt, **kw):
        args = dict(journal=self.journal, receipt=receipt, verify_receipt=lambda _: True, read_floor=lambda: self.floor,
                    verify_genesis=lambda _: True, verify_lease=lambda: True, verify_ruleset=lambda: True,
                    read_ref=self.refs.get, create_once=self.create, verify_publication=lambda *_: True)
        args.update(kw)
        return publish_checkpoint(**args)


class TestJournalPublicationTests(unittest.TestCase):
    def test_registration_preserves_blocker_and_anchors(self):
        f = Fixture(); receipt = f.append(); cp = f.publish(receipt)
        assert [e['payload']['event'] for e in f.journal.read().events] == ['BLOCKED', 'REGISTERED']
        assert cp.sequence == 2 and cp.tip == receipt.tip and not receipt.write_authorized
        assert cp.anchor_ref == 'refs/heads/samuel/journal-anchors/6624795458-000000000002'

    _cases_test_append_holds_without_writes = [
        {'verify_issuance': lambda *_: False}, {'verify_issuance': lambda *_: 1},
        {'verify_lease': lambda: False}, {'verify_genesis': lambda _: False},
        {'read_head': lambda _: 'b'*40}, {'registrations': ()},
    ]

    def _check_test_append_holds_without_writes(self, override):
        f = Fixture()
        with self.assertRaises(PublicationHold): f.append(**override)
        assert f.rows == []

    def test_append_holds_without_writes_01(self):
        self._check_test_append_holds_without_writes(self._cases_test_append_holds_without_writes[0])

    def test_append_holds_without_writes_02(self):
        self._check_test_append_holds_without_writes(self._cases_test_append_holds_without_writes[1])

    def test_append_holds_without_writes_03(self):
        self._check_test_append_holds_without_writes(self._cases_test_append_holds_without_writes[2])

    def test_append_holds_without_writes_04(self):
        self._check_test_append_holds_without_writes(self._cases_test_append_holds_without_writes[3])

    def test_append_holds_without_writes_05(self):
        self._check_test_append_holds_without_writes(self._cases_test_append_holds_without_writes[4])

    def test_append_holds_without_writes_06(self):
        self._check_test_append_holds_without_writes(self._cases_test_append_holds_without_writes[5])

    def test_existing_registration_not_reissued(self):
        f = Fixture(); f.append()
        with self.assertRaises((PublicationHold, JournalError)): f.append()
        assert len(f.rows) == 2

    _cases_test_anchor_holds_before_write = [
        {'verify_receipt': lambda _: False}, {'verify_lease': lambda: False},
        {'verify_ruleset': lambda: False}, {'verify_genesis': lambda _: False},
        {'read_ref': lambda _: 'already-exists'},
    ]

    def _check_test_anchor_holds_before_write(self, override):
        f = Fixture(); receipt = f.append()
        with self.assertRaises(PublicationHold): f.publish(receipt, **override)
        assert not f.refs

    def test_anchor_holds_before_write_01(self):
        self._check_test_anchor_holds_before_write(self._cases_test_anchor_holds_before_write[0])

    def test_anchor_holds_before_write_02(self):
        self._check_test_anchor_holds_before_write(self._cases_test_anchor_holds_before_write[1])

    def test_anchor_holds_before_write_03(self):
        self._check_test_anchor_holds_before_write(self._cases_test_anchor_holds_before_write[2])

    def test_anchor_holds_before_write_04(self):
        self._check_test_anchor_holds_before_write(self._cases_test_anchor_holds_before_write[3])

    def test_anchor_holds_before_write_05(self):
        self._check_test_anchor_holds_before_write(self._cases_test_anchor_holds_before_write[4])

    def test_deleted_tail_rejected(self):
        f = Fixture(); receipt = f.append(); f.rows.pop()
        with self.assertRaises((PublicationHold, JournalError)): f.publish(receipt)
        assert not f.refs

    def test_wrong_tip_rejected(self):
        f = Fixture(); receipt = f.append()
        with self.assertRaises((PublicationHold, JournalError)): f.publish(replace(receipt, tip='f'*64))
        assert not f.refs

    def test_bad_provenance_after_publication_holds_no_retry(self):
        f = Fixture(); receipt = f.append()
        with self.assertRaises(PublicationHold): f.publish(receipt, verify_publication=lambda *_: False)
        assert len(f.refs) == 1
        with self.assertRaises(PublicationHold): f.publish(receipt)
        assert len(f.refs) == 1
