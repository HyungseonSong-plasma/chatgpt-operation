import unittest
from chatgpt_operation.adoption.approval import Binding, REPO
from chatgpt_operation.adoption.reservation import PATTERN, reservation_ref, plan_reservation

class ReservationTests(unittest.TestCase):
    def setUp(self):
        self.b=Binding('a'*40,'b'*40,'c'*64,123,456)
        self.rule={'source_type':'Repository','source':REPO,'target':'branch','enforcement':'active',
                   'conditions':{'ref_name':{'include':[PATTERN],'exclude':[]}},
                   'bypass_actors':[],'rules':[{'type':'update'},{'type':'deletion'}]}
    def check(self, **kw):
        args=dict(current_main=self.b.base,ruleset=self.rule,observed_ref=None,observation_complete=True);args.update(kw)
        return plan_reservation(self.b,**args)
    def test_absence_not_authority(self):
        self.assertEqual(self.check()['status'],'RESERVATION_ABSENT_NON_AUTHORIZING')
        self.assertFalse(self.check()['write_authorized'])
    def test_existing_no_replay(self):
        v=self.check(observed_ref={'ref':reservation_ref(self.b),'object':{'type':'commit','sha':'d'*40}})
        self.assertEqual(v['status'],'RESERVATION_EXISTS_RECONCILE_ONLY');self.assertFalse(v['write_authorized'])
    def test_same_candidate_different_run_same_ref(self):
        self.assertEqual(reservation_ref(self.b),reservation_ref(Binding(self.b.base,self.b.request_sha,self.b.digest,999,456)))
    def test_no_bypass(self):
        self.rule['bypass_actors']=[{'actor_id':1}]
        with self.assertRaises(ValueError): self.check()
    def test_missing_bypass(self):
        del self.rule['bypass_actors']
        with self.assertRaises(ValueError): self.check()
    def test_missing_delete(self):
        self.rule['rules'].pop()
        with self.assertRaises(ValueError): self.check()
    def test_disabled(self):
        self.rule['enforcement']='disabled'
        with self.assertRaises(ValueError): self.check()
    def test_exclusion(self):
        self.rule['conditions']['ref_name']['exclude']=[reservation_ref(self.b)]
        with self.assertRaises(ValueError): self.check()
    def test_incomplete(self):
        with self.assertRaises(ValueError): self.check(observation_complete=False)
    def test_stale_main(self):
        with self.assertRaises(ValueError): self.check(current_main='e'*40)
    def test_wrong_ref(self):
        with self.assertRaises(ValueError): self.check(observed_ref={'ref':'refs/heads/main','object':{'type':'commit','sha':'d'*40}})
    def test_wrong_repo(self):
        self.rule['source']='other/repo'
        with self.assertRaises(ValueError): self.check()
    def test_optional_non_fast_forward(self):
        self.rule['rules'].append({'type':'non_fast_forward'})
        self.assertFalse(self.check()['write_authorized'])
    def test_force_protection_does_not_replace_update_restriction(self):
        self.rule['rules']=[{'type':'deletion'},{'type':'non_fast_forward'}]
        with self.assertRaises(ValueError): self.check()
    def test_unexpected_rule_rejected(self):
        self.rule['rules'].append({'type':'creation'})
        with self.assertRaises(ValueError): self.check()
