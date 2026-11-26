import copy
import json
from dataclasses import replace

import unittest

from chatgpt_operation.controller.central_admission_readback import (
    MARKER, CentralAdmissionReadback, CentralLedgerConfig, LedgerReadError,
)
from chatgpt_operation.controller.foreign_work_admission import (
    ForeignAdmissionBinding, ForeignWorkAdmission, AdmissionStatus,
)
from chatgpt_operation.repository.legacy_work_identity import (
    LegacyWorkScope, RecoveryRequest, HistoryEvidence, HistoricalRecord,
)

# Synthetic identities only; the live probe is separate from these tests.
CFG = CentralLedgerConfig('owner/central', 1, 44, 2, 'bot', 3, 4)
HEAD = 'a' * 40
BIND = ForeignAdmissionBinding(LegacyWorkScope('owner/consumer', 10, 20, 'bounded'),
                               888, 'main', 'b' * 40, 'bot')
REQ = RecoveryRequest(BIND.scope, HEAD)


def body(entries=None):
    if entries is None:
        entries = {'issue:888': {'work_id': 'issue:888', 'issue_number': 888,
                                'html_url': 'https://github.com/owner/central/issues/888',
                                'status': 'admitted'}}
    return MARKER + '\n~~~json\n' + json.dumps({'schema_version': 1, 'work': entries}) + '\n~~~'


class Transport:
    def __init__(self):
        self.repo = {'id': 1, 'full_name': CFG.repository}
        self.issue = {'id': 2, 'number': 44, 'url': 'https://api.github.com/repos/owner/central/issues/44', 'comments': 1}
        self.rows = [{'id': 4, 'body': body(), 'user': {'id': 3, 'login': 'bot'}}]
        self.pages = 0
        self.change = False

    def get(self, path, *, query=None):
        if path == '/repos/owner/central':
            return copy.deepcopy(self.repo)
        if path.endswith('/issues/44'):
            return copy.deepcopy(self.issue)
        if path.endswith('/issues/44/comments'):
            self.pages += 1
            result = copy.deepcopy(self.rows)
            if self.change and self.pages > 1:
                result[0]['body'] = body({})
            return result
        if path == '/repos/owner/consumer':
            return {'id': 10, 'full_name': 'owner/consumer'}
        if path.endswith('/issues/888'):
            return {'id': 20, 'number': 888, 'state': 'open', 'url': 'https://api.github.com/repos/owner/consumer/issues/888'}
        if path.endswith('/git/ref/heads/main'):
            return {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': HEAD}}
        raise AssertionError(path)


class TestCentralAdmissionReadbackTests(unittest.TestCase):
    def test_domestic_same_number_is_not_foreign_enrollment(self):
        t = Transport()
        adapter = CentralAdmissionReadback(CFG, t)
        observed = adapter.observe()
        assert observed.entries[0].work_id == 'issue:888'
        assert not observed.foreign_enrollment_attested
        assert not observed.mutation_authorized
        assert not observed.controller_execution_approved
        assert adapter.read_enrollment(BIND) is None
        assert t.pages == 4

    _cases_test_fail_closed = ['repo','issue','actor','login','comment','count','duplicate','marker',
                                         'foreign','key','duplicate_json','schema','changed','missing']

    def _check_test_fail_closed(self, failure):
        t = Transport()
        if failure == 'repo': t.repo['id'] = 99
        elif failure == 'issue': t.issue['id'] = 99
        elif failure == 'actor': t.rows[0]['user']['id'] = 99
        elif failure == 'login': t.rows[0]['user']['login'] = 'other'
        elif failure == 'comment': t.rows[0]['id'] = 99
        elif failure == 'count': t.issue['comments'] = 2
        elif failure == 'duplicate': t.rows *= 2; t.issue['comments'] = 2
        elif failure == 'marker': t.rows.append({'id': 5, 'body': body(), 'user': {'id': 3, 'login':'bot'}}); t.issue['comments'] = 2
        elif failure == 'foreign': t.rows[0]['body'] = body().replace('owner/central','owner/consumer')
        elif failure == 'key': t.rows[0]['body'] = body().replace('issue:888','foreign:888')
        elif failure == 'duplicate_json': t.rows[0]['body'] = body().replace('"schema_version": 1','"schema_version": 1, "schema_version": 1')
        elif failure == 'schema': t.rows[0]['body'] = body().replace('"schema_version": 1','"schema_version": 2')
        elif failure == 'changed': t.change = True
        elif failure == 'missing': t.rows[0]['body'] = 'no ledger'
        with self.assertRaises(LedgerReadError): CentralAdmissionReadback(CFG,t).observe()

    def test_fail_closed_01(self):
        self._check_test_fail_closed(self._cases_test_fail_closed[0])

    def test_fail_closed_02(self):
        self._check_test_fail_closed(self._cases_test_fail_closed[1])

    def test_fail_closed_03(self):
        self._check_test_fail_closed(self._cases_test_fail_closed[2])

    def test_fail_closed_04(self):
        self._check_test_fail_closed(self._cases_test_fail_closed[3])

    def test_fail_closed_05(self):
        self._check_test_fail_closed(self._cases_test_fail_closed[4])

    def test_fail_closed_06(self):
        self._check_test_fail_closed(self._cases_test_fail_closed[5])

    def test_fail_closed_07(self):
        self._check_test_fail_closed(self._cases_test_fail_closed[6])

    def test_fail_closed_08(self):
        self._check_test_fail_closed(self._cases_test_fail_closed[7])

    def test_fail_closed_09(self):
        self._check_test_fail_closed(self._cases_test_fail_closed[8])

    def test_fail_closed_10(self):
        self._check_test_fail_closed(self._cases_test_fail_closed[9])

    def test_fail_closed_11(self):
        self._check_test_fail_closed(self._cases_test_fail_closed[10])

    def test_fail_closed_12(self):
        self._check_test_fail_closed(self._cases_test_fail_closed[11])

    def test_fail_closed_13(self):
        self._check_test_fail_closed(self._cases_test_fail_closed[12])

    def test_fail_closed_14(self):
        self._check_test_fail_closed(self._cases_test_fail_closed[13])

    def test_incomplete_pagination(self):
        t = Transport()
        t.rows = [{'id': i, 'body': 'ordinary'} for i in range(1,101)]
        t.issue['comments'] = 100
        with self.assertRaisesRegex(LedgerReadError, 'pagination'):
            CentralAdmissionReadback(replace(CFG,max_pages=1),t).observe()

    _cases_test_a52a_integration_never_admits_foreign_work = [False, True]

    def _check_test_a52a_integration_never_admits_foreign_work(self, blocker):
        t = Transport()
        reader = CentralAdmissionReadback(CFG,t)
        def history(req):
            return HistoryEvidence(req, 'scope', 'source', 'coverage', 'original', ('original',),
                (HistoricalRecord('old-denial', None, 'TOOL_SAFETY'),) if blocker else ())
        def never_verify(*args):
            raise AssertionError('no existing enrollment available to verify')
        # Test doubles for scope/coverage, not actual attestations.
        admission = ForeignWorkAdmission(binding=BIND, transport=t, history_reader=history,
            verify_scope=lambda e: True, verify_coverage=lambda e: True,
            read_enrollment=reader.read_enrollment, verify_enrollment=never_verify)
        result = admission.observe(REQ)
        assert result.status is (AdmissionStatus.BLOCKER_PRESENT if blocker else AdmissionStatus.ENROLLMENT_NOT_ATTESTED)
        assert result.work_id is None and not result.mutation_authorized and not result.controller_execution_approved
        if blocker:
            assert result.recovery.blockers[0].evidence_ref == 'old-denial'
            assert t.pages == 0

    def test_a52a_integration_never_admits_foreign_work_01(self):
        self._check_test_a52a_integration_never_admits_foreign_work(self._cases_test_a52a_integration_never_admits_foreign_work[0])

    def test_a52a_integration_never_admits_foreign_work_02(self):
        self._check_test_a52a_integration_never_admits_foreign_work(self._cases_test_a52a_integration_never_admits_foreign_work[1])
