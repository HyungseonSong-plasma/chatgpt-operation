from __future__ import annotations
import base64, os, unittest
from unittest.mock import patch
from chatgpt_operation.cli import main as cli_main
from chatgpt_operation.repository.mutation import ApiError,Engine,HardStop,ManifestError,PolicyError,parse_manifest,parse_policy
from chatgpt_operation.source import canonical_github_repository

OLD="a"*40; NEW="b"*40

def mf(action,path="docs/x.txt",branch="issue-1-x",expected=None,desired=None):
    return parse_manifest({"schema_version":1,"repository":"o/r","resource":"file","action":action,
      "target":{"path":path,"branch":branch},
      "expected":expected if expected is not None else ({"absent":True} if action=="create" else {"sha":OLD}),
      "desired":desired if desired is not None else ({} if action=="delete" else {"content":"new"}),
      "commit_message":"mutate"})

def mb(name="issue-1-x",sha=NEW):
    return parse_manifest({"schema_version":1,"repository":"o/r","resource":"branch","action":"create",
      "target":{"name":name},"expected":{"absent":True},"desired":{"sha":sha}})

def pol(mode="off",workflows=None,file_allow=None,file_deny=None,branch_allow=None,branch_deny=None):
    return parse_policy({"schema_version":1,"repository":"o/r",
      "mutation":{"allow":{"file":["create","update","delete"],"branch":["create"]},
      "file_paths":{"allow":file_allow or ["docs/**"],"deny":file_deny or [".github/**"]},
      "branch_names":{"allow":branch_allow or ["issue-*"],"deny":branch_deny or ["main"]}},
      "validation_gate":{"mode":mode,"workflows":workflows or [],"ignore_current_run":True}})

class Fake:
    def __init__(self):
        self.files={}; self.branches={}; self.runs={"in_progress":[],"queued":[]}; self.fail_page=None; self.break_verify=False; self.requests=[]; self.file_create_race=False; self.branch_create_race=False
    def get(self,path,*,query=None):
        if path=="/actions/runs":
            status=query["status"]; page=int(query["page"])
            if self.fail_page==(status,page): raise ApiError("page failed",status=500)
            values=self.runs[status]; start=(page-1)*100
            return {"workflow_runs":values[start:start+100]}
        if path.startswith("/contents/"):
            key=(path.removeprefix("/contents/"),(query or {}).get("ref"))
            if key not in self.files: raise ApiError("not found",status=404)
            return dict(self.files[key])
        if path.startswith("/git/ref/heads/"):
            name=path.removeprefix("/git/ref/heads/")
            if name not in self.branches: raise ApiError("not found",status=404)
            return {"object":{"sha":self.branches[name]}}
        raise AssertionError(path)
    def request(self,method,path,*,payload=None):
        self.requests.append((method,path,payload)); payload=payload or {}
        if path.startswith("/contents/"):
            key=(path.removeprefix("/contents/"),payload["branch"])
            if method=="DELETE": self.files.pop(key,None); return None
            c=base64.b64decode(payload["content"]).decode()
            if self.file_create_race and "sha" not in payload:
                self.files[key]={"sha":NEW,"content":base64.b64encode(c.encode()).decode()}
                raise ApiError("exists",status=422)
            stored="CORRUPTED" if self.break_verify else c
            self.files[key]={"sha":"f"*40,"content":base64.b64encode(stored.encode()).decode()}; return {}
        if path=="/git/refs":
            name=payload["ref"].removeprefix("refs/heads/")
            if self.branch_create_race:
                self.branches[name]=payload["sha"]
                raise ApiError("exists",status=422)
            self.branches[name]=payload["sha"]; return {}
        raise AssertionError((method,path))

class Tests(unittest.TestCase):
    def engine(self,f=None,p=None,run=None): return Engine(f or Fake(),repository="o/r",policy=p or pol(),current_run_id=run)
    def test_closed_world(self):
        with self.assertRaises(ManifestError):
            parse_manifest({"schema_version":1,"repository":"o/r","resource":"issue","action":"update","target":{},"expected":{},"desired":{}})
    def test_path_policy(self):
        f=Fake(); e=self.engine(f,pol(file_allow=["**"],file_deny=["docs/private/**"]))
        with self.assertRaises(PolicyError): e.execute(mf("create",path="docs/private/x.txt"))
        with self.assertRaises(PolicyError): self.engine(f,pol(file_allow=["docs/**"])).execute(mf("create",path="src/x.txt"))
    def test_main_branch_denied(self):
        with self.assertRaises(PolicyError): self.engine().execute(mb("main"))
    def test_create_retry(self):
        f=Fake(); f.files[("docs/x.txt","issue-1-x")]={"sha":OLD,"content":base64.b64encode(b"new").decode()}
        self.assertEqual(self.engine(f).execute(mf("create"))["status"],"NO_MUTATION_NEEDED")
    def test_github_wrapped_base64_content(self):
        f=Fake()
        wrapped=base64.encodebytes(b"new").decode()
        f.files[("docs/x.txt","issue-1-x")]={"sha":OLD,"content":wrapped,"encoding":"base64"}
        self.assertEqual(self.engine(f).execute(mf("create"))["status"],"NO_MUTATION_NEEDED")

    def test_update_retry_before_stale(self):
        f=Fake(); f.files[("docs/x.txt","issue-1-x")]={"sha":NEW,"content":base64.b64encode(b"new").decode()}
        self.assertEqual(self.engine(f).execute(mf("update"))["status"],"NO_MUTATION_NEEDED")
    def test_delete_retry(self):
        self.assertEqual(self.engine().execute(mf("delete"))["status"],"NO_MUTATION_NEEDED")
    def test_stale_update(self):
        f=Fake(); f.files[("docs/x.txt","issue-1-x")]={"sha":NEW,"content":base64.b64encode(b"old").decode()}
        with self.assertRaises(HardStop): self.engine(f).execute(mf("update"))
    def test_update_and_readback(self):
        f=Fake(); f.files[("docs/x.txt","issue-1-x")]={"sha":OLD,"content":base64.b64encode(b"old").decode()}
        r=self.engine(f).execute(mf("update")); self.assertEqual(r["status"],"PASS"); self.assertEqual(len(r["operation_id"]),64)
    def test_post_write_mismatch(self):
        f=Fake(); f.files[("docs/x.txt","issue-1-x")]={"sha":OLD,"content":base64.b64encode(b"old").decode()}; f.break_verify=True
        with self.assertRaises(HardStop): self.engine(f).execute(mf("update"))
    def test_operation_id_ignores_expected(self):
        self.assertEqual(mf("update",expected={"sha":OLD}).operation_id,mf("update",expected={"sha":NEW}).operation_id)
    def test_gate_paginates(self):
        f=Fake(); f.runs["in_progress"]=[{"id":i,"name":"Other","status":"in_progress"} for i in range(100)]+[{"id":100,"name":"Repository CI","status":"in_progress"}]
        with self.assertRaises(HardStop): self.engine(f,pol("named_workflows",["Repository CI"])).execute(mb())
    def test_gate_fails_closed_page_error(self):
        f=Fake(); f.runs["in_progress"]=[{"id":i,"name":"Other","status":"in_progress"} for i in range(100)]; f.fail_page=("in_progress",2)
        with self.assertRaises(HardStop): self.engine(f,pol("all_actions")).execute(mb())
    def test_source_remote_parser(self):
        self.assertEqual(canonical_github_repository("git@github.com:HyungseonSong-plasma/chatgpt-operation.git"),"HyungseonSong-plasma/chatgpt-operation")
        self.assertIsNone(canonical_github_repository("https://example.com/o/r.git"))
    def test_path_normalization(self):
        for path in ("../x.txt","./x.txt","docs\\x.txt"):
            with self.assertRaises(ManifestError): mf("create",path=path)

    def test_file_create_race_converges(self):
        f=Fake(); f.file_create_race=True
        self.assertEqual(self.engine(f).execute(mf("create"))["status"],"NO_MUTATION_NEEDED")
    def test_branch_create_race_converges(self):
        f=Fake(); f.branch_create_race=True
        self.assertEqual(self.engine(f).execute(mb())["status"],"NO_MUTATION_NEEDED")
    def test_result_persistence_failure_is_structured(self):
        old=os.environ.get("TEST_TOKEN"); os.environ["TEST_TOKEN"]="x"
        try:
            with patch("chatgpt_operation.cli.execute_from_files",return_value={"status":"PASS","operation_id":"op"}), patch("chatgpt_operation.cli.persist",side_effect=OSError):
                code=cli_main(["repository","mutate","--manifest","m","--policy","p","--repository","o/r","--token-env","TEST_TOKEN","--result","r"])
            self.assertEqual(code,3)
        finally:
            if old is None: os.environ.pop("TEST_TOKEN",None)
            else: os.environ["TEST_TOKEN"]=old

if __name__=="__main__": unittest.main()
