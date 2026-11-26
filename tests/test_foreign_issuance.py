from dataclasses import replace
import pytest

from test_foreign_init_runtime import Scenario, PATHS
from chatgpt_operation.controller.foreign_issuance import ExistingIssuanceVerifier, IssuanceHold
from chatgpt_operation.repository.blocker_triage import BlockerSource
from chatgpt_operation.controller.journal_publication import append_enrollment, PublicationHold
from chatgpt_operation.repository.blocker_journal import GitHubIssueBlockerJournal


def adapter(s, **kw):
    args = dict(binding=s.binding, journal_issue_id=s.jb.issue_id, authority=s.authority(),
                read_history=lambda _:s.history, verify_scope=lambda _:True, verify_coverage=lambda _:True,
                read_original_blocker=lambda r:s.original_blockers[r.evidence_ref],
                verify_original_blocker=s.verify_original_blocker, paths=PATHS)
    args.update(kw)
    return ExistingIssuanceVerifier(**args)


def test_exact_batch_with_original_blocker():
    s=Scenario(); b=s.historical_blocker(BlockerSource.TOOL_SAFETY,migrate=False)
    v=adapter(s); batch=v.prepare(s.history.request)
    assert batch.registrations[1].blockers == (b,)
    assert batch.write_authorized is False
    assert v.publication_verifier(batch)(s.jb.issue_id,batch.registrations,batch.issuer_evidence) is True
    assert s.writes == 2  # existing synthetic registration fixtures only


@pytest.mark.parametrize('case',['missing_coverage','false_coverage','truthy_coverage','wrong_scope','unknown_id','never_issued','alias_loss','wrong_intent','missing_original','changed_source','unverified_original','unverified_authority','unstable_history'])
def test_hold(case):
    s=Scenario(); kwargs={}
    if case=='missing_coverage': s.history=replace(s.history,coverage_ref=None)
    elif case=='false_coverage': kwargs['verify_coverage']=lambda _:False
    elif case=='truthy_coverage': kwargs['verify_coverage']=lambda _:1
    elif case=='wrong_scope': kwargs['verify_scope']=lambda _:False
    elif case=='unknown_id': s.history=replace(s.history,original_work_id=None)
    elif case=='never_issued': s.history=replace(s.history,original_work_id=None,historical_work_ids=(),no_original_id_issued=True)
    elif case=='alias_loss': s.history=replace(s.history,historical_work_ids=('existing',))
    elif case=='wrong_intent': s.attestation=replace(s.attestation,registrations=(s.regs[0],replace(s.regs[1],intent_id='f'*64)))
    elif case in ('missing_original','changed_source','unverified_original'):
        s.historical_blocker(BlockerSource.TOOL_SAFETY,migrate=False)
        if case=='missing_original': s.original_blockers.clear()
        elif case=='changed_source': s.history=replace(s.history,blockers=(replace(s.history.blockers[0],source='CI'),))
        else: kwargs['verify_original_blocker']=lambda *_:False
    elif case=='unverified_authority': s.valid_authority=False
    elif case=='unstable_history':
        values=iter((s.history,replace(s.history,source_ref='changed')))
        kwargs['read_history']=lambda _:next(values)
    before=s.writes
    with pytest.raises(IssuanceHold): adapter(s,**kwargs).prepare(s.history.request)
    assert s.writes==before


def test_recheck_rejects_changed_batch_or_authority():
    s=Scenario(); v=adapter(s); b=v.prepare(s.history.request); verify=v.publication_verifier(b)
    assert not verify(s.jb.issue_id+1,b.registrations,b.issuer_evidence)
    assert not verify(s.jb.issue_id,b.registrations[:1],b.issuer_evidence)
    assert not verify(s.jb.issue_id,b.registrations,'wrong')
    s.valid_authority=False
    assert not verify(s.jb.issue_id,b.registrations,b.issuer_evidence)


def test_actual_append_retains_blockers_before_registration():
    s=Scenario(); s.rows=[]; s.writes=0
    b=s.historical_blocker(BlockerSource.REPOSITORY_POLICY,migrate=False)
    v=adapter(s); batch=v.prepare(s.history.request)
    receipt=append_enrollment(journal=s.fixture_journal,issue_id=s.jb.issue_id,
        registrations=batch.registrations,issuer_evidence=batch.issuer_evidence,
        verify_issuance=v.publication_verifier(batch),verify_lease=lambda:True,
        read_floor=lambda:None,verify_genesis=lambda _:True,read_head=lambda _:s.head)
    events=s.fixture_journal.read().events
    assert [e['payload']['event'] for e in events]==['REGISTERED','BLOCKED','REGISTERED']
    assert events[1]['payload']['source']=='repository_policy'
    assert events[1]['payload']['intent']==b.logical_intent_id
    assert receipt.sequence==3 and receipt.write_authorized is False


def test_actual_append_refuses_unverified_issuance_before_write():
    s=Scenario(); s.rows=[]; s.writes=0
    v=adapter(s); batch=v.prepare(s.history.request); s.valid_authority=False
    with pytest.raises(PublicationHold,match='ISSUANCE_NOT_ATTESTED'):
        append_enrollment(journal=s.fixture_journal,issue_id=s.jb.issue_id,
            registrations=batch.registrations,issuer_evidence=batch.issuer_evidence,
            verify_issuance=v.publication_verifier(batch),verify_lease=lambda:True,
            read_floor=lambda:None,verify_genesis=lambda _:True,read_head=lambda _:s.head)
    assert s.writes==0
