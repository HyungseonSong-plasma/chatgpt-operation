"""Synthetic trust sources, actual Samuel recovery, journal and gate implementations."""
from dataclasses import replace
import json
import unittest
from chatgpt_operation.controller.foreign_work_admission import ForeignAdmissionBinding, EnrollmentRecord, AdmissionStatus
from chatgpt_operation.controller.foreign_enrollment_contract import (
    ForeignEnrollmentAuthority, ForeignEnrollmentAttestation, IntentRegistration, EnrollmentError,
)
from chatgpt_operation.controller.foreign_anchored_journal import (
    JournalBinding, AnchorAttestation, AnchoredForeignJournal, JournalBindingError,
)
from chatgpt_operation.controller.foreign_init_runtime import ForeignInitRuntime
from chatgpt_operation.repository.legacy_work_identity import LegacyWorkScope, RecoveryRequest, HistoryEvidence, HistoricalRecord
from chatgpt_operation.repository.blocker_triage import logical_intent_id, BlockerObservation, BlockerSource
from chatgpt_operation.repository.blocker_resolution import ClearanceEvidence, ClearanceKind
from chatgpt_operation.repository.blocker_journal import GitHubIssueBlockerJournal
from chatgpt_operation.repository.blocker_checkpoint import JournalCheckpoint

HEAD, PIN = 'a'*40, 'b'*40
PATHS = ('docs/example.md',)


class Scenario:
    def __init__(self):
        self.scope=LegacyWorkScope('example/moose',11,12,'bounded-scope')
        self.binding=ForeignAdmissionBinding(self.scope,888,'issue-888/runtime',PIN,'issuer-fixture')
        self.jb=JournalBinding('example/samuel',21,44,22,'fixture-bot',23,'journal-fixture','anchor-fixture')
        self.record=EnrollmentRecord(self.scope,'existing',('existing','old'),self.binding.issuer_id,'reg:1')
        self.regs=tuple(IntentRegistration(repo,w,logical_intent_id(repository=repo,branch=self.binding.target_branch,work_id=w,paths=PATHS),ref)
                        for repo,w,ref in ((self.scope.repository,'existing','reg:1'),('example/old-moose','old','reg:2')))
        self.attestation=ForeignEnrollmentAttestation(self.record,PIN,5,'fixture-authority',self.regs)
        self.rows=[]; self.head=HEAD; self.writes=0; self.valid_authority=True; self.valid_anchor=True
        self.technical=False; self.authority_clear=False; self.mutate=lambda path,x:x
        self.original_blockers = {}
        # Fixture only: populate real journal implementation in-memory; production read path never writes.
        self.fixture_journal=GitHubIssueBlockerJournal(self,issue_number=44,trusted_actor=self.jb.actor_login)
        for r in self.regs:
            self.fixture_journal.register_work(logical_intent_id=r.intent_id,exact_head_sha=HEAD,evidence_ref=r.registration_ref)
        self.floor=self.checkpoint(); self.anchor=AnchorAttestation(self.jb,self.floor,self.jb.anchor_boundary,'fixture-anchor-proof')
        self.request_data={'repository':self.scope.repository,'target_branch':self.binding.target_branch,'target_sha':HEAD,'work_id':'existing'}
        self.history=HistoryEvidence(RecoveryRequest(self.scope,HEAD),'scope','source','coverage','existing',self.record.historical_work_ids,())

    def checkpoint(self):
        s=self.fixture_journal.read(); return JournalCheckpoint(len(s.events),s.tip,'anchor:fixture')
    def refresh_anchor(self):
        self.anchor=replace(self.anchor,checkpoint=self.checkpoint())
    def get(self,path,*,query=None):
        if path in ('/issues/44/comments','/repos/example/samuel/issues/44/comments'):
            page=int((query or {}).get('page','1')); result=[dict(x,user=dict(x['user'])) for x in self.rows[(page-1)*100:page*100]]
        elif path=='/repos/example/samuel': result={'id':21,'full_name':'example/samuel'}
        elif path=='/repos/example/samuel/issues/44': result={'id':22,'number':44,'url':'https://api.github.com'+path,'comments':len(self.rows)}
        elif path=='/repos/example/moose': result={'id':11,'full_name':'example/moose'}
        elif path=='/repos/example/moose/issues/888': result={'id':12,'number':888,'url':'https://api.github.com'+path,'state':'open'}
        elif path=='/repos/example/moose/git/ref/heads/issue-888/runtime': result={'ref':'refs/heads/issue-888/runtime','object':{'type':'commit','sha':self.head}}
        else: raise AssertionError(path)
        return self.mutate(path,result)
    def request_write(self,method,path,*,payload=None):
        assert method=='POST' and path=='/issues/44/comments'; self.writes+=1
        r={'id':len(self.rows)+100,'body':payload['body'],'user':{'login':self.jb.actor_login,'id':self.jb.actor_id}}
        self.rows.append(r);return {'id':r['id']}
    # Journal protocol needs request(), while request data is held separately.
    def request(self,*a,**kw): return self.request_write(*a,**kw)
    def authority(self,**kwargs):
        return ForeignEnrollmentAuthority(read=kwargs.get('read',lambda _:self.attestation),verify_authority=kwargs.get('verify',lambda *_:self.valid_authority),minimum_generation=kwargs.get('floor',5))
    def journal(self,**kwargs):
        return AnchoredForeignJournal(binding=self.jb,transport=self,read_anchor=kwargs.get('read',lambda _:self.anchor),verify_anchor=kwargs.get('verify',lambda *_:self.valid_anchor),durable_floor=kwargs.get('floor',self.floor),technical_verifier=lambda _:self.technical,authority_verifier=lambda _:self.authority_clear,read_head=lambda:self.head,
                                      verify_historical_blocker=kwargs.get('verify_history', self.verify_original_blocker))
    def runtime(self,**kwargs):
        return ForeignInitRuntime(binding=self.binding,authority=kwargs.get('authority',self.authority()),journal=kwargs.get('journal',self.journal()),transport=self,history_reader=lambda _:self.history,verify_scope=lambda _:True,verify_coverage=kwargs.get('verify_coverage', lambda _:True),paths=PATHS)
    def blocker(self,source=BlockerSource.CI):
        self.fixture_journal.record_blocker(BlockerObservation(source,self.regs[1].intent_id,'fixture','original-denial'));self.refresh_anchor()
    def verify_original_blocker(self, original, typed):
        return self.original_blockers.get(original.evidence_ref) == typed
    def historical_blocker(self, source=BlockerSource.CI, *, http_status=None, migrate=True):
        typed=BlockerObservation(source,self.regs[1].intent_id,'original-provider','historical-denial',http_status)
        self.original_blockers[typed.evidence_ref]=typed
        original=HistoricalRecord(typed.evidence_ref,typed.logical_intent_id,source.name)
        self.history=replace(self.history,blockers=(original,))
        if migrate:
            self.fixture_journal.record_blocker(typed)
            self.refresh_anchor()
        return typed
    def clearance(self, typed, kind=ClearanceKind.EXACT_HEAD_CI_PASS, *, head=HEAD):
        self.fixture_journal.record_clearance(ClearanceEvidence(typed.logical_intent_id,typed.evidence_ref,kind,head,'clearance-proof'))
        self.refresh_anchor()


class TestForeignInitRuntimeTests(unittest.TestCase):
    def test_existing_enrollment(self):
        s=Scenario(); assert s.authority().observe(s.binding)==s.attestation

    _cases_test_enrollment_refusal = ['missing','wrong_pin','wrong_issuer','wrong_scope','stale','false','truthy','unstable']

    def _check_test_enrollment_refusal(self, case):
        s=Scenario(); a=s.attestation; read=lambda _:s.attestation; verify=lambda *_:True
        if case=='missing': read=lambda _:None
        if case=='wrong_pin': s.attestation=replace(a,central_revision='c'*40)
        if case=='wrong_issuer': s.attestation=replace(a,record=replace(a.record,issuer_id='other'))
        if case=='wrong_scope': s.attestation=replace(a,record=replace(a.record,scope=replace(a.record.scope,issue_id=999)))
        if case=='stale': s.attestation=replace(a,generation=4)
        if case=='false': verify=lambda *_:False
        if case=='truthy': verify=lambda *_:1
        if case=='unstable':
            values=iter((a,replace(a,generation=6)));read=lambda _:next(values)
        with self.assertRaises(EnrollmentError): s.authority(read=read,verify=verify).observe(s.binding)

    def test_enrollment_refusal_01(self):
        self._check_test_enrollment_refusal(self._cases_test_enrollment_refusal[0])

    def test_enrollment_refusal_02(self):
        self._check_test_enrollment_refusal(self._cases_test_enrollment_refusal[1])

    def test_enrollment_refusal_03(self):
        self._check_test_enrollment_refusal(self._cases_test_enrollment_refusal[2])

    def test_enrollment_refusal_04(self):
        self._check_test_enrollment_refusal(self._cases_test_enrollment_refusal[3])

    def test_enrollment_refusal_05(self):
        self._check_test_enrollment_refusal(self._cases_test_enrollment_refusal[4])

    def test_enrollment_refusal_06(self):
        self._check_test_enrollment_refusal(self._cases_test_enrollment_refusal[5])

    def test_enrollment_refusal_07(self):
        self._check_test_enrollment_refusal(self._cases_test_enrollment_refusal[6])

    def test_enrollment_refusal_08(self):
        self._check_test_enrollment_refusal(self._cases_test_enrollment_refusal[7])

    _cases_test_attestation_coverage = ['missing_alias','duplicate_intent','canonical_ref']

    def _check_test_attestation_coverage(self, case):
        s=Scenario(); r=s.regs
        if case=='missing_alias': r=r[:1]
        if case=='duplicate_intent': r=(r[0],replace(r[1],intent_id=r[0].intent_id))
        if case=='canonical_ref': r=(replace(r[0],registration_ref='wrong'),r[1])
        with self.assertRaises(EnrollmentError): replace(s.attestation,registrations=r)

    def test_attestation_coverage_01(self):
        self._check_test_attestation_coverage(self._cases_test_attestation_coverage[0])

    def test_attestation_coverage_02(self):
        self._check_test_attestation_coverage(self._cases_test_attestation_coverage[1])

    def test_attestation_coverage_03(self):
        self._check_test_attestation_coverage(self._cases_test_attestation_coverage[2])

    def test_anchored_gate_checks_all_aliases_without_write(self):
        s=Scenario(); before=s.writes; j=s.journal(); result=j.observe(s.attestation,branch=s.binding.target_branch,paths=PATHS,head=HEAD)
        assert result.endswith(s.anchor.checkpoint.tip) and s.writes==before

    _cases_test_journal_fail_closed = ['absent','unauthenticated','truthy','wrong_boundary','tail_deleted','stale_anchor','rollback','wrong_actor','wrong_issue','wrong_repo','wrong_registration','wrong_intent','stale_head','changed_anchor','read_only']

    def _check_test_journal_fail_closed(self, case):
        s=Scenario(); a=s.attestation; kw={}; before=s.writes
        if case=='absent': kw['read']=lambda _:None
        if case=='unauthenticated': s.valid_anchor=False
        if case=='truthy': kw['verify']=lambda *_:1
        if case=='wrong_boundary':
            with self.assertRaises(JournalBindingError): replace(s.jb,anchor_boundary=s.jb.journal_boundary)
            return
        if case=='tail_deleted': s.rows.pop()
        if case=='stale_anchor':
            s.fixture_journal.record_blocker(BlockerObservation(BlockerSource.CI,s.regs[1].intent_id,'fixture','extra'))
        if case=='rollback': kw['floor']=replace(s.floor,tip='f'*64)
        if case=='wrong_actor': s.rows[0]['user']['id']=999
        if case=='wrong_issue': s.mutate=lambda p,x:dict(x,id=99) if p.endswith('/issues/44') else x
        if case=='wrong_repo': s.mutate=lambda p,x:dict(x,id=99) if p=='/repos/example/samuel' else x
        if case=='wrong_registration': a=replace(a,registrations=(a.registrations[0],replace(a.registrations[1],registration_ref='unrelated')))
        if case=='wrong_intent': a=replace(a,registrations=(a.registrations[0],replace(a.registrations[1],intent_id='f'*64)))
        if case=='stale_head': s.head='c'*40
        if case=='changed_anchor':
            values=iter((s.anchor,replace(s.anchor,authority_ref='changed')));kw['read']=lambda _:next(values)
        j=s.journal(**kw)
        if case=='read_only':
            with self.assertRaises(JournalBindingError): j._transport.request('POST','/issues/44/comments',payload={})
            assert s.writes==before; return
        with self.assertRaises((ValueError,RuntimeError)): j.observe(a,branch=s.binding.target_branch,paths=PATHS,head=HEAD)
        assert s.writes==before+(case=='stale_anchor')

    def test_journal_fail_closed_01(self):
        self._check_test_journal_fail_closed(self._cases_test_journal_fail_closed[0])

    def test_journal_fail_closed_02(self):
        self._check_test_journal_fail_closed(self._cases_test_journal_fail_closed[1])

    def test_journal_fail_closed_03(self):
        self._check_test_journal_fail_closed(self._cases_test_journal_fail_closed[2])

    def test_journal_fail_closed_04(self):
        self._check_test_journal_fail_closed(self._cases_test_journal_fail_closed[3])

    def test_journal_fail_closed_05(self):
        self._check_test_journal_fail_closed(self._cases_test_journal_fail_closed[4])

    def test_journal_fail_closed_06(self):
        self._check_test_journal_fail_closed(self._cases_test_journal_fail_closed[5])

    def test_journal_fail_closed_07(self):
        self._check_test_journal_fail_closed(self._cases_test_journal_fail_closed[6])

    def test_journal_fail_closed_08(self):
        self._check_test_journal_fail_closed(self._cases_test_journal_fail_closed[7])

    def test_journal_fail_closed_09(self):
        self._check_test_journal_fail_closed(self._cases_test_journal_fail_closed[8])

    def test_journal_fail_closed_10(self):
        self._check_test_journal_fail_closed(self._cases_test_journal_fail_closed[9])

    def test_journal_fail_closed_11(self):
        self._check_test_journal_fail_closed(self._cases_test_journal_fail_closed[10])

    def test_journal_fail_closed_12(self):
        self._check_test_journal_fail_closed(self._cases_test_journal_fail_closed[11])

    def test_journal_fail_closed_13(self):
        self._check_test_journal_fail_closed(self._cases_test_journal_fail_closed[12])

    def test_journal_fail_closed_14(self):
        self._check_test_journal_fail_closed(self._cases_test_journal_fail_closed[13])

    def test_journal_fail_closed_15(self):
        self._check_test_journal_fail_closed(self._cases_test_journal_fail_closed[14])

    _cases_test_alias_blocker_not_discarded = [BlockerSource.CI,BlockerSource.TOOL_SAFETY,BlockerSource.REPOSITORY_POLICY]

    def _check_test_alias_blocker_not_discarded(self, source):
        s=Scenario();s.blocker(source)
        with self.assertRaisesRegex(RuntimeError, 'ACTIVE_BLOCKER'):s.journal().observe(s.attestation,branch=s.binding.target_branch,paths=PATHS,head=HEAD)

    def test_alias_blocker_not_discarded_01(self):
        self._check_test_alias_blocker_not_discarded(self._cases_test_alias_blocker_not_discarded[0])

    def test_alias_blocker_not_discarded_02(self):
        self._check_test_alias_blocker_not_discarded(self._cases_test_alias_blocker_not_discarded[1])

    def test_alias_blocker_not_discarded_03(self):
        self._check_test_alias_blocker_not_discarded(self._cases_test_alias_blocker_not_discarded[2])

    def test_verified_ci_clearance_reuses_actual_gate(self):
        s=Scenario();s.blocker();s.fixture_journal.record_clearance(ClearanceEvidence(s.regs[1].intent_id,'original-denial',ClearanceKind.EXACT_HEAD_CI_PASS,HEAD,'ci-proof'));s.refresh_anchor()
        with self.assertRaises(RuntimeError):s.journal().observe(s.attestation,branch=s.binding.target_branch,paths=PATHS,head=HEAD)
        s.technical=True
        assert s.journal().observe(s.attestation,branch=s.binding.target_branch,paths=PATHS,head=HEAD).endswith(s.anchor.checkpoint.tip)

    def test_runtime_composition(self):
        s=Scenario();r=s.runtime();a=r.observe_enrollment(s.request_data);assert a.attestation==s.attestation
        assert r.observe_blockers(s.request_data,a).startswith('journal:')

    _cases_test_runtime_refuses_unresolved_history = ['wrong_work','wrong_branch','historical_blocker','incomplete_history','enrollment_changed']

    def _check_test_runtime_refuses_unresolved_history(self, case):
        s=Scenario();r=s.runtime();q=dict(s.request_data);a=r.observe_enrollment(q)
        if case=='wrong_work':q['work_id']='replacement'
        if case=='wrong_branch':q['target_branch']='other'
        if case=='historical_blocker':s.history=replace(s.history,blockers=(HistoricalRecord('old-denial',s.regs[1].intent_id,'TOOL_SAFETY'),))
        if case=='incomplete_history':s.history=replace(s.history,coverage_ref=None)
        if case=='enrollment_changed':s.attestation=replace(a.attestation,generation=6)
        with self.assertRaises(ValueError):r.observe_blockers(q,a)

    def test_runtime_refuses_unresolved_history_01(self):
        self._check_test_runtime_refuses_unresolved_history(self._cases_test_runtime_refuses_unresolved_history[0])

    def test_runtime_refuses_unresolved_history_02(self):
        self._check_test_runtime_refuses_unresolved_history(self._cases_test_runtime_refuses_unresolved_history[1])

    def test_runtime_refuses_unresolved_history_03(self):
        self._check_test_runtime_refuses_unresolved_history(self._cases_test_runtime_refuses_unresolved_history[2])

    def test_runtime_refuses_unresolved_history_04(self):
        self._check_test_runtime_refuses_unresolved_history(self._cases_test_runtime_refuses_unresolved_history[3])

    def test_runtime_refuses_unresolved_history_05(self):
        self._check_test_runtime_refuses_unresolved_history(self._cases_test_runtime_refuses_unresolved_history[4])

    def test_historical_ci_clearance_reaches_existing_gate(self):
        s=Scenario(); typed=s.historical_blocker(); s.clearance(typed); s.technical=True
        r=s.runtime(); a=r.observe_enrollment(s.request_data); before=s.writes
        self.assertIs(a.admission.status, AdmissionStatus.ENROLLMENT_OBSERVED_BLOCKER_CHECK_REQUIRED)
        self.assertIsNone(a.admission.work_id)
        self.assertFalse(a.admission.mutation_authorized)
        self.assertFalse(a.admission.controller_execution_approved)
        self.assertEqual(a.admission.recovery.blockers, s.history.blockers)
        self.assertTrue(r.observe_blockers(s.request_data,a).endswith(s.anchor.checkpoint.tip))
        self.assertEqual(s.writes,before)
        events=[e['payload']['event'] for e in s.fixture_journal.read().matching(typed.logical_intent_id)]
        self.assertEqual(events,['REGISTERED','BLOCKED','CLEARED'])

    def test_historical_active_ci_still_blocks(self):
        s=Scenario(); s.historical_blocker(); s.technical=True; r=s.runtime()
        a=r.observe_enrollment(s.request_data); before=s.writes
        with self.assertRaisesRegex(RuntimeError,'ACTIVE_BLOCKER_CI'):
            r.observe_blockers(s.request_data,a)
        self.assertEqual(s.writes,before)

    def test_historical_unverified_ci_clearance_still_blocks(self):
        s=Scenario(); typed=s.historical_blocker(); s.clearance(typed); r=s.runtime()
        a=r.observe_enrollment(s.request_data)
        with self.assertRaisesRegex(RuntimeError,'ACTIVE_BLOCKER_CI'):
            r.observe_blockers(s.request_data,a)

    def test_historical_stale_clearance_still_blocks(self):
        s=Scenario(); typed=s.historical_blocker(); s.clearance(typed,head='c'*40); s.technical=True; r=s.runtime()
        a=r.observe_enrollment(s.request_data)
        with self.assertRaisesRegex(RuntimeError,'ACTIVE_BLOCKER_CI'):
            r.observe_blockers(s.request_data,a)

    def test_historical_safety_cannot_use_technical_clearance(self):
        s=Scenario(); typed=s.historical_blocker(BlockerSource.TOOL_SAFETY); s.clearance(typed); s.technical=True; s.authority_clear=True
        r=s.runtime(); a=r.observe_enrollment(s.request_data)
        with self.assertRaisesRegex(RuntimeError,'ACTIVE_BLOCKER_TOOL_SAFETY'):
            r.observe_blockers(s.request_data,a)

    def test_historical_safety_requires_original_authority(self):
        s=Scenario(); typed=s.historical_blocker(BlockerSource.TOOL_SAFETY)
        s.clearance(typed,ClearanceKind.UPSTREAM_SAFETY_CLEARED); s.technical=True
        r=s.runtime(); a=r.observe_enrollment(s.request_data)
        with self.assertRaisesRegex(RuntimeError,'ACTIVE_BLOCKER_TOOL_SAFETY'):
            r.observe_blockers(s.request_data,a)
        # Synthetic originating-authority verification, not actual clearance.
        s.authority_clear=True
        self.assertTrue(r.observe_blockers(s.request_data,a).endswith(s.anchor.checkpoint.tip))

    def test_historical_policy_requires_owner_authority(self):
        s=Scenario(); typed=s.historical_blocker(BlockerSource.REPOSITORY_POLICY)
        s.clearance(typed,ClearanceKind.OWNER_POLICY_AUTHORIZED); s.technical=True
        r=s.runtime(); a=r.observe_enrollment(s.request_data)
        with self.assertRaisesRegex(RuntimeError,'ACTIVE_BLOCKER_REPOSITORY_POLICY'):
            r.observe_blockers(s.request_data,a)

    def test_historical_blocker_missing_from_anchored_journal(self):
        s=Scenario(); s.historical_blocker(migrate=False); s.technical=True
        r=s.runtime(); a=r.observe_enrollment(s.request_data)
        with self.assertRaisesRegex(JournalBindingError,'missing or ambiguous'):
            r.observe_blockers(s.request_data,a)

    def test_historical_blocker_wrong_original_intent(self):
        s=Scenario(); typed=s.historical_blocker(); s.clearance(typed); s.technical=True
        s.history=replace(s.history,blockers=(replace(s.history.blockers[0],original_intent_id=s.regs[0].intent_id),))
        r=s.runtime(); a=r.observe_enrollment(s.request_data)
        with self.assertRaisesRegex(JournalBindingError,'intent mismatch'):
            r.observe_blockers(s.request_data,a)

    def test_historical_safety_source_cannot_be_reclassified(self):
        s=Scenario(); typed=s.historical_blocker(); s.clearance(typed); s.technical=True
        s.history=replace(s.history,blockers=(replace(s.history.blockers[0],source='TOOL_SAFETY'),))
        r=s.runtime(journal=s.journal(verify_history=lambda *_:True)); a=r.observe_enrollment(s.request_data)
        with self.assertRaisesRegex(JournalBindingError,'source mismatch'):
            r.observe_blockers(s.request_data,a)

    def test_historical_duplicate_reference_across_aliases(self):
        s=Scenario(); typed=s.historical_blocker(); s.clearance(typed); s.technical=True
        s.fixture_journal.record_blocker(replace(typed,logical_intent_id=s.regs[0].intent_id)); s.refresh_anchor()
        r=s.runtime(); a=r.observe_enrollment(s.request_data)
        with self.assertRaisesRegex(JournalBindingError,'missing or ambiguous'):
            r.observe_blockers(s.request_data,a)

    def test_historical_provider_and_http_status_authenticated(self):
        s=Scenario(); typed=s.historical_blocker(BlockerSource.GITHUB_HTTP,http_status=403,migrate=False)
        # A fabricated transient error cannot replace the original access denial.
        fake=replace(typed,provider='other-provider',http_status=503)
        s.fixture_journal.record_blocker(fake); s.clearance(fake,ClearanceKind.TRANSIENT_RECOVERED); s.technical=True
        r=s.runtime(); a=r.observe_enrollment(s.request_data)
        with self.assertRaisesRegex(JournalBindingError,'not authenticated'):
            r.observe_blockers(s.request_data,a)

    def test_historical_original_proof_required(self):
        for verifier in (None,lambda *_:False,lambda *_:1):
            with self.subTest(verifier=verifier):
                s=Scenario(); typed=s.historical_blocker(); s.clearance(typed); s.technical=True
                r=s.runtime(journal=s.journal(verify_history=verifier)); a=r.observe_enrollment(s.request_data)
                with self.assertRaises(JournalBindingError): r.observe_blockers(s.request_data,a)

    def test_historical_coverage_and_original_id_still_required(self):
        for case in ('missing_coverage','false_coverage','truthy_coverage','missing_id'):
            with self.subTest(case=case):
                s=Scenario(); typed=s.historical_blocker(); s.clearance(typed); s.technical=True; kw={}
                if case=='missing_coverage': s.history=replace(s.history,coverage_ref=None)
                if case=='false_coverage': kw['verify_coverage']=lambda _:False
                if case=='truthy_coverage': kw['verify_coverage']=lambda _:1
                if case=='missing_id': s.history=replace(s.history,original_work_id=None)
                r=s.runtime(**kw)
                with self.assertRaisesRegex(ValueError,'BLOCKER_PRESENT'): r.observe_enrollment(s.request_data)

    def test_historical_evidence_cannot_disappear_between_init_checks(self):
        s=Scenario(); typed=s.historical_blocker(); s.clearance(typed); s.technical=True
        r=s.runtime(); a=r.observe_enrollment(s.request_data)
        s.history=replace(s.history,blockers=())
        with self.assertRaisesRegex(ValueError,'history changed within INIT'):
            r.observe_blockers(s.request_data,a)

    def test_historical_coverage_receipt_cannot_change_during_resolution(self):
        s=Scenario(); typed=s.historical_blocker(); s.clearance(typed); s.technical=True
        def verify(original, observed):
            s.history=replace(s.history,coverage_ref='changed')
            return s.verify_original_blocker(original,observed)
        r=s.runtime(journal=s.journal(verify_history=verify)); a=r.observe_enrollment(s.request_data)
        with self.assertRaisesRegex(ValueError,'history changed after blocker observation'):
            r.observe_blockers(s.request_data,a)
