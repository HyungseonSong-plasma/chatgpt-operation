"""Portable repository mutation v1."""
from __future__ import annotations
import base64, fnmatch, hashlib, json, re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

SCHEMA_VERSION=1
SHA40=re.compile(r"^[0-9a-f]{40}$")
REPOSITORY=re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
BRANCH=re.compile(r"^(?!/)(?!.*//)(?!.*\.\.)[A-Za-z0-9._/-]+(?<!/)$")
FILE_ACTIONS=frozenset({"create","update","delete"})
BRANCH_ACTIONS=frozenset({"create"})
RESOURCES={"file":FILE_ACTIONS,"branch":BRANCH_ACTIONS}

class MutationError(RuntimeError): pass
class ManifestError(MutationError): pass
class PolicyError(MutationError): pass
class HardStop(MutationError): pass
class ApiError(HardStop):
    def __init__(self,message:str,*,status:int|None=None):
        super().__init__(message); self.status=status

class Transport(Protocol):
    def get(self,path:str,*,query:dict[str,str]|None=None)->Any: ...
    def request(self,method:str,path:str,*,payload:dict[str,Any]|None=None)->Any: ...

def _keys(raw,allowed,required,where,error=ManifestError):
    extra=set(raw)-allowed; missing=required-set(raw)
    if extra: raise error(f"{where}: unknown fields {sorted(extra)}")
    if missing: raise error(f"{where}: missing fields {sorted(missing)}")

def _sha(v,w):
    if not isinstance(v,str) or not SHA40.fullmatch(v): raise ManifestError(f"{w} must be lowercase 40-hex SHA")
    return v

def normalize_path(v,w="target.path"):
    if not isinstance(v,str) or not v: raise ManifestError(f"{w} must be non-empty string")
    if "\\" in v or v.startswith("./") or "//" in v: raise ManifestError(f"{w} contains ambiguous path form")
    p=PurePosixPath(v)
    if p.is_absolute() or "." in p.parts or ".." in p.parts: raise ManifestError(f"{w} must be normalized repository-relative path")
    if p.as_posix()!=v: raise ManifestError(f"{w} must already be normalized")
    return v

def normalize_branch(v,w="target.branch"):
    if not isinstance(v,str) or not BRANCH.fullmatch(v): raise ManifestError(f"{w} is invalid")
    return v

def _patterns(v,w):
    if not isinstance(v,list) or not all(isinstance(x,str) and x for x in v): raise PolicyError(f"{w} must be list of non-empty strings")
    return tuple(v)

def _allowed(v,allow,deny):
    if any(fnmatch.fnmatchcase(v,p) for p in deny): return False
    return any(fnmatch.fnmatchcase(v,p) for p in allow)

@dataclass(frozen=True)
class Manifest:
    repository:str; resource:str; action:str
    target:dict[str,Any]; expected:dict[str,Any]; desired:dict[str,Any]
    commit_message:str|None
    @property
    def operation_id(self):
        semantic={"schema_version":1,"repository":self.repository,"resource":self.resource,"action":self.action,"target":self.target,"desired":self.desired}
        data=json.dumps(semantic,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
        return hashlib.sha256(data).hexdigest()

@dataclass(frozen=True)
class Policy:
    repository:str
    allow_file_actions:frozenset[str]; allow_branch_actions:frozenset[str]
    file_allow:tuple[str,...]; file_deny:tuple[str,...]
    branch_allow:tuple[str,...]; branch_deny:tuple[str,...]
    gate_mode:str; gate_workflows:frozenset[str]; ignore_current_run:bool

def parse_manifest(raw):
    if not isinstance(raw,dict): raise ManifestError("manifest root must be object")
    _keys(raw,{"schema_version","repository","resource","action","target","expected","desired","commit_message"},{"schema_version","repository","resource","action","target","expected","desired"},"manifest")
    if raw["schema_version"]!=1: raise ManifestError("schema_version must be 1")
    repo=raw["repository"]
    if not isinstance(repo,str) or not REPOSITORY.fullmatch(repo): raise ManifestError("repository must be owner/name")
    resource=raw["resource"]; action=raw["action"]
    if resource not in RESOURCES or action not in RESOURCES[resource]: raise ManifestError(f"unsupported resource/action: {resource}/{action}")
    target,expected,desired=raw["target"],raw["expected"],raw["desired"]
    if not all(isinstance(x,dict) for x in (target,expected,desired)): raise ManifestError("target/expected/desired must be objects")
    msg=raw.get("commit_message")
    if resource=="file":
        _keys(target,{"path","branch"},{"path","branch"},"target")
        target={"path":normalize_path(target["path"]),"branch":normalize_branch(target["branch"])}
        if action=="create":
            _keys(expected,{"absent"},{"absent"},"expected")
            if expected["absent"] is not True: raise ManifestError("file create requires expected.absent=true")
            _keys(desired,{"content"},{"content"},"desired")
        elif action=="update":
            _keys(expected,{"sha"},{"sha"},"expected"); expected={"sha":_sha(expected["sha"],"expected.sha")}
            _keys(desired,{"content"},{"content"},"desired")
        else:
            _keys(expected,{"sha"},{"sha"},"expected"); expected={"sha":_sha(expected["sha"],"expected.sha")}
            _keys(desired,set(),set(),"desired")
        if action!="delete" and not isinstance(desired["content"],str): raise ManifestError("desired.content must be text")
        if not isinstance(msg,str) or not msg.strip(): raise ManifestError("file mutations require commit_message")
    else:
        _keys(target,{"name"},{"name"},"target"); target={"name":normalize_branch(target["name"],"target.name")}
        _keys(expected,{"absent"},{"absent"},"expected")
        if expected["absent"] is not True: raise ManifestError("branch create requires expected.absent=true")
        _keys(desired,{"sha"},{"sha"},"desired"); desired={"sha":_sha(desired["sha"],"desired.sha")}
        if msg is not None: raise ManifestError("branch create does not accept commit_message")
    return Manifest(repo,resource,action,target,dict(expected),dict(desired),msg)

def parse_policy(raw):
    if not isinstance(raw,dict): raise PolicyError("policy root must be object")
    _keys(raw,{"schema_version","repository","mutation","validation_gate"},{"schema_version","repository","mutation","validation_gate"},"policy",PolicyError)
    if raw["schema_version"]!=1: raise PolicyError("policy schema_version must be 1")
    repo=raw["repository"]
    if not isinstance(repo,str) or not REPOSITORY.fullmatch(repo): raise PolicyError("policy.repository must be owner/name")
    m=raw["mutation"]
    if not isinstance(m,dict): raise PolicyError("policy.mutation must be object")
    _keys(m,{"allow","file_paths","branch_names"},{"allow","file_paths","branch_names"},"policy.mutation",PolicyError)
    allow=m["allow"]
    if not isinstance(allow,dict): raise PolicyError("policy.mutation.allow must be object")
    _keys(allow,{"file","branch"},{"file","branch"},"policy.mutation.allow",PolicyError)
    fa,ba=allow["file"],allow["branch"]
    if not isinstance(fa,list) or not set(fa)<=FILE_ACTIONS: raise PolicyError("unsupported file actions")
    if not isinstance(ba,list) or not set(ba)<=BRANCH_ACTIONS: raise PolicyError("unsupported branch actions")
    fp,bn=m["file_paths"],m["branch_names"]
    for value,where in ((fp,"file_paths"),(bn,"branch_names")):
        if not isinstance(value,dict): raise PolicyError(f"{where} must be object")
        _keys(value,{"allow","deny"},{"allow","deny"},where,PolicyError)
    gate=raw["validation_gate"]
    if not isinstance(gate,dict): raise PolicyError("validation_gate must be object")
    _keys(gate,{"mode","workflows","ignore_current_run"},{"mode","workflows","ignore_current_run"},"validation_gate",PolicyError)
    mode=gate["mode"]
    if mode not in {"off","all_actions","named_workflows"}: raise PolicyError("invalid validation_gate.mode")
    workflows=gate["workflows"]
    if not isinstance(workflows,list) or not all(isinstance(x,str) and x for x in workflows): raise PolicyError("validation_gate.workflows must be list")
    if mode=="named_workflows" and not workflows: raise PolicyError("named_workflows requires workflows")
    if mode!="named_workflows" and workflows: raise PolicyError("workflows only valid with named_workflows")
    if not isinstance(gate["ignore_current_run"],bool): raise PolicyError("ignore_current_run must be boolean")
    return Policy(repo,frozenset(fa),frozenset(ba),_patterns(fp["allow"],"file_paths.allow"),_patterns(fp["deny"],"file_paths.deny"),_patterns(bn["allow"],"branch_names.allow"),_patterns(bn["deny"],"branch_names.deny"),mode,frozenset(workflows),gate["ignore_current_run"])

def load_json(path):
    try:
        with open(path,"r",encoding="utf-8") as f: return json.load(f)
    except (OSError,UnicodeError,json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot load JSON {path}: {type(exc).__name__}") from exc

class GitHubTransport:
    def __init__(self,repository,token,api_url="https://api.github.com",timeout=30):
        self.repository=repository; self.token=token; self.api_url=api_url.rstrip("/"); self.timeout=timeout
    def _call(self,method,path,payload=None,query=None):
        url=f"{self.api_url}/repos/{self.repository}{path}"
        if query: url+="?"+urlencode(query)
        data=None if payload is None else json.dumps(payload).encode()
        req=Request(url,data=data,method=method)
        req.add_header("Accept","application/vnd.github+json"); req.add_header("Authorization",f"Bearer {self.token}"); req.add_header("X-GitHub-Api-Version","2022-11-28")
        if data is not None: req.add_header("Content-Type","application/json")
        try:
            with urlopen(req,timeout=self.timeout) as response: body=response.read()
        except HTTPError as exc:
            body=exc.read().decode("utf-8",errors="replace")
            try: detail=json.loads(body).get("message","GitHub API error")
            except json.JSONDecodeError: detail="GitHub API returned non-JSON error"
            raise ApiError(f"GitHub API {method} {path} -> {exc.code}: {detail}",status=exc.code) from exc
        except (URLError,TimeoutError,OSError) as exc:
            raise ApiError(f"GitHub API {method} {path} transport failure: {type(exc).__name__}") from exc
        if not body: return None
        try: return json.loads(body.decode("utf-8"))
        except (UnicodeError,json.JSONDecodeError) as exc: raise ApiError(f"GitHub API {method} {path} returned invalid JSON") from exc
    def get(self,path,*,query=None): return self._call("GET",path,query=query)
    def request(self,method,path,*,payload=None): return self._call(method,path,payload=payload)

class Engine:
    def __init__(self,transport,*,repository,policy,current_run_id=None):
        self.t=transport; self.repository=repository; self.policy=policy; self.current_run_id=str(current_run_id) if current_run_id else None
    def _read(self,path,query=None):
        try: return self.t.get(path,query=query)
        except ApiError as exc:
            if exc.status==404: return None
            raise
    def _authorize(self,m):
        if m.repository!=self.repository or self.policy.repository!=self.repository: raise PolicyError("repository binding mismatch")
        if m.resource=="file":
            if m.action not in self.policy.allow_file_actions: raise PolicyError(f"file action denied: {m.action}")
            if not _allowed(m.target["path"],self.policy.file_allow,self.policy.file_deny): raise PolicyError(f"file path denied: {m.target['path']}")
            if not _allowed(m.target["branch"],self.policy.branch_allow,self.policy.branch_deny): raise PolicyError(f"branch target denied: {m.target['branch']}")
        else:
            if m.action not in self.policy.allow_branch_actions: raise PolicyError(f"branch action denied: {m.action}")
            if not _allowed(m.target["name"],self.policy.branch_allow,self.policy.branch_deny): raise PolicyError(f"branch name denied: {m.target['name']}")
    def _runs(self,status):
        page=1
        while True:
            try: response=self.t.get("/actions/runs",query={"status":status,"per_page":"100","page":str(page)})
            except MutationError: raise
            except Exception as exc: raise HardStop(f"validation gate enumeration failed on page {page}") from exc
            if not isinstance(response,dict) or not isinstance(response.get("workflow_runs"),list): raise HardStop(f"validation gate invalid page {page}")
            runs=response["workflow_runs"]
            yield from runs
            if len(runs)<100: return
            page+=1
            if page>10000: raise HardStop("validation gate pagination exceeded safety bound")
    def _gate(self):
        if self.policy.gate_mode=="off": return
        blocked=[]
        for status in ("in_progress","queued"):
            for run in self._runs(status):
                rid=str(run.get("id"))
                if self.policy.ignore_current_run and self.current_run_id and rid==self.current_run_id: continue
                if self.policy.gate_mode=="named_workflows" and run.get("name") not in self.policy.gate_workflows: continue
                blocked.append({"id":run.get("id"),"name":run.get("name"),"status":run.get("status"),"head_sha":run.get("head_sha")})
        if blocked: raise HardStop("validation gate active: "+json.dumps(blocked,sort_keys=True))
    def execute(self,m):
        self._authorize(m); self._gate()
        return self._file(m) if m.resource=="file" else self._branch(m)
    def _result(self,m,status,identity=None):
        r={"status":status,"operation_id":m.operation_id,"repository":m.repository,"resource":m.resource,"action":m.action,"target":m.target}
        if identity is not None: r["result_identity"]=identity
        return r
    @staticmethod
    def _content(payload):
        try:
            c=payload["content"]
            if not isinstance(c,str): raise TypeError
            return base64.b64decode(c,validate=True).decode("utf-8")
        except (KeyError,TypeError,ValueError,UnicodeError) as exc: raise HardStop("GitHub file content could not be decoded") from exc
    def _file(self,m):
        path,branch=m.target["path"],m.target["branch"]; api="/contents/"+quote(path,safe="/"); cur=self._read(api,{"ref":branch})
        if m.action=="create":
            if cur is not None:
                if self._content(cur)==m.desired["content"]: return self._result(m,"NO_MUTATION_NEEDED",cur.get("sha"))
                raise HardStop("file create target exists with different content")
            self.t.request("PUT",api,payload={"message":m.commit_message,"content":base64.b64encode(m.desired["content"].encode()).decode(),"branch":branch})
        elif m.action=="update":
            if cur is None: raise HardStop("file update target absent")
            if self._content(cur)==m.desired["content"]: return self._result(m,"NO_MUTATION_NEEDED",cur.get("sha"))
            if cur.get("sha")!=m.expected["sha"]: raise HardStop(f"stale file identity: actual={cur.get('sha')} expected={m.expected['sha']}")
            self.t.request("PUT",api,payload={"message":m.commit_message,"content":base64.b64encode(m.desired["content"].encode()).decode(),"branch":branch,"sha":cur["sha"]})
        else:
            if cur is None: return self._result(m,"NO_MUTATION_NEEDED")
            if cur.get("sha")!=m.expected["sha"]: raise HardStop(f"stale file identity: actual={cur.get('sha')} expected={m.expected['sha']}")
            self.t.request("DELETE",api,payload={"message":m.commit_message,"branch":branch,"sha":cur["sha"]})
            if self._read(api,{"ref":branch}) is not None: raise HardStop("post-write verification mismatch: file still exists")
            return self._result(m,"PASS")
        verified=self.t.get(api,query={"ref":branch})
        if self._content(verified)!=m.desired["content"]: raise HardStop("post-write verification mismatch for file content")
        return self._result(m,"PASS",verified.get("sha"))
    def _branch(self,m):
        name=m.target["name"]; api="/git/ref/heads/"+quote(name,safe="/"); cur=self._read(api); desired=m.desired["sha"]
        if cur is not None:
            actual=cur.get("object",{}).get("sha")
            if actual==desired: return self._result(m,"NO_MUTATION_NEEDED",actual)
            raise HardStop(f"branch create target exists with different head: {actual}")
        self.t.request("POST","/git/refs",payload={"ref":f"refs/heads/{name}","sha":desired})
        actual=self.t.get(api).get("object",{}).get("sha")
        if actual!=desired: raise HardStop("post-write verification mismatch for branch create")
        return self._result(m,"PASS",actual)

def execute_from_files(*,manifest_path,policy_path,repository,token,current_run_id=None,api_url="https://api.github.com"):
    manifest=parse_manifest(load_json(manifest_path))
    try: policy=parse_policy(load_json(policy_path))
    except ManifestError as exc: raise PolicyError(str(exc)) from exc
    return Engine(GitHubTransport(repository,token,api_url=api_url),repository=repository,policy=policy,current_run_id=current_run_id).execute(manifest)
