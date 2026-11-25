import copy
import unittest
from datetime import datetime, timezone, timedelta
from chatgpt_operation.adoption.approval import *

class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,25,23,0,tzinfo=timezone.utc)
        self.b=Binding('a'*40,'b'*40,'c'*64,123,456)
        self.run=dict(id=123,run_attempt=1,event='workflow_dispatch',path=WORKFLOW,head_branch='main',head_sha=self.b.base,repository={'id':REPO_ID},head_repository={'id':REPO_ID},status='in_progress',display_title=f'adoption:{self.b.request_sha}:{self.b.digest}',created_at=self.now.isoformat())
        self.reviews=[dict(state='approved',user={'id':OWNER_ID,'type':'User'},comment=self.b.comment(),environments=[{'id':456,'name':ENV}])]
    def check(self,**kwargs):
        d=dict(run=self.run,reviews=self.reviews,current_main=self.b.base,now=self.now);d.update(kwargs)
        return verify_approval(self.b,**d)
    def test_match(self): self.assertFalse(self.check()['write_authorized'])
    def test_missing(self):
        with self.assertRaises(ValueError): self.check(reviews=[])
    def test_duplicate(self):
        with self.assertRaises(ValueError): self.check(reviews=self.reviews*2)
    def test_wrong_owner(self):
        self.reviews[0]['user']['id']=1
        with self.assertRaises(ValueError): self.check()
    def test_bot(self):
        self.reviews[0]['user']['type']='Bot'
        with self.assertRaises(ValueError): self.check()
    def test_wrong_comment(self):
        self.reviews[0]['comment']='APPROVE'
        with self.assertRaises(ValueError): self.check()
    def test_wrong_env(self):
        self.reviews[0]['environments'][0]['id']=1
        with self.assertRaises(ValueError): self.check()
    def test_rejected(self):
        self.reviews[0]['state']='rejected'
        with self.assertRaises(ValueError): self.check()
    def test_rerun(self):
        self.run['run_attempt']=2
        with self.assertRaises(ValueError): self.check()
    def test_wrong_workflow(self):
        self.run['path']='.github/workflows/other.yml'
        with self.assertRaises(ValueError): self.check()
    def test_wrong_repo(self):
        self.run['repository']['id']=1
        with self.assertRaises(ValueError): self.check()
    def test_stale_base(self):
        with self.assertRaises(ValueError): self.check(current_main='d'*40)
    def test_expiry(self):
        with self.assertRaises(ValueError): self.check(now=self.now+timedelta(hours=3))
    def test_wrong_title(self):
        self.run['display_title']='adoption:other'
        with self.assertRaises(ValueError): self.check()
    def test_wrong_run(self):
        self.run['id']=124
        with self.assertRaises(ValueError): self.check()
    def test_future_time(self):
        with self.assertRaises(ValueError): self.check(now=self.now-timedelta(seconds=1))
