#!/usr/bin/env python3
"""Deterministic fail-closed repository mutation skill."""
from __future__ import annotations
import argparse, base64, json, os, re, socket, sys, tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

SCHEMA_VERSION=1
RESOURCES={"file","branch"}
ACTIONS={"file":{"create","update","delete"},"branch":{"create"}}
SHA40=re.compile(r"^[0-9a-f]{40}$"); REPO=re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"); BRANCH=re.compile(r"^(?!/)(?!.*//)(?!.*\.\.)[A-Za-z0-9._/-]+(?<!/)$")

class MutationError(RuntimeError): pass
class ManifestError(MutationError): pass
class HardStop(MutationError): pass
class Transport(Protocol):
    def get(self,path:str,*,query:dict[str,str]|None=None)->Any: ...
    def request(self,method:str,path:str,*,payload:dict[str,Any]|None=None)->Any: ...

def _keys(raw,allowed,required,where):
    extra=set(raw)-allowed; missing=required-set(raw)
    if extra: raise ManifestError(f"{where}: unknown fields {sorted(extra)}")
    if missing: raise ManifestError(f"{where}: missing fields {sorted(missing)}")
def _sha(v,w):
    if not isinstance(v,str) or not SHA40.fullmatch(v): raise ManifestError(f"{w} must be lowercase 40-hex SHA")
    return v
def _path(v,w):
    if not isinstance(v,str): raise ManifestError(f"{w} must be string")
    p=PurePosixPath(v)
    if not v or p.is_absolute() or ".." in p.parts or v.startswith("./"): raise ManifestError(f"{w} must be repository-relative")
    return v
def _branch(v,w):
    if not isinstance(v,str) or not BRANCH.fullmatch(v): raise ManifestError(f"{w} invalid")
    return v
@dataclass(frozen=True)
class MutationManifest:
    repository:str; resource:str; action:str; target:dict[str,Any]; expected:dict[str,Any]; desired:dict[str,Any]; commit_message:str|None=None

def parse_manifest(raw:Any)->MutationManifest:
    if not isinstance(raw,dict): raise ManifestError("manifest root must be object")
    _keys(raw,{"schema_version","repository","resource","action","target","expected","desired","commit_message"},{"schema_version","repository","resource","action","target","expected","desired"},"manifest")
    if raw["schema_version"]!=1: raise ManifestError("schema_version must be 1")
    repo=raw["repository"]; resource=raw["resource"]; action=raw["action"]; target=raw["target"]; expected=raw["expected"]; desired=raw["desired"]; msg=raw.get("commit_message")
    if not isinstance(repo,str) or not REPO.fullmatch(repo): raise ManifestError("repository must be owner/name")
    if resource not in RESOURCES or action not in ACTIONS.get(resource,set()): raise ManifestError(f"invalid resource/action: {resource}/{action}")
    if not all(isinstance(x,dict) for x in (target,expected,desired)): raise ManifestError("target/expected/desired must be objects")
    if resource=="file":
        _keys(target,{"path","branch"},{"path","branch"},"target"); _path(target["path"],"target.path"); _branch(target["branch"],"target.branch")
        if action=="create":
            _keys(expected,{"absent"},{"absent"},"expected"); _keys(desired,{"content"},{"content"},"desired")
            if expected["absent"] is not True: raise ManifestError("create requires expected.absent=true")
        elif action=="update":
            _keys(expected,{"sha"},{"sha"},"expected"); _sha(expected["sha"],"expected.sha"); _keys(desired,{"content"},{"content"},"desired")
        else:
            _keys(expected,{"sha"},{"sha"},"expected"); _sha(expected["sha"],"expected.sha"); _keys(desired,set(),set(),"desired")
        if action!="delete" and not isinstance(desired["content"],str): raise ManifestError("desired.content must be text")
        if not isinstance(msg,str) or not msg.strip(): raise ManifestError("file mutations require commit_message")
    elif resource=="branch":
        _keys(target,{"name"},{"name"},"target"); _branch(target["name"],"target.name")
        _keys(expected,{"absent"},{"absent"},"expected"); _keys(desired,{"sha"},{"sha"},"desired"); _sha(desired["sha"],"desired.sha")
        if expected["absent"] is not True: raise ManifestError("branch create requires expected.absent=true")
        if msg is not None: raise ManifestError("branch mutations do not accept commit_message")
    return MutationManifest(repo,resource,action,target,expected,desired,msg)

def load_manifest(path):
    try:
        return parse_manifest(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ManifestError(f"cannot load manifest {path}: {type(e).__name__}: {e}") from e

class GitHubTransport:
    def __init__(self,repository,token,api_url="https://api.github.com"): self.repository=repository; self.token=token; self.api_url=api_url.rstrip("/")
    def _call(self,method,path,payload=None,query=None):
        url=f"{self.api_url}/repos/{self.repository}{path}"
        if query: url+="?"+urlencode(query)
        data=None if payload is None else json.dumps(payload).encode()
        req=Request(url,data=data,method=method); req.add_header("Accept","application/vnd.github+json"); req.add_header("Authorization",f"Bearer {self.token}"); req.add_header("X-GitHub-Api-Version","2022-11-28")
        if data is not None: req.add_header("Content-Type","application/json")
        try:
            with urlopen(req,timeout=30) as r:
                body=r.read()
        except HTTPError as e:
            raw=e.read()
            try:
                decoded=raw.decode("utf-8")
                try:
                    parsed=json.loads(decoded)
                    detail=parsed.get("message",decoded) if isinstance(parsed,dict) else decoded
                except json.JSONDecodeError:
                    detail=decoded
            except UnicodeDecodeError:
                detail="<non-UTF8 error response>"
            x=HardStop(f"GitHub API {method} {path} -> {e.code}: {detail}"); setattr(x,"status",e.code); raise x from e
        except (URLError, TimeoutError, socket.timeout, OSError) as e:
            raise HardStop(f"GitHub transport failure during {method} {path}: {type(e).__name__}: {e}") from e
        if not body: return None
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise HardStop(f"GitHub API {method} {path} returned non-JSON data") from e
    def get(self,path,*,query=None): return self._call("GET",path,query=query)
    def request(self,method,path,*,payload=None): return self._call(method,path,payload=payload)

def _decode_content(raw):
    if not isinstance(raw,str): raise HardStop("GitHub file response missing content")
    try:
        return base64.b64decode("".join(raw.split()),validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as e:
        raise HardStop("GitHub file content is invalid base64 or non-UTF8") from e

class Engine:
    def __init__(self,transport,*,repository,current_run_id=None): self.t=transport; self.repository=repository; self.current_run_id=str(current_run_id) if current_run_id else None
    def _read(self,path,query=None):
        try: return self.t.get(path,query=query)
        except HardStop as e:
            if getattr(e,"status",None)==404: return None
            raise
    def _lock(self):
        locked=[]
        for status in ("in_progress","queued"):
            for run in self.t.get("/actions/runs",query={"status":status,"per_page":"100"}).get("workflow_runs",[]):
                if self.current_run_id and str(run.get("id"))==self.current_run_id: continue
                locked.append({"id":run.get("id"),"name":run.get("name"),"status":run.get("status"),"head_sha":run.get("head_sha")})
        if locked: raise HardStop("CI mutation lock active: "+json.dumps(locked,sort_keys=True))
    def execute(self,m):
        if m.repository!=self.repository: raise HardStop(f"manifest repository {m.repository} != execution repository {self.repository}")
        self._lock()
        return getattr(self,f"_{m.resource}")(m)
    def _id(self,m): return {"repository":m.repository,"resource":m.resource,"action":m.action,"target":m.target}
    def _ok(self,m,i=None): return {"status":"PASS",**self._id(m),**({"result_identity":i} if i else {})}
    def _noop(self,m,i=None): return {"status":"NO_MUTATION_NEEDED",**self._id(m),**({"result_identity":i} if i else {})}
    def _file(self,m):
        p=m.target["path"]; b=m.target["branch"]; api="/contents/"+quote(p,safe="/"); cur=self._read(api,{"ref":b})
        if m.action=="create":
            desired=m.desired["content"]
            if cur is not None:
                if _decode_content(cur.get("content"))==desired: return self._noop(m,cur.get("sha"))
                raise HardStop("file create expected absence but target exists with different content")
            self.t.request("PUT",api,payload={"message":m.commit_message,"content":base64.b64encode(desired.encode()).decode(),"branch":b})
        elif m.action=="delete":
            if cur is None: return self._noop(m)
            if cur.get("sha")!=m.expected["sha"]: raise HardStop(f"stale file identity: actual={cur.get('sha')} expected={m.expected['sha']}")
            self.t.request("DELETE",api,payload={"message":m.commit_message,"branch":b,"sha":cur["sha"]})
            if self._read(api,{"ref":b}) is not None: raise HardStop("post-write verification mismatch: file still exists")
            return self._ok(m)
        else:
            if cur is None: raise HardStop("file update target absent")
            desired=m.desired["content"]
            if _decode_content(cur.get("content"))==desired: return self._noop(m,cur.get("sha"))
            if cur.get("sha")!=m.expected["sha"]: raise HardStop(f"stale file identity: actual={cur.get('sha')} expected={m.expected['sha']}")
            self.t.request("PUT",api,payload={"message":m.commit_message,"content":base64.b64encode(desired.encode()).decode(),"branch":b,"sha":cur["sha"]})
        v=self.t.get(api,query={"ref":b}); actual=_decode_content(v.get("content"))
        if actual!=m.desired["content"]: raise HardStop("post-write verification mismatch for file content")
        return self._ok(m,v.get("sha"))
    def _branch(self,m):
        n=m.target["name"]; api="/git/ref/heads/"+quote(n,safe="/"); cur=self._read(api); sha=m.desired["sha"]
        if cur is not None:
            try: actual=cur["object"]["sha"]
            except (KeyError,TypeError) as e: raise HardStop("branch ref response missing object.sha") from e
            if actual==sha: return self._noop(m,actual)
            raise HardStop(f"branch create expected absence but branch exists: actual={actual} desired={sha}")
        self.t.request("POST","/git/refs",payload={"ref":f"refs/heads/{n}","sha":sha})
        v=self.t.get(api)
        try: got=v["object"]["sha"]
        except (KeyError,TypeError) as e: raise HardStop("post-write branch response missing object.sha") from e
        if got!=sha: raise HardStop("post-write verification mismatch for branch")
        return self._ok(m,got)

class Fake:
    def __init__(self): self.files={}; self.branches={}; self.runs=[]; self.break_verify=False
    def _e(self,status,msg): x=HardStop(msg); setattr(x,"status",status); return x
    def get(self,path,*,query=None):
        if path=="/actions/runs": return {"workflow_runs":[r for r in self.runs if r["status"]==(query or {}).get("status")]}
        if path.startswith("/contents/"):
            k=(path.removeprefix("/contents/"),(query or {}).get("ref","main"))
            if k not in self.files: raise self._e(404,"not found")
            return dict(self.files[k])
        if path.startswith("/git/ref/heads/"):
            n=path.removeprefix("/git/ref/heads/")
            if n not in self.branches: raise self._e(404,"not found")
            return {"object":{"sha":self.branches[n]}}
        raise AssertionError(path)
    def request(self,method,path,*,payload=None):
        payload=payload or {}
        if path.startswith("/contents/"):
            k=(path.removeprefix("/contents/"),payload["branch"])
            if method=="DELETE": self.files.pop(k,None); return None
            c=base64.b64decode(payload["content"]).decode(); stored="CORRUPTED" if self.break_verify else c; sha="f"*40
            self.files[k]={"sha":sha,"content":base64.b64encode(stored.encode()).decode()}; return {}
        if path=="/git/refs": self.branches[payload["ref"].removeprefix("refs/heads/")]=payload["sha"]; return {}
        raise AssertionError((method,path))

def M(resource,action,target,expected,desired,msg=None):
    raw={"schema_version":1,"repository":"o/r","resource":resource,"action":action,"target":target,"expected":expected,"desired":desired}
    if msg is not None: raw["commit_message"]=msg
    return parse_manifest(raw)

def self_test():
    old="a"*40
    f=Fake(); f.files[("x.txt","main")]={"sha":old,"content":base64.b64encode(b"old").decode()}; e=Engine(f,repository="o/r")
    assert e.execute(M("file","update",{"path":"x.txt","branch":"main"},{"sha":old},{"content":"new"},"update"))["status"]=="PASS"
    stale="0"*40
    assert e.execute(M("file","update",{"path":"x.txt","branch":"main"},{"sha":stale},{"content":"new"},"noop"))["status"]=="NO_MUTATION_NEEDED"
    assert e.execute(M("file","delete",{"path":"missing.txt","branch":"main"},{"sha":old},{},"delete"))["status"]=="NO_MUTATION_NEEDED"
    b=Fake(); assert Engine(b,repository="o/r").execute(M("branch","create",{"name":"x"},{"absent":True},{"sha":old}))["status"]=="PASS"
    assert Engine(b,repository="o/r").execute(M("branch","create",{"name":"x"},{"absent":True},{"sha":old}))["status"]=="NO_MUTATION_NEEDED"
    for resource,action in (("branch","move"),("branch","delete"),("issue","update"),("issue","close"),("issue","reopen")):
        try:
            M(resource,action,{}, {}, {}); raise AssertionError(f"{resource}/{action} unexpectedly allowed")
        except ManifestError: pass
    lock=Fake(); lock.runs=[{"id":10,"name":"CI","status":"in_progress","head_sha":old}]
    try: Engine(lock,repository="o/r").execute(M("branch","create",{"name":"x"},{"absent":True},{"sha":old})); raise AssertionError
    except HardStop: pass
    assert Engine(lock,repository="o/r",current_run_id="10").execute(M("branch","create",{"name":"x"},{"absent":True},{"sha":old}))["status"]=="PASS"
    bad=Fake(); bad.files[("x.txt","main")]={"sha":old,"content":base64.b64encode(b"old").decode()}; bad.break_verify=True
    try: Engine(bad,repository="o/r").execute(M("file","update",{"path":"x.txt","branch":"main"},{"sha":old},{"content":"new"},"bad")); raise AssertionError
    except HardStop: pass
    print("REPOSITORY_MUTATION_SELF_TEST=PASS"); return 0

def _write_result(path,result):
    if not path: return
    p=Path(path)
    try:
        p.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=p.parent,prefix=f".{p.name}.",delete=False) as h:
            tmp=Path(h.name); h.write(json.dumps(result,indent=2,sort_keys=True)+"\n"); h.flush(); os.fsync(h.fileno())
        tmp.replace(p)
    except OSError as e:
        raise HardStop(f"result persistence failed after mutation may have completed; retry is safe for supported operations: {e}") from e

def _preflight_result(path):
    if not path: return
    p=Path(path)
    try:
        p.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=p.parent,prefix=f".{p.name}.preflight.",delete=False) as h:
            probe=Path(h.name); h.write("{}\n")
        probe.unlink()
    except OSError as e:
        raise HardStop(f"result destination is not writable: {e}") from e

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("--self-test",action="store_true"); p.add_argument("--manifest"); p.add_argument("--repository",default=os.environ.get("GITHUB_REPOSITORY")); p.add_argument("--token-env",default="GITHUB_TOKEN"); p.add_argument("--current-run-id",default=os.environ.get("GITHUB_RUN_ID")); p.add_argument("--result"); a=p.parse_args(argv)
    if a.self_test: return self_test()
    if not a.manifest or not a.repository: p.error("--manifest and repository/GITHUB_REPOSITORY required")
    result=None
    try:
        _preflight_result(a.result)
        token=os.environ.get(a.token_env)
        if not token: raise ManifestError(f"{a.token_env} required")
        result=Engine(GitHubTransport(a.repository,token),repository=a.repository,current_run_id=a.current_run_id).execute(load_manifest(a.manifest))
        _write_result(a.result,result)
        print("REPOSITORY_MUTATION="+result["status"]); print(json.dumps(result,sort_keys=True))
        return 0
    except Exception as e:
        result={"status":"HARD_STOP","error_type":type(e).__name__,"error":str(e)}
        try: _write_result(a.result,result)
        except Exception as persist:
            result["result_persistence_error"]=str(persist)
        print("REPOSITORY_MUTATION=HARD_STOP",file=sys.stderr); print(json.dumps(result,sort_keys=True),file=sys.stderr)
        return 2
if __name__=="__main__": raise SystemExit(main())
