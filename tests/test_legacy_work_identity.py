from dataclasses import replace
import unittest
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


def fail(_):
    raise OSError('unavailable')


class LegacyTests(unittest.TestCase):
    def test_original_id_preserved(self):
        result = run()
        self.assertTrue(result.status is RecoveryStatus.HISTORY_VERIFIED)
        self.assertTrue(result.work_id == 'old-1')
        self.assertTrue(result.historical_work_ids == ('old-1', 'old-2'))
        self.assertTrue(not result.mutation_authorized)

    def test_known_blocker_dominates_incomplete_coverage(self):
        for source in ['tool_safety', 'repository_policy', 'github_http', 'unknown', 'ci']:
            with self.subTest(source=source):
                blocker = HistoricalRecord('original-event', 'b'*64, source)
                result = run(replace(BASE, coverage_ref=None, blockers=(blocker,)))
                self.assertTrue(result.status is RecoveryStatus.BLOCKER_PRESENT)
                self.assertTrue(result.blockers == (blocker,))
                self.assertTrue(not result.mutation_authorized)

    def test_blocker_without_original_id_survives(self):
        b = HistoricalRecord('original-event', None, 'tool_safety')
        result = run(replace(BASE, original_work_id=None, historical_work_ids=(), blockers=(b,)))
        self.assertTrue(result.status is RecoveryStatus.BLOCKER_PRESENT)
        self.assertTrue(result.blockers == (b,))
        self.assertTrue(result.work_id is None)

    def test_unverified_history_not_denial_or_clearance(self):
        for coverage in [lambda _: False, lambda _: 1, lambda _: None]:
            with self.subTest(coverage=coverage):
                r = run(coverage=coverage)
                self.assertTrue(r.status is RecoveryStatus.HISTORY_INCOMPLETE)
                self.assertTrue(not r.blockers and not r.mutation_authorized)

    def test_missing_coverage(self):
        self.assertTrue(run(replace(BASE, coverage_ref=None)).status is RecoveryStatus.HISTORY_INCOMPLETE)

    def test_scope_requires_exact_true(self):
        for scope in [lambda _: False, lambda _: 1, lambda _: None]:
            with self.subTest(scope=scope):
                self.assertTrue(run(scope=scope).status is RecoveryStatus.IDENTITY_UNVERIFIED)

    def test_scope_mismatch(self):
        e = replace(BASE, request=replace(REQUEST, target_head='c'*40))
        self.assertTrue(run(e).status is RecoveryStatus.IDENTITY_UNVERIFIED)

    def test_missing_old_id_is_not_proof_of_absence(self):
        r = run(replace(BASE, original_work_id=None, historical_work_ids=()))
        self.assertTrue(r.status is RecoveryStatus.IDENTITY_UNVERIFIED and r.work_id is None)

    def test_verified_never_issued_id_can_bind(self):
        e = replace(BASE, original_work_id=None, historical_work_ids=(), no_original_id_issued=True)
        r = run(e)
        self.assertTrue(r.status is RecoveryStatus.HISTORY_VERIFIED)
        self.assertTrue(r.work_id == SCOPE.legacy_work_id())
        self.assertTrue(not r.mutation_authorized)

    def test_new_head_does_not_change_stable_id(self):
        self.assertTrue(replace(REQUEST, target_head='d'*40).scope.legacy_work_id() == SCOPE.legacy_work_id())

    def test_different_work_scope_different_id(self):
        for change in [{'work_anchor':'other'}, {'issue_id':21}, {'repository_id':11}]:
            with self.subTest(change=change):
                self.assertTrue(replace(SCOPE, **change).legacy_work_id() != SCOPE.legacy_work_id())

    def test_repository_rename_does_not_change_anchor_id(self):
        self.assertTrue(replace(SCOPE, repository='example/renamed').legacy_work_id() == SCOPE.legacy_work_id())

    def test_contradictory_identity_rejected(self):
        with self.assertRaises(ValueError):
            replace(BASE, no_original_id_issued=True)

    def test_original_id_must_be_in_aliases(self):
        with self.assertRaises(ValueError):
            replace(BASE, historical_work_ids=('old-2',))

    def test_duplicate_records_rejected(self):
        b = HistoricalRecord('original-event', None, 'unknown')
        with self.assertRaises(ValueError):
            replace(BASE, blockers=(b,b))

    def test_reader_failure(self):
        r = recover_work_identity(REQUEST, trusted_reader=fail, verify_scope=lambda _: True, verify_coverage=lambda _: True)
        self.assertTrue(r.status is RecoveryStatus.IDENTITY_UNVERIFIED)

    def test_scope_verifier_failure(self):
        self.assertTrue(run(scope=fail).status is RecoveryStatus.IDENTITY_UNVERIFIED)

    def test_coverage_verifier_failure(self):
        self.assertTrue(run(coverage=fail).status is RecoveryStatus.HISTORY_INCOMPLETE)

    def test_no_coverage_callback_does_not_hide_blocker(self):
        b = HistoricalRecord('event', None, 'tool_safety')
        self.assertTrue(run(replace(BASE, blockers=(b,)), coverage=fail).status is RecoveryStatus.BLOCKER_PRESENT)

