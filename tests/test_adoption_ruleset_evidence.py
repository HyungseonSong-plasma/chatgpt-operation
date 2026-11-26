import copy
import unittest
from datetime import datetime, timedelta, timezone
from chatgpt_operation.adoption.approval import REPO
from chatgpt_operation.adoption.reservation import PATTERN
from chatgpt_operation.adoption.ruleset_evidence import RULESET_ID, compare_snapshot


class RulesetEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 26, 8, tzinfo=timezone.utc)
        self.rule = dict(id=RULESET_ID, source=REPO, source_type='Repository',
                         target='branch', enforcement='active',
                         conditions={'ref_name':{'include':[PATTERN],'exclude':[]}},
                         rules=[{'type':'deletion'},{'type':'non_fast_forward'},{'type':'update'}],
                         bypass_actors=[], updated_at='2026-11-26T07:10:43.212+00:00')
        self.snapshot = dict(schema_version=1, observed_at='2026-11-26T07:30:00Z',
                             ruleset=copy.deepcopy(self.rule))
        self.live = copy.deepcopy(self.rule)
        del self.live['bypass_actors']

    def check(self):
        return compare_snapshot(self.snapshot, self.live, now=self.now)

    def test_hidden_not_proven_empty(self):
        result = self.check()
        self.assertEqual(result['status'], 'SNAPSHOT_MATCHED_LIVE_BYPASS_UNOBSERVABLE')
        self.assertFalse(result['live_bypass_observable'])
        self.assertFalse(result['write_authorized'])
        self.assertNotIn('bypass_actors', self.live)

    def test_live_empty(self):
        self.live['bypass_actors'] = []
        self.assertEqual(self.check()['status'], 'LIVE_BYPASS_EMPTY_NON_AUTHORIZING')

    def test_live_enabled(self):
        self.live['bypass_actors'] = [{'actor_id':1}]
        with self.assertRaisesRegex(ValueError, 'RESERVATION_BYPASS'): self.check()

    def test_snapshot_missing_bypass(self):
        del self.snapshot['ruleset']['bypass_actors']
        with self.assertRaisesRegex(ValueError, 'RULESET_SNAPSHOT_SCOPE'): self.check()

    def test_snapshot_enabled_bypass(self):
        self.snapshot['ruleset']['bypass_actors'] = [{'actor_id':1}]
        with self.assertRaisesRegex(ValueError, 'RESERVATION_BYPASS'): self.check()

    def test_version_change(self):
        self.live['updated_at'] = '2026-11-26T07:11:00Z'
        with self.assertRaisesRegex(ValueError, 'RULESET_VERSION_CHANGED'): self.check()

    def test_version_timezone_equivalence(self):
        self.live['updated_at'] = '2026-11-26T07:10:43.212Z'
        self.assertFalse(self.check()['write_authorized'])

    def test_missing_version(self):
        del self.live['updated_at']
        with self.assertRaisesRegex(ValueError, 'RULESET_LIVE_FIELDS_MISSING'): self.check()

    def test_rule_drift(self):
        self.live['rules'].pop()
        with self.assertRaisesRegex(ValueError, 'RULESET_VISIBLE_DRIFT'): self.check()

    def test_stale(self):
        self.now += timedelta(hours=3)
        with self.assertRaisesRegex(ValueError, 'RULESET_SNAPSHOT_STALE'): self.check()

    def test_future(self):
        self.snapshot['observed_at'] = '2026-11-26T09:00:00Z'
        with self.assertRaisesRegex(ValueError, 'RULESET_SNAPSHOT_STALE'): self.check()

    def test_observed_before_version(self):
        self.snapshot['observed_at'] = '2026-11-26T07:00:00Z'
        with self.assertRaisesRegex(ValueError, 'RULESET_SNAPSHOT_STALE'): self.check()
