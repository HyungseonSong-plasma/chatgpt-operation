from dataclasses import replace
import pytest
from chatgpt_operation.repository.legacy_work_identity import (
    LegacyWorkScope, RecoveryRequest, HistoricalRecord, HistoryEvidence,
    RecoveryStatus, recover_work_identity,
)

SCOPE = LegacyWorkScope('example/repo', 10, 20, 'trusted-work-package-1')
REQUEST = RecoveryRequest(SCOPE, 'a'*40)
BASE = HistoryEvidence(REQUEST, 'scope-proof', 'source', 'coverage-proof', 'old-1', ('old-1', 'old-2'), ())


def run(evidence=BASE, scope=lambda _: True, coverage=lambda _: True):
    return recover_work_identity(REQUEST, trusted_reader=lambda _: evidence,
                                 verify_scope=scope, verify_coverage=coverage)


def test_original_id_preserved():
    result = run()
    assert result.status is RecoveryStatus.HISTORY_VERIFIED
    assert result.work_id == 'old-1'
    assert result.historical_work_ids == ('old-1', 'old-2')
    assert not result.mutation_authorized


@pytest.mark.parametrize('source', ['tool_safety', 'repository_policy', 'github_http', 'unknown', 'ci'])
def test_known_blocker_dominates_incomplete_coverage(source):
    blocker = HistoricalRecord('original-event', 'b'*64, source)
    result = run(replace(BASE, coverage_ref=None, blockers=(blocker,)))
    assert result.status is RecoveryStatus.BLOCKER_PRESENT
    assert result.blockers == (blocker,)
    assert not result.mutation_authorized


def test_blocker_without_original_id_survives():
    b = HistoricalRecord('original-event', None, 'tool_safety')
    result = run(replace(BASE, original_work_id=None, historical_work_ids=(), blockers=(b,)))
    assert result.status is RecoveryStatus.BLOCKER_PRESENT
    assert result.blockers == (b,)
    assert result.work_id is None


@pytest.mark.parametrize('coverage', [lambda _: False, lambda _: 1, lambda _: None])
def test_unverified_history_not_denial_or_clearance(coverage):
    r = run(coverage=coverage)
    assert r.status is RecoveryStatus.HISTORY_INCOMPLETE
    assert not r.blockers and not r.mutation_authorized


def test_missing_coverage():
    assert run(replace(BASE, coverage_ref=None)).status is RecoveryStatus.HISTORY_INCOMPLETE


@pytest.mark.parametrize('scope', [lambda _: False, lambda _: 1, lambda _: None])
def test_scope_requires_exact_true(scope):
    assert run(scope=scope).status is RecoveryStatus.IDENTITY_UNVERIFIED


def test_scope_mismatch():
    e = replace(BASE, request=replace(REQUEST, target_head='c'*40))
    assert run(e).status is RecoveryStatus.IDENTITY_UNVERIFIED


def test_missing_old_id_is_not_proof_of_absence():
    r = run(replace(BASE, original_work_id=None, historical_work_ids=()))
    assert r.status is RecoveryStatus.IDENTITY_UNVERIFIED and r.work_id is None


def test_verified_never_issued_id_can_bind():
    e = replace(BASE, original_work_id=None, historical_work_ids=(), no_original_id_issued=True)
    r = run(e)
    assert r.status is RecoveryStatus.HISTORY_VERIFIED
    assert r.work_id == SCOPE.legacy_work_id()
    assert not r.mutation_authorized


def test_new_head_does_not_change_stable_id():
    assert replace(REQUEST, target_head='d'*40).scope.legacy_work_id() == SCOPE.legacy_work_id()


@pytest.mark.parametrize('change', [{'work_anchor':'other'}, {'issue_id':21}, {'repository_id':11}])
def test_different_work_scope_different_id(change):
    assert replace(SCOPE, **change).legacy_work_id() != SCOPE.legacy_work_id()


def test_repository_rename_does_not_change_anchor_id():
    assert replace(SCOPE, repository='example/renamed').legacy_work_id() == SCOPE.legacy_work_id()


def test_contradictory_identity_rejected():
    with pytest.raises(ValueError):
        replace(BASE, no_original_id_issued=True)


def test_original_id_must_be_in_aliases():
    with pytest.raises(ValueError):
        replace(BASE, historical_work_ids=('old-2',))


def test_duplicate_records_rejected():
    b = HistoricalRecord('original-event', None, 'unknown')
    with pytest.raises(ValueError):
        replace(BASE, blockers=(b,b))


def fail(_):
    raise OSError('unavailable')


def test_reader_failure():
    r = recover_work_identity(REQUEST, trusted_reader=fail, verify_scope=lambda _: True, verify_coverage=lambda _: True)
    assert r.status is RecoveryStatus.IDENTITY_UNVERIFIED


def test_scope_verifier_failure():
    assert run(scope=fail).status is RecoveryStatus.IDENTITY_UNVERIFIED


def test_coverage_verifier_failure():
    assert run(coverage=fail).status is RecoveryStatus.HISTORY_INCOMPLETE


def test_no_coverage_callback_does_not_hide_blocker():
    b = HistoricalRecord('event', None, 'tool_safety')
    assert run(replace(BASE, blockers=(b,)), coverage=fail).status is RecoveryStatus.BLOCKER_PRESENT
