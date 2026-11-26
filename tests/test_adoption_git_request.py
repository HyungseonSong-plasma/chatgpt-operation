import base64, json, os, subprocess, tempfile, unittest
from pathlib import Path
from chatgpt_operation.adoption.candidate import REGISTRY,CATALOG,README,CONTRACT,ENTRY,CAPABILITY,candidate_digest,inspect_candidate
from chatgpt_operation.adoption.qualify import candidate_from_git, REQUEST_PATH

class GitRequestTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.cwd=os.getcwd();os.chdir(self.tmp.name);self.addCleanup(os.chdir,self.cwd)
        self.git('init','-q');self.git('config','user.email','test@example.invalid');self.git('config','user.name','Test')
        old={REGISTRY:json.dumps({'schema_version':1,'capabilities':{}}).encode(),CATALOG:json.dumps({'schema_version':1,'skills':[{'name':'repository-mutation','load_on':['MUTATE'],'capabilities':[]}]}).encode(),README:b'old\n'}
        for p,b in old.items(): self.write(p,b)
        self.git('add','.');self.git('commit','-qm','baseline');self.base=self.git('rev-parse','HEAD')
        self.new={REGISTRY:json.dumps({'schema_version':1,'capabilities':{CAPABILITY:ENTRY}}).encode(),CATALOG:json.dumps({'schema_version':1,'skills':[{'name':'repository-mutation','load_on':['MUTATE',CAPABILITY],'capabilities':[CAPABILITY]}]}).encode(),README:b'old\nnew\n',CONTRACT:b'candidate only\n'}
        self.request={'schema_version':1,'base_sha':self.base,'files':{p:base64.b64encode(b).decode() for p,b in self.new.items()}}
    def git(self,*a): return subprocess.check_output(['git',*a],text=True).strip()
    def write(self,path,b):
        p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
    def commit_request(self,extra=False):
        self.write(REQUEST_PATH,json.dumps(self.request).encode())
        if extra: self.write('other.py',b'pass\n')
        self.git('add','.');self.git('commit','-qm','request');return self.git('rev-parse','HEAD')
    def test_valid(self):
        req=self.commit_request();self.git('checkout','--detach','-q',self.base)
        old,new=candidate_from_git(self.base,req)
        receipt=inspect_candidate(expected_base=self.base,observed_base=self.base,baseline=old,proposed=new,approved_candidate_sha256=candidate_digest(self.base,self.new))
        self.assertFalse(receipt.write_authorized);self.assertFalse(Path(REQUEST_PATH).exists())
    def test_extra_code(self):
        req=self.commit_request(extra=True)
        with self.assertRaisesRegex(ValueError,'BAD_REQUEST_DIFF'): candidate_from_git(self.base,req)
    def test_wrong_parent(self):
        req=self.commit_request();self.git('commit','--allow-empty','-qm','second')
        with self.assertRaisesRegex(ValueError,'BAD_PARENT'): candidate_from_git(self.base,self.git('rev-parse','HEAD'))
    def test_wrong_schema(self):
        self.request['schema_version']=True;req=self.commit_request()
        with self.assertRaisesRegex(ValueError,'BAD_REQUEST'): candidate_from_git(self.base,req)
    def test_symlink(self):
        p=Path(REQUEST_PATH);p.parent.mkdir(parents=True);p.symlink_to('../../README.md')
        self.git('add','.');self.git('commit','-qm','symlink');req=self.git('rev-parse','HEAD')
        with self.assertRaisesRegex(ValueError,'NOT_REGULAR_FILE'): candidate_from_git(self.base,req)

    def test_v2_snapshot_request_preserves_candidate(self):
        self.request['schema_version']=2
        self.request['ruleset_snapshot']={'schema_version':1,'observed_at':'2026-11-26T07:30:00Z','ruleset':{}}
        req=self.commit_request()
        old,new=candidate_from_git(self.base,req)
        self.assertEqual(new,self.new)
        receipt=inspect_candidate(expected_base=self.base,observed_base=self.base,baseline=old,proposed=new,approved_candidate_sha256=candidate_digest(self.base,self.new))
        self.assertFalse(receipt.write_authorized)
    def test_v2_missing_snapshot(self):
        self.request['schema_version']=2
        req=self.commit_request()
        with self.assertRaisesRegex(ValueError,'BAD_REQUEST'): candidate_from_git(self.base,req)
    def test_v1_extra_snapshot(self):
        self.request['ruleset_snapshot']={}
        req=self.commit_request()
        with self.assertRaisesRegex(ValueError,'BAD_REQUEST'): candidate_from_git(self.base,req)
