"""Standard-library tests; synthetic GitHub transport, no production writes."""
import base64
from dataclasses import replace
from hashlib import sha1
import unittest

from chatgpt_operation.controller.foreign_work_issuer import (
    ProtectedIssuanceStore, FirstIssuance, issue_first, issuance_ref, FILENAME,
)
from chatgpt_operation.controller.foreign_issuance import IssuanceHold
from chatgpt_operation.controller.foreign_enrollment_contract import EnrollmentError
from chatgpt_operation.repository.legacy_work_identity import HistoricalRecord

ROOT = '/repos/example/samuel'
TREE, COMMIT = 'a' * 40, 'b' * 40


class GitObjects:
    def __init__(self):
        self.refs, self.objects, self.writes = {}, {}, []
        self.bad_tree = False
        self.lose_ack = False

    def get(self, path):
        if path == ROOT:
            return {'id': 21, 'full_name': 'example/samuel'}
        if path.startswith(ROOT + '/git/matching-refs/'):
            prefix = 'refs/' + path.split('/git/matching-refs/')[1]
            return [{'ref': ref, 'object': {'type': 'commit', 'sha': sha}}
                    for ref, sha in self.refs.items() if ref.startswith(prefix)]
        return self.objects[path]

    def post(self, path, payload):
        self.writes.append(path)
        if path == ROOT + '/git/blobs':
            raw = base64.b64decode(payload['content'])
            digest = sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
            self.objects[path + '/' + digest] = {
                'sha': digest, 'encoding': 'base64', 'size': len(raw), 'content': payload['content']}
            return {'sha': digest}
        if path == ROOT + '/git/trees':
            entries = payload['tree']
            if self.bad_tree:
                entries = entries + [{'path': 'extra'}]
            self.objects[path + '/' + TREE] = {'sha': TREE, 'tree': entries, 'truncated': False}
            return {'sha': TREE}
        if path == ROOT + '/git/commits':
            self.objects[path + '/' + COMMIT] = {
                'sha': COMMIT, 'tree': {'sha': payload['tree']}, 'parents': payload['parents']}
            return {'sha': COMMIT}
        if path == ROOT + '/git/refs':
            if payload['ref'] in self.refs:
                raise RuntimeError('ref exists')
            self.refs[payload['ref']] = payload['sha']
            if self.lose_ack:
                raise RuntimeError('publication acknowledgement lost')
            return {'ref': payload['ref'], 'object': {'sha': payload['sha']}}
        raise AssertionError(path)


class TestForeignWorkIssuer(unittest.TestCase):
    def setUp(self):
        from test_foreign_init_runtime import Scenario, PATHS
        self.s = Scenario()
        self.paths = PATHS
        self.evidence = replace(self.s.history, original_work_id=None,
                                historical_work_ids=(), no_original_id_issued=True)
        self.transport = GitObjects()
        self.store = ProtectedIssuanceStore(repository='example/samuel',
                                            repository_id=21, transport=self.transport)
        self.args = dict(binding=self.s.binding, request=self.evidence.request,
                         store=self.store, paths=self.paths, approval_ref='owner-proof',
                         publisher_ref='run-proof', read_history=lambda _: self.evidence,
                         verify_scope=lambda _: True, verify_coverage=lambda _: True,
                         verify_approval=lambda *_: True, verify_lease=lambda: True,
                         verify_ruleset=lambda: True, read_head=lambda: self.s.head,
                         verify_publication=lambda *_: True)

    def issue(self, **changes):
        return issue_first(**dict(self.args, **changes))

    def test_create_once_and_existing_authority_readback(self):
        record, commit = self.issue()
        self.assertEqual(commit, COMMIT)
        self.assertEqual(len(self.transport.writes), 4)
        self.assertEqual(record.ref, issuance_ref(self.s.scope))
        self.assertFalse(record.payload(self.paths)['work_enrolled'])
        authority = self.store.authority(paths=self.paths, verify_publication=lambda *_: True,
                                         verify_current_authority=lambda *_: True)
        self.assertEqual(authority.observe(self.s.binding), record.attestation(self.paths))
        self.assertEqual(authority.observe(self.s.binding).record.work_id, self.s.scope.legacy_work_id())

    def test_ref_stable_on_rename(self):
        self.assertEqual(issuance_ref(self.s.scope),
                         issuance_ref(replace(self.s.scope, repository='example/renamed')))

    def test_original_id_cannot_be_replaced(self):
        self.evidence = self.s.history
        with self.assertRaises(IssuanceHold):
            self.issue()
        self.assertEqual(self.transport.writes, [])

    def test_unknown_original_is_not_never_issued(self):
        self.evidence = replace(self.evidence, no_original_id_issued=False)
        with self.assertRaises(IssuanceHold):
            self.issue()
        self.assertEqual(self.transport.writes, [])

    def test_known_blocker_prevents_first_issuance(self):
        self.evidence = replace(self.evidence, blockers=(HistoricalRecord('original', None, 'TOOL_SAFETY'),))
        with self.assertRaises(IssuanceHold):
            self.issue()
        self.assertEqual(self.transport.writes, [])

    def test_missing_coverage_ref(self):
        self.evidence = replace(self.evidence, coverage_ref=None)
        with self.assertRaises(IssuanceHold):
            self.issue()
        self.assertEqual(self.transport.writes, [])

    def test_failed_trust_ports(self):
        for port in ('verify_scope', 'verify_coverage', 'verify_approval', 'verify_lease', 'verify_ruleset'):
            with self.subTest(port=port), self.assertRaises(IssuanceHold):
                self.issue(**{port: lambda *_: False})
        self.assertEqual(self.transport.writes, [])

    def test_truthy_approval_rejected(self):
        with self.assertRaises(IssuanceHold):
            self.issue(verify_approval=lambda *_: 1)
        self.assertEqual(self.transport.writes, [])

    def test_stale_head(self):
        with self.assertRaises(IssuanceHold):
            self.issue(read_head=lambda: 'c' * 40)
        self.assertEqual(self.transport.writes, [])

    def test_scope_history_changed_before_publication(self):
        def read(_):
            return self.evidence if not self.transport.writes else replace(self.evidence, source_ref='changed')
        with self.assertRaises(IssuanceHold):
            self.issue(read_history=read)
        self.assertEqual(len(self.transport.writes), 1)
        self.assertEqual(self.transport.refs, {})

    def test_corrupt_tree_never_creates_ref(self):
        self.transport.bad_tree = True
        with self.assertRaises(IssuanceHold):
            self.issue()
        self.assertEqual(self.transport.refs, {})

    def test_existing_ref_never_overwritten(self):
        self.issue()
        with self.assertRaises(IssuanceHold):
            self.issue()
        self.assertEqual(len(self.transport.writes), 4)

    def test_unknown_publication_reconciles_without_retry(self):
        self.transport.lose_ack = True
        with self.assertRaises(RuntimeError):
            self.issue()
        self.assertIsNotNone(self.store.read(issuance_ref(self.s.scope)))
        with self.assertRaises(IssuanceHold):
            self.issue()
        self.assertEqual(len(self.transport.writes), 4)

    def test_published_but_provenance_refused(self):
        with self.assertRaises(IssuanceHold):
            self.issue(verify_publication=lambda *_: False)
        self.assertEqual(len(self.transport.writes), 4)
        with self.assertRaises(IssuanceHold):
            self.store.read_attestation(self.s.binding, self.paths, lambda *_: False)

    def test_revoked_authority_rejected(self):
        self.issue()
        authority = self.store.authority(paths=self.paths, verify_publication=lambda *_: True,
                                         verify_current_authority=lambda *_: False)
        with self.assertRaises(EnrollmentError):
            authority.observe(self.s.binding)

    def test_mismatched_binding_rejected(self):
        self.issue()
        with self.assertRaises(IssuanceHold):
            self.store.read_attestation(replace(self.s.binding, issuer_id='other'), self.paths, lambda *_: True)

    def test_after_publication_history_can_reflect_issued_identity(self):
        def read(_):
            return self.s.history if self.transport.refs else self.evidence
        record, _ = self.issue(read_history=read)
        self.assertEqual(record.ref, issuance_ref(self.s.scope))

    def test_blob_tamper_rejected(self):
        self.issue()
        for path, obj in self.transport.objects.items():
            if '/git/blobs/' in path:
                obj['content'] = base64.b64encode(b'{}').decode()
        with self.assertRaises(IssuanceHold):
            self.store.read(issuance_ref(self.s.scope))
