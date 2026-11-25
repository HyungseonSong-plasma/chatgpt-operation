from dataclasses import replace
import unittest
from chatgpt_operation.repository.legacy_work_identity import HistoricalRecord, RecoveryStatus
from chatgpt_operation.repository.legacy_mutation_preflight import HistoryDisposition, observe_history, observe_github_history
from test_legacy_work_identity import BASE, REQUEST, fail
from test_legacy_github_history import Fake, REQ, reader, evidence


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

