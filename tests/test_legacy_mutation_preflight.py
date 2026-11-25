from dataclasses import replace
import unittest
from chatgpt_operation.repository.legacy_work_identity import (
    LegacyWorkScope, RecoveryRequest, HistoryEvidence, HistoricalRecord, RecoveryStatus,
)
from chatgpt_operation.repository.legacy_mutation_preflight import HistoryDisposition, observe_history, observe_github_history

SCOPE = LegacyWorkScope('example/repo', 10, 20, 'trusted-work-package-1')
REQUEST = RecoveryRequest(SCOPE, 'a'*40)
BASE = HistoryEvidence(REQUEST, 'scope-proof', 'source', 'coverage-proof', 'old-1', ('old-1', 'old-2'), ())



def fail(_):
    raise OSError('unavailable')

from copy import deepcopy
from chatgpt_operation.repository.legacy_github_history import GitHubHistoryReader

ROOT = '/repos/example/repo'
HEAD = 'a'*40
REQ = RecoveryRequest(LegacyWorkScope('example/repo', 10, 20, 'anchor'), HEAD)
P = ROOT + '/pulls/8'
I = ROOT + '/issues/7'
C = ROOT + '/issues/8/comments'

class Fake:
    def __init__(self):
        self.rows = {ROOT:{'id':10,'full_name':'example/repo'}, I:{'id':20,'number':7,'comments':1},
            I+'/comments':[{'id':1,'body':'work evidence'}],
            P:{'id':80,'number':8,'head':{'sha':HEAD,'repo':{'id':10}},
               'base':{'sha':'b'*40,'repo':{'id':10}},'commits':1,'comments':1,'review_comments':0},
            P+'/commits':[{'sha':HEAD,'commit':{'message':'change'}}],
            C:[{'id':2,'body':'not authoritative'}], P+'/comments':[], P+'/reviews':[]}
        self.calls = []
    def __call__(self,path,query):
        self.calls.append((path,query))
        val = deepcopy(self.rows[path])
        return val[(query['page']-1)*100:query['page']*100] if isinstance(val,list) else val

def reader(f, **kwargs):
    return GitHubHistoryReader(f,issue_number=7,target_pr=8,**kwargs)

def evidence(snapshot, **kwargs):
    data = dict(request=REQ, scope_ref='verified-scope', source_ref=snapshot.source_ref,
                coverage_ref=None, original_work_id=None,historical_work_ids=(),blockers=())
    data.update(kwargs)
    return HistoryEvidence(**data)



class LegacyTests(unittest.TestCase):
    def test_dispositions(self):
        for evidence, scope, coverage, expected in [
            (BASE, True, True, HistoryDisposition.CONTINUE_ORDINARY_PREFLIGHT),
            (BASE, False, True, HistoryDisposition.RESTORE_IDENTITY),
            (BASE, True, False, HistoryDisposition.RESTORE_COVERAGE),
            (replace(BASE, original_work_id=None, historical_work_ids=()), True, True, HistoryDisposition.RESTORE_IDENTITY),
            (replace(BASE, coverage_ref=None), True, True, HistoryDisposition.RESTORE_COVERAGE),
        ]:
            with self.subTest(evidence=evidence, scope=scope, coverage=coverage, expected=expected):
                r = observe_history(REQUEST, reader=lambda _: evidence,
                                    verify_scope=lambda _: scope, verify_coverage=lambda _: coverage)
                self.assertTrue(r.disposition is expected)
                self.assertTrue(not r.mutation_authorized)
                self.assertTrue(not r.recovery.mutation_authorized)

    def test_existing_gate_preserves_records(self):
        for source in ['tool_safety', 'repository_policy', 'github_http', 'unknown']:
            with self.subTest(source=source):
                b = HistoricalRecord('original-ref', 'f'*64, source)
                r = observe_history(REQUEST, reader=lambda _: replace(BASE, blockers=(b,), coverage_ref=None),
                                    verify_scope=lambda _: True, verify_coverage=fail)
                self.assertTrue(r.disposition is HistoryDisposition.EXISTING_BLOCKER_GATE)
                self.assertTrue(r.recovery.blockers == (b,))
                self.assertTrue(not r.mutation_authorized)

    def test_transport_error_is_missing_identity_not_denial(self):
        r = observe_history(REQUEST, reader=fail, verify_scope=lambda _: True, verify_coverage=lambda _: True)
        self.assertTrue(r.disposition is HistoryDisposition.RESTORE_IDENTITY)
        self.assertTrue(not r.recovery.blockers)

    def test_github_bridge_requires_external_coverage(self):
        r = observe_github_history(REQ, reader=reader(Fake()), resolve=evidence,
                                   verify_scope=lambda _: True, verify_coverage=lambda _: True)
        self.assertTrue(r.disposition is HistoryDisposition.RESTORE_COVERAGE)

    def test_github_bridge_preserves_denial(self):
        b = HistoricalRecord('original-ref', None, 'tool_safety')
        r = observe_github_history(REQ, reader=reader(Fake()),
                                   resolve=lambda s: evidence(s, blockers=(b,)),
                                   verify_scope=lambda _: True, verify_coverage=fail)
        self.assertTrue(r.disposition is HistoryDisposition.EXISTING_BLOCKER_GATE)
        self.assertTrue(r.recovery.blockers == (b,))

