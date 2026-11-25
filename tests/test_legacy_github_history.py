from copy import deepcopy
from dataclasses import replace
import unittest
from chatgpt_operation.repository.legacy_work_identity import (
    LegacyWorkScope, RecoveryRequest, HistoryEvidence, HistoricalRecord,
    RecoveryStatus, recover_work_identity,
)
from chatgpt_operation.repository.legacy_github_history import GitHubHistoryReader, HistoryReadError

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
    def test_complete_visible_double_read_not_complete_external_history(self):
        f=Fake(); s=reader(f).collect(REQ)
        self.assertTrue(not s.external_history_complete)
        self.assertTrue(len(f.calls)==16 and f.calls[:8]==f.calls[8:])
        self.assertTrue(s.records()['pull_requests'][0]['commits'][0]['sha']==HEAD)
        self.assertTrue(s.source_ref==reader(f).collect(REQ).source_ref)
        data=s.records(); data['issue']['id']=99
        self.assertTrue(s.records()['issue']['id']==20)

    def test_binding_and_count_mismatch(self):
        for path, key, value in [
            (ROOT,'id',11),(ROOT,'full_name','other/repo'),(I,'id',21),(I,'number',8),
            (I,'comments',2),(P,'number',9),(P,'commits',251),(P,'comments',2),
            (P,'review_comments',1),(P,'head',{'sha':'c'*40,'repo':{'id':10}}),
            (P,'base',{'sha':'b'*40,'repo':{'id':11}}),
        ]:
            with self.subTest(path=path, key=key, value=value):
                f=Fake(); f.rows[path][key]=value
                with self.assertRaises(HistoryReadError): reader(f).collect(REQ)

    def test_invalid_comment_page(self):
        for rows in [[{'id':1},{'id':1}],[{'id':True}],{'id':1}]:
            with self.subTest(rows=rows):
                f=Fake(); f.rows[I+'/comments']=rows
                with self.assertRaises(HistoryReadError): reader(f).collect(REQ)

    def test_commit_tip_mismatch(self):
        f=Fake();f.rows[P+'/commits']=[{'sha':'c'*40}]
        with self.assertRaises(HistoryReadError): reader(f).collect(REQ)

    def test_pagination_complete_and_boundary(self):
        f=Fake(); f.rows[I]['comments']=100; f.rows[I+'/comments']=[{'id':n} for n in range(1,101)]
        self.assertTrue(len(reader(f,max_pages=2).collect(REQ).records()['issue_comments'])==100)
        with self.assertRaises(HistoryReadError): reader(f,max_pages=1).collect(REQ)

    def test_changed_comment_blocks_snapshot(self):
        f=Fake()
        def moving(path,query):
            val=f(path,query)
            if path==C: f.rows[C][0]['body']='edited'
            return val
        with self.assertRaisesRegex(HistoryReadError, 'changed'): reader(moving).collect(REQ)

    def test_transport_failure_is_not_empty_history(self):
        f=Fake();del f.rows[C]
        with self.assertRaises(HistoryReadError): reader(f).collect(REQ)

    def test_invalid_inventory(self):
        for kw in [{'historical_prs':(8,)},{'historical_prs':(7,)},{'max_pages':0}]:
            with self.subTest(kw=kw):
                with self.assertRaises(ValueError): reader(Fake(),**kw)

    def test_external_coverage_stays_incomplete_even_when_verifier_true(self):
        f=Fake();r=reader(f)
        result=recover_work_identity(REQ,trusted_reader=lambda req:r.read_evidence(req,resolve=evidence),verify_scope=lambda _:True,verify_coverage=lambda _:True)
        self.assertTrue(result.status is RecoveryStatus.HISTORY_INCOMPLETE and not result.mutation_authorized)

    def test_known_blocker_preserved_without_coverage(self):
        f=Fake();r=reader(f);block=HistoricalRecord('original',None,'tool_safety')
        result=recover_work_identity(REQ,trusted_reader=lambda req:r.read_evidence(req,resolve=lambda s:evidence(s,blockers=(block,))),verify_scope=lambda _:True,verify_coverage=lambda _:False)
        self.assertTrue(result.status is RecoveryStatus.BLOCKER_PRESENT and result.blockers==(block,))

    def test_unbound_resolver_rejected(self):
        with self.assertRaises(HistoryReadError): reader(Fake()).read_evidence(REQ,resolve=lambda s:evidence(s,source_ref='different'))

    def test_old_id_is_not_inferred_from_comment_text(self):
        f=Fake();f.rows[C][0]['body']='work_id: arbitrary; no_original_id_issued: true'
        r=reader(f);e=r.read_evidence(REQ,resolve=evidence)
        self.assertTrue(e.original_work_id is None and not e.no_original_id_issued)

    def test_snapshot_digest_binds_work_anchor(self):
        f=Fake();r=reader(f)
        self.assertTrue(r.collect(REQ).source_ref!=r.collect(replace(REQ,scope=replace(REQ.scope,work_anchor='other'))).source_ref)

