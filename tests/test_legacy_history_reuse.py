from dataclasses import replace
import pytest
from chatgpt_operation.repository.legacy_work_identity import HistoricalRecord, RecoveryStatus
from chatgpt_operation.repository.legacy_history_reuse import HistoryVersion, VerifiedHistoryReuse, evidence_digest
from test_legacy_work_identity import BASE, REQUEST, fail

PIN = 'a'*40

class Harness:
    def __init__(self):
        self.evidence = BASE
        self.v = HistoryVersion(REQUEST, 'trusted-source', PIN, 1, evidence_digest(BASE))
        self.reads = self.probes = self.scopes = self.coverages = 0
        self.scope_ok = self.coverage_ok = True
        self.cache = VerifiedHistoryReuse(authority_id='trusted-source', central_revision=PIN,
            probe=self.probe, reader=self.read, verify_scope=self.scope, verify_coverage=self.coverage)
    def read(self, req):
        self.reads += 1
        return self.evidence
    def probe(self, req):
        self.probes += 1
        return self.v
    def scope(self, e):
        self.scopes += 1
        return self.scope_ok
    def coverage(self, e):
        self.coverages += 1
        return self.coverage_ok
    def observe(self, req=REQUEST):
        result = self.cache.observe(req)
        assert not result.preflight.mutation_authorized
        return result


def test_reuse_requires_fresh_version_and_skips_full_recovery():
    h = Harness()
    assert not h.observe().reused
    assert h.observe().reused
    assert (h.reads, h.probes, h.scopes, h.coverages) == (1, 3, 1, 1)


def test_new_generation_reruns_verifiers():
    h = Harness(); h.observe()
    h.v = replace(h.v, generation=2)
    assert not h.observe().reused
    assert h.reads == h.scopes == h.coverages == 2
    assert h.observe().reused


@pytest.mark.parametrize('changes', [dict(authority_id='different'), dict(central_revision='b'*40),
    dict(request=replace(REQUEST, target_head='d'*40)), dict(request=replace(REQUEST, scope=replace(REQUEST.scope, work_anchor='other')))])
def test_wrong_version_binding_disables_cache(changes):
    h = Harness(); h.observe(); h.v = replace(h.v, **changes)
    assert not h.observe().reused
    assert not h.observe().reused
    assert h.reads == 3


def test_changed_head_cannot_use_previous_history():
    h = Harness(); h.observe()
    req = replace(REQUEST, target_head='c'*40)
    assert h.observe(req).preflight.recovery.status is RecoveryStatus.IDENTITY_UNVERIFIED
    h.evidence = replace(BASE, request=req)
    h.v = replace(h.v, request=req, digest=evidence_digest(h.evidence))
    assert not h.observe(req).reused
    assert h.observe(req).reused


def test_new_denial_preserved_after_generation_change():
    h = Harness(); h.observe()
    b = HistoricalRecord('denial', None, 'tool_safety')
    h.evidence = replace(BASE, blockers=(b,))
    h.v = replace(h.v, generation=2, digest=evidence_digest(h.evidence))
    for _ in range(2):
        r = h.observe()
        assert not r.reused and r.preflight.recovery.blockers == (b,)
        assert r.preflight.recovery.status is RecoveryStatus.BLOCKER_PRESENT
    assert h.reads == 3


def test_revoked_coverage_invalidates_positive_cache():
    h = Harness(); h.observe(); h.v = replace(h.v, generation=2); h.coverage_ok = False
    assert h.observe().preflight.recovery.status is RecoveryStatus.HISTORY_INCOMPLETE
    assert not h.observe().reused


def test_unavailable_probe_falls_back_to_full_verification():
    h = Harness(); h.observe(); h.v = None
    assert not h.observe().reused
    assert h.observe().preflight.recovery.status is RecoveryStatus.HISTORY_VERIFIED
    assert h.reads == 3


def test_probe_failure_does_not_reuse():
    h = Harness(); h.observe(); h.cache._probe = fail
    h.coverage_ok = False
    assert h.observe().preflight.recovery.status is RecoveryStatus.HISTORY_INCOMPLETE


def test_digest_mismatch_not_cached():
    h = Harness(); h.v = replace(h.v, digest='b'*64)
    for _ in range(2):
        assert h.observe().preflight.recovery.status is RecoveryStatus.HISTORY_INCOMPLETE
    assert h.reads == 2


def test_moving_version_during_read_downgrades_positive():
    h = Harness(); old = h.cache._reader
    def move(req):
        e = old(req); h.v = replace(h.v, generation=h.v.generation+1); return e
    h.cache._reader = move
    assert h.observe().preflight.recovery.status is RecoveryStatus.HISTORY_INCOMPLETE
    assert not h.observe().reused


def test_known_blocker_dominates_moving_version():
    h = Harness(); b = HistoricalRecord('original', None, 'repository_policy')
    h.evidence = replace(BASE, blockers=(b,)); old = h.cache._reader
    def move(req):
        e = old(req); h.v = replace(h.v, generation=2); return e
    h.cache._reader = move
    assert h.observe().preflight.recovery.blockers == (b,)


@pytest.mark.parametrize('change',[dict(generation=True),dict(generation=-1),dict(digest='invalid'),dict(central_revision='latest'),dict(authority_id='')])
def test_bad_version_rejected(change):
    with pytest.raises(ValueError): replace(Harness().v, **change)


def test_digest_changes_with_aliases_and_scope():
    assert evidence_digest(BASE) != evidence_digest(replace(BASE, historical_work_ids=('old-1','another')))
    assert evidence_digest(BASE) != evidence_digest(replace(BASE, scope_ref='new-ref'))
