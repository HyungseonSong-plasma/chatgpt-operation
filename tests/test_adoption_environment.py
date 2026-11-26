import copy
import unittest
from chatgpt_operation.adoption.approval import Binding, OWNER_ID, ENV
from chatgpt_operation.adoption.qualify import verify_environment

class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.binding=Binding('a'*40,'b'*40,'c'*64,123,456)
        self.env={'id':456,'name':ENV,'can_admins_bypass':False,'protection_rules':[{'type':'required_reviewers','reviewers':[{'type':'User','reviewer':{'id':OWNER_ID}}]}], 'deployment_branch_policy':{'protected_branches':False,'custom_branch_policies':True}}
        self.rules={'total_count':1,'branch_policies':[{'name':'main','type':'branch'}]}
    def check(self):
        return verify_environment(self.binding,self.env,self.rules)
    def test_exact(self): self.assertIsNone(self.check())
    def test_wrong_id(self):
        self.env['id']=1
        with self.assertRaises(ValueError): self.check()
    def test_missing_owner(self):
        self.env['protection_rules']=[]
        with self.assertRaises(ValueError): self.check()
    def test_extra_reviewer(self):
        self.env['protection_rules'][0]['reviewers'].append({'type':'User','reviewer':{'id':1}})
        with self.assertRaises(ValueError): self.check()
    def test_all_branches(self):
        self.env['deployment_branch_policy']=None
        with self.assertRaises(ValueError): self.check()
    def test_wildcard(self):
        self.rules['branch_policies'][0]['name']='*'
        with self.assertRaises(ValueError): self.check()
    def test_tag(self):
        self.rules['branch_policies'][0]['type']='tag'
        with self.assertRaises(ValueError): self.check()
    def test_incomplete(self):
        self.rules['total_count']=2
        with self.assertRaises(ValueError): self.check()

    def test_admin_bypass_enabled(self):
        self.env['can_admins_bypass']=True
        with self.assertRaisesRegex(ValueError,'ADMIN_BYPASS_NOT_DISABLED'): self.check()
    def test_admin_bypass_missing(self):
        del self.env['can_admins_bypass']
        with self.assertRaisesRegex(ValueError,'ADMIN_BYPASS_NOT_DISABLED'): self.check()
    def test_admin_bypass_not_boolean(self):
        self.env['can_admins_bypass']=0
        with self.assertRaisesRegex(ValueError,'ADMIN_BYPASS_NOT_DISABLED'): self.check()
