"""Trusted-main-only, read-only qualification CLI. Never checks out request code."""
import base64
import json
import os
import subprocess
from datetime import datetime, timezone
from urllib.request import Request, build_opener, HTTPRedirectHandler
from .candidate import PATHS, CONTRACT, SHA, HASH, parse, require, inspect_candidate
from .approval import REPO, REPO_ID, ENV, OWNER_ID, Binding, verify_approval

REQUEST_PATH = 'automation/adoption-requests/checkpoint-cas.json'
MAX_REQUEST = 1_500_000

def git(*args):
    return subprocess.check_output(['git',*args], timeout=30)

def read_blob(commit, path):
    entries = git('ls-tree',commit,'--',path).decode().splitlines()
    require(len(entries)==1 and entries[0].startswith('100644 blob ')
            and entries[0].split('\t',1)[-1]==path,'NOT_REGULAR_FILE')
    require(int(git('cat-file','-s',commit+':'+path)) <= MAX_REQUEST,'BLOB_LIMIT')
    return git('show',commit+':'+path)

def candidate_from_git(base, request):
    require(SHA.fullmatch(base) and SHA.fullmatch(request),'BAD_SHA')
    require(git('rev-list','--parents','-n','1',request).decode().split()==[request,base],'BAD_PARENT')
    require(git('diff-tree','--no-commit-id','--name-status','-r',base,request).decode().splitlines()
            ==['A\t'+REQUEST_PATH],'BAD_REQUEST_DIFF')
    require(not git('ls-tree',base,'--',CONTRACT).strip(),'CONTRACT_ALREADY_EXISTS')
    raw = parse(read_blob(request,REQUEST_PATH))
    require(type(raw) is dict and set(raw)=={'schema_version','base_sha','files'}
            and type(raw['schema_version']) is int and raw['schema_version']==1
            and raw['base_sha']==base and type(raw['files']) is dict and set(raw['files'])==PATHS,'BAD_REQUEST')
    proposed = {p:base64.b64decode(v,validate=True) for p,v in raw['files'].items()}
    baseline = {p:read_blob(base,p) for p in PATHS-{CONTRACT}}
    return baseline,proposed

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def get(path):
    # No redirects to user-chosen URLs, no token outside the fixed API origin.
    require(path.startswith('/') and '?' not in path and '..' not in path,'BAD_API_PATH')
    req=Request('https://api.github.com/repos/'+REPO+path, headers={
        'Authorization':'Bearer '+os.environ['GH_TOKEN'], 'Accept':'application/vnd.github+json',
        'X-GitHub-Api-Version':'2026-03-10'})
    with build_opener(NoRedirect()).open(req,timeout=20) as response:
        require(response.geturl() == req.full_url,'UNEXPECTED_REDIRECT')
        require(not response.headers.get('Link'),'PAGINATED_EVIDENCE')
        raw=response.read(2_000_001)
        require(len(raw)<=2_000_000,'API_LIMIT')
        return parse(raw)

def verify_environment(binding, environment, branch_policies):
    """Check observable settings; admin bypass is a separate owner check."""
    require(environment.get('id')==binding.environment_id and environment.get('name')==ENV,
            'ENVIRONMENT_MISMATCH')
    rules=[r for r in environment.get('protection_rules',[]) if r.get('type')=='required_reviewers']
    require(len(rules)==1 and len(rules[0].get('reviewers',[]))==1
            and rules[0]['reviewers'][0].get('type')=='User'
            and rules[0]['reviewers'][0].get('reviewer',{}).get('id')==OWNER_ID,
            'ENVIRONMENT_REVIEWER_MISMATCH')
    require(environment.get('deployment_branch_policy') ==
            {'protected_branches':False,'custom_branch_policies':True}, 'BRANCH_POLICY_MISMATCH')
    policies=branch_policies.get('branch_policies')
    require(type(policies) is list and branch_policies.get('total_count')==1
            and len(policies)==1 and policies[0].get('name')=='main'
            and policies[0].get('type')=='branch', 'BRANCH_POLICY_MISMATCH')


def main():
    base,request,digest = (os.environ[k] for k in ('EXPECTED_BASE','REQUEST_SHA','CANDIDATE_DIGEST'))
    require(os.environ['GITHUB_REPOSITORY']==REPO and os.environ['GITHUB_REPOSITORY_ID']==str(REPO_ID)
            and os.environ['GITHUB_REF']=='refs/heads/main' and os.environ['GITHUB_EVENT_NAME']=='workflow_dispatch'
            and os.environ['GITHUB_RUN_ATTEMPT']=='1' and os.environ['GITHUB_SHA']==base
            and git('rev-parse','HEAD').decode().strip()==base,'UNTRUSTED_RUNNER_CONTEXT')
    require(SHA.fullmatch(base) and SHA.fullmatch(request) and HASH.fullmatch(digest),'BAD_INPUT')
    binding=Binding(base,request,digest,int(os.environ['GITHUB_RUN_ID']),int(os.environ['ADOPTION_ENV_ID']))
    binding.validate()
    environment=get('/environments/'+ENV)
    verify_environment(binding, environment, get('/environments/'+ENV+'/deployment-branch-policies'))
    current=get('/branches/main')['commit']['sha']
    baseline,proposed=candidate_from_git(base,request)
    result=inspect_candidate(expected_base=base, observed_base=current, baseline=baseline,
                             proposed=proposed, approved_candidate_sha256=digest)
    phase=os.environ['ADOPTION_PHASE']
    if phase=='preflight':
        print(result.status)
        print('Approval comment: '+binding.comment())
    elif phase=='approval':
        run=get(f'/actions/runs/{binding.run_id}')
        reviews=get(f'/actions/runs/{binding.run_id}/approvals')
        print(json.dumps(verify_approval(binding,run=run,reviews=reviews,
                 current_main=get('/branches/main')['commit']['sha'],now=datetime.now(timezone.utc)),sort_keys=True))
    else:
        raise ValueError('BAD_PHASE')

if __name__=='__main__': main()
