"""Staging is not completed-run authority; all tests use synthetic ports."""
import unittest
from dataclasses import replace
import test_foreign_work_issuer as fixture_module
from chatgpt_operation.controller.foreign_work_issuer import stage_first_issuance
from chatgpt_operation.controller.foreign_issuance import IssuanceHold
from chatgpt_operation.repository.legacy_work_identity import HistoricalRecord


class TestStagedIssuer(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.TestForeignWorkIssuer()
        self.fixture.setUp()
        self.args = dict(self.fixture.args)
        self.args.pop('verify_publication')

    def stage(self, **changes):
        return stage_first_issuance(**dict(self.args, **changes))

    def test_staging_needs_no_completed_run_but_is_not_authority(self):
        record, commit = self.stage()
        self.assertEqual(len(self.fixture.transport.writes), 4)
        self.assertFalse(record.payload(self.fixture.paths)['work_enrolled'])
        self.assertFalse(record.payload(self.fixture.paths)['controller_execution_approved'])
        with self.assertRaises(IssuanceHold):
            self.fixture.store.read_attestation(self.fixture.s.binding, self.fixture.paths,
                                                lambda *_: False)
        self.assertEqual(self.fixture.store.read_attestation(
            self.fixture.s.binding, self.fixture.paths,
            lambda r, c, raw: r == record and c == commit), record.attestation(self.fixture.paths))

    def test_staging_does_not_relax_any_prewrite_gate(self):
        for port in ('verify_scope', 'verify_coverage', 'verify_approval', 'verify_lease', 'verify_ruleset'):
            with self.subTest(port=port), self.assertRaises(IssuanceHold):
                self.stage(**{port: lambda *_: False})
            self.assertEqual(self.fixture.transport.writes, [])

    def test_known_historical_blocker_prevents_staging(self):
        evidence = replace(self.fixture.evidence,
                           blockers=(HistoricalRecord('original', None, 'TOOL_SAFETY'),))
        with self.assertRaises(IssuanceHold):
            self.stage(read_history=lambda _: evidence)
        self.assertEqual(self.fixture.transport.writes, [])

    def test_existing_storage_is_reconcile_only(self):
        self.stage()
        with self.assertRaises(IssuanceHold):
            self.stage()
        self.assertEqual(len(self.fixture.transport.writes), 4)

    def test_lost_ack_is_not_replayed(self):
        self.fixture.transport.lose_ack = True
        with self.assertRaises(RuntimeError):
            self.stage()
        with self.assertRaises(IssuanceHold):
            self.stage()
        self.assertEqual(len(self.fixture.transport.writes), 4)
