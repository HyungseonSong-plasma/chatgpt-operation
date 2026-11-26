import unittest
from datetime import datetime, timezone
from chatgpt_operation.adoption.approval import Binding, ENV, REPO, REPO_ID, OWNER_ID, WORKFLOW
from chatgpt_operation.adoption.github_observation import observe, RULESET_ID
from chatgpt_operation.adoption.reservation import PATTERN, reservation_ref


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.b = Binding('a'*40, 'b'*40, 'c'*64, 123, 456)
        self.now = datetime.now(timezone.utc)
        b = self.b
        env = {'id':456,'name':ENV,'can_admins_bypass':False,'protection_rules':[{'type':'required_reviewers','reviewers':[{'type':'User','reviewer':{'id':OWNER_ID}}]}], 'deployment_branch_policy':{'protected_branches':False,'custom_branch_policies':True}}
        rule = {'id':RULESET_ID,'source_type':'Repository','source':REPO,'target':'branch','enforcement':'active','conditions':{'ref_name':{'include':[PATTERN],'exclude':[]}},'bypass_actors':[],'rules':[{'type':'update'},{'type':'deletion'}]}
        self.ref_path = '/git/matching-refs/' + reservation_ref(b).removeprefix('refs/')
        self.responses = {'/branches/main':{'commit':{'sha':b.base}},'/environments/'+ENV:env,
            '/environments/'+ENV+'/deployment-branch-policies':{'total_count':1,'branch_policies':[{'name':'main','type':'branch'}]},
            '/actions/runs/123':dict(id=123,run_attempt=1,event='workflow_dispatch',path=WORKFLOW,head_branch='main',head_sha=b.base,repository={'id':REPO_ID},head_repository={'id':REPO_ID},status='in_progress',display_title=f'adoption:{b.request_sha}:{b.digest}',created_at=self.now.isoformat()),
            '/actions/runs/123/approvals':[dict(state='approved',user={'id':OWNER_ID,'type':'User'},comment=b.comment(),environments=[{'id':456,'name':ENV,'can_admins_bypass':False}])],
            '/rulesets':[rule],f'/rulesets/{RULESET_ID}':rule,self.ref_path:[]}

    def check(self):
        return observe(self.b, getter=self.responses.__getitem__, clock=lambda:self.now)

    def test_absent(self):
        v=self.check(); self.assertFalse(v['write_authorized']); self.assertEqual(v['reservation']['status'],'RESERVATION_ABSENT_NON_AUTHORIZING')

    def test_existing(self):
        self.responses[self.ref_path]=[{'ref':reservation_ref(self.b),'object':{'type':'commit','sha':'d'*40}}]
        self.assertEqual(self.check()['reservation']['status'],'RESERVATION_EXISTS_RECONCILE_ONLY')

    def test_prefix_not_absence(self):
        self.responses[self.ref_path]=[{'ref':reservation_ref(self.b)+'extra'}]
        with self.assertRaisesRegex(ValueError,'AMBIGUOUS_REF_OBSERVATION'): self.check()

    def test_missing_response_not_absence(self):
        del self.responses[self.ref_path]
        with self.assertRaises(KeyError): self.check()

    def test_ruleset_not_listed(self):
        self.responses['/rulesets']=[]
        with self.assertRaisesRegex(ValueError,'RESERVATION_RULESET_NOT_LISTED'): self.check()

    def test_ruleset_id_mismatch(self):
        self.responses[f'/rulesets/{RULESET_ID}']={'id':123}
        with self.assertRaisesRegex(ValueError,'RESERVATION_RULESET_IDENTITY'): self.check()

    def test_changed_main(self):
        def get(p):
            val=self.responses[p]
            if p=='/branches/main': self.responses[p]={'commit':{'sha':'e'*40}}
            return val
        with self.assertRaisesRegex(ValueError,'STALE_BASE'): observe(self.b,getter=get,clock=lambda:self.now)

    def snapshot_fixture(self):
        import copy
        rule = copy.deepcopy(self.responses[f'/rulesets/{RULESET_ID}'])
        rule['updated_at'] = self.now.isoformat()
        snapshot = dict(schema_version=1, observed_at=self.now.isoformat(), ruleset=rule)
        live = copy.deepcopy(rule)
        del live['bypass_actors']
        self.responses[f'/rulesets/{RULESET_ID}'] = live
        return snapshot

    def test_snapshot_only_is_not_live_gate(self):
        snapshot = self.snapshot_fixture()
        result = observe(self.b, snapshot=snapshot, getter=self.responses.__getitem__, clock=lambda:self.now)
        self.assertEqual(result['reservation']['status'], 'SNAPSHOT_RESERVATION_ABSENT_NON_AUTHORIZING')
        self.assertFalse(result['ruleset_evidence']['live_bypass_observable'])
        self.assertFalse(result['write_authorized'])

    def test_snapshot_existing_ref_no_new_publication(self):
        snapshot = self.snapshot_fixture()
        self.responses[self.ref_path] = [{'ref':reservation_ref(self.b),'object':{'type':'commit','sha':'d'*40}}]
        result = observe(self.b, snapshot=snapshot, getter=self.responses.__getitem__, clock=lambda:self.now)
        self.assertEqual(result['reservation']['status'], 'SNAPSHOT_RESERVATION_EXISTS_RECONCILE_ONLY')
        self.assertFalse(result['reservation']['write_authorized'])

    def test_missing_live_bypass_without_snapshot_fails(self):
        self.snapshot_fixture()
        with self.assertRaisesRegex(ValueError,'RESERVATION_BYPASS_UNKNOWN_OR_ENABLED'): self.check()

    def test_snapshot_detects_change_during_read(self):
        from datetime import timedelta
        snapshot = self.snapshot_fixture()
        def get(p):
            val = self.responses[p]
            if p == self.ref_path:
                self.responses[f'/rulesets/{RULESET_ID}']['updated_at'] = (self.now + timedelta(seconds=1)).isoformat()
            return val
        with self.assertRaisesRegex(ValueError,'RULESET_VERSION_CHANGED'):
            observe(self.b, snapshot=snapshot, getter=get, clock=lambda:self.now)
