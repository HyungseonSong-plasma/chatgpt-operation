import copy
import json
import unittest
from chatgpt_operation.adoption.candidate import *

def raw(x):
    return json.dumps(x).encode()

class Tests(unittest.TestCase):
    def setUp(self):
        self.base='a'*40
        self.old={REGISTRY:raw({'schema_version':1,'capabilities':{'OLD':{'providers':[]}}}),
                  CATALOG:raw({'schema_version':1,'skills':[{'name':'repository-mutation','load_on':['MUTATE'],'capabilities':['OLD']},{'name':'other','load_on':['OTHER']}]}),README:b'old\n'}
        self.new=copy.deepcopy(self.old)
        reg=parse(self.new[REGISTRY]); reg['capabilities'][CAPABILITY]=ENTRY; self.new[REGISTRY]=raw(reg)
        cat=parse(self.new[CATALOG]); cat['skills'][0]['load_on'].append(CAPABILITY); cat['skills'][0]['capabilities'].append(CAPABILITY); self.new[CATALOG]=raw(cat)
        self.new[README]+=b'new scope\n'; self.new[CONTRACT]=b'qualification only\n'
    def verify(self, **kw):
        args=dict(expected_base=self.base, observed_base=self.base, baseline=self.old, proposed=self.new, approved_candidate_sha256=candidate_digest(self.base,self.new)); args.update(kw)
        return inspect_candidate(**args)
    def test_valid_non_authorizing(self):
        self.assertFalse(self.verify().write_authorized)
    def test_stale_base(self):
        with self.assertRaisesRegex(Hold,'STALE_BASE'): self.verify(observed_base='b'*40)
    def test_wrong_approval_digest(self):
        with self.assertRaisesRegex(Hold,'CANDIDATE_DIGEST_MISMATCH'): self.verify(approved_candidate_sha256='0'*64)
    def test_policy_path_denied(self):
        self.new['automation/samuel/repository-mutation-policy.json']=b'{}'
        with self.assertRaisesRegex(Hold,'BAD_PATH_SCOPE'): self.verify()
    def test_existing_provider_change(self):
        x=parse(self.new[REGISTRY]); x['capabilities']['OLD']={}; self.new[REGISTRY]=raw(x)
        with self.assertRaisesRegex(Hold,'REGISTRY_DELTA_MISMATCH'): self.verify()
    def test_fallback_added(self):
        x=parse(self.new[REGISTRY]); x['capabilities'][CAPABILITY]['providers'].append({'name':'fallback'}); self.new[REGISTRY]=raw(x)
        with self.assertRaisesRegex(Hold,'REGISTRY_DELTA_MISMATCH'): self.verify()
    def test_other_skill_changed(self):
        x=parse(self.new[CATALOG]); x['skills'][1]['load_on'].append('MUTATE'); self.new[CATALOG]=raw(x)
        with self.assertRaisesRegex(Hold,'CATALOG_DELTA_MISMATCH'): self.verify()
    def test_duplicate_key(self):
        self.new[REGISTRY]=b'{"schema_version":1,"schema_version":1}'
        with self.assertRaisesRegex(Hold,'DUPLICATE_JSON_KEY'): self.verify()
    def test_rewrite_readme(self):
        self.new[README]=b'replacement'
        with self.assertRaisesRegex(Hold,'README_REWRITE'): self.verify()
    def test_missing_contract(self):
        del self.new[CONTRACT]
        with self.assertRaisesRegex(Hold,'BAD_PATH_SCOPE'): self.verify()
    def test_payload_drift(self):
        approved=candidate_digest(self.base,self.new); self.new[CONTRACT]+=b'changed'
        with self.assertRaisesRegex(Hold,'CANDIDATE_DIGEST_MISMATCH'): self.verify(approved_candidate_sha256=approved)

if __name__=='__main__': unittest.main()
