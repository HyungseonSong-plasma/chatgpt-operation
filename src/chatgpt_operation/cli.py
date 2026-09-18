"""chatgpt-operation CLI."""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path
from chatgpt_operation.repository.mutation import MutationError, execute_from_files
from chatgpt_operation.source import SourceVerificationError, verify_git_source

def persist(path: str | None, result: dict) -> None:
    if path:
        Path(path).write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")

def mutate(args: argparse.Namespace) -> int:
    token=os.environ.get(args.token_env)
    if not token:
        print(f"{args.token_env} is required",file=sys.stderr); return 2
    result=None
    try:
        result=execute_from_files(
            manifest_path=args.manifest, policy_path=args.policy,
            repository=args.repository, token=token,
            current_run_id=args.current_run_id, api_url=args.api_url,
        )
        print("REPOSITORY_MUTATION="+result["status"])
        print(json.dumps(result,sort_keys=True))
    except MutationError as exc:
        failure={"status":"HARD_STOP","phase":"mutation","error_type":type(exc).__name__,"error":str(exc)}
        print("REPOSITORY_MUTATION=HARD_STOP",file=sys.stderr)
        print(json.dumps(failure,sort_keys=True),file=sys.stderr)
        try: persist(args.result,failure)
        except OSError: pass
        return 2
    except Exception as exc:
        failure={"status":"HARD_STOP","phase":"boundary","error_type":type(exc).__name__}
        print("REPOSITORY_MUTATION=HARD_STOP",file=sys.stderr)
        print(json.dumps(failure,sort_keys=True),file=sys.stderr)
        try: persist(args.result,failure)
        except OSError: pass
        return 2
    try:
        persist(args.result,result)
    except OSError as exc:
        failure={
            "status":"HARD_STOP","phase":"result_persistence",
            "remote_status":result["status"],"operation_id":result.get("operation_id"),
            "error_type":type(exc).__name__,
        }
        print("REPOSITORY_MUTATION=HARD_STOP",file=sys.stderr)
        print(json.dumps(failure,sort_keys=True),file=sys.stderr)
        return 3
    return 0

def source_verify(args: argparse.Namespace) -> int:
    try:
        verify_git_source(args.path,repository=args.repository,expected_sha=args.expected_sha)
    except SourceVerificationError as exc:
        print(f"SOURCE_VERIFY=HARD_STOP {exc}",file=sys.stderr); return 2
    print("SOURCE_VERIFY=PASS"); return 0

def parser() -> argparse.ArgumentParser:
    p=argparse.ArgumentParser(prog="chatgpt-op")
    sub=p.add_subparsers(dest="group",required=True)
    s=sub.add_parser("source"); ss=s.add_subparsers(dest="command",required=True)
    v=ss.add_parser("verify"); v.add_argument("--path",default=".")
    v.add_argument("--repository",required=True); v.add_argument("--expected-sha",required=True)
    v.set_defaults(func=source_verify)
    r=sub.add_parser("repository"); rs=r.add_subparsers(dest="command",required=True)
    m=rs.add_parser("mutate"); m.add_argument("--manifest",required=True); m.add_argument("--policy",required=True)
    m.add_argument("--repository",default=os.environ.get("GITHUB_REPOSITORY"))
    m.add_argument("--token-env",default="GITHUB_TOKEN"); m.add_argument("--current-run-id",default=os.environ.get("GITHUB_RUN_ID"))
    m.add_argument("--api-url",default=os.environ.get("GITHUB_API_URL","https://api.github.com")); m.add_argument("--result")
    m.set_defaults(func=mutate)
    return p

def main(argv=None) -> int:
    p=parser(); args=p.parse_args(argv)
    if args.group=="repository" and not args.repository:
        p.error("--repository or GITHUB_REPOSITORY is required")
    return args.func(args)

if __name__=="__main__": raise SystemExit(main())
