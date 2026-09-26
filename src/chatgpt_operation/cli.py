"""chatgpt-operation CLI."""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path
from chatgpt_operation.controller.lifecycle import LifecycleError, evaluate as evaluate_controller, self_test as controller_self_test
from chatgpt_operation.controller.throughput import ThroughputError, evaluate as evaluate_throughput, self_test as throughput_self_test
from chatgpt_operation.controller.state_refresh import StateRefreshError, evaluate as evaluate_state_refresh, self_test as state_refresh_self_test
from chatgpt_operation.controller.scientific_discriminator import ScientificDiscriminatorError, load_plan as load_discriminator_plan, summary as summarize_discriminator_plan
from chatgpt_operation.github.actions_observation import evaluate as evaluate_actions_observation
from chatgpt_operation.github.actions_execution import ActionsExecutionError, evaluate as evaluate_actions_execution, self_test as actions_execution_self_test
from chatgpt_operation.github.actions_runtime import DEFAULT_API_VERSION, ActionsRuntimeError, GitHubActionsTransport, dispatch_workflow, wait_for_dispatch
from chatgpt_operation.controller.action_plan import ActionPlan, ActionPlanError
from chatgpt_operation.github.native_executor import NativeGitHubError, execute_native_github
from chatgpt_operation.github.native_runtime import GitHubNativeTransport, NativeGitHubRuntimeError
from chatgpt_operation.repository.mutation import MutationError, execute_from_files
from chatgpt_operation.source import SourceVerificationError, verify_git_source
from chatgpt_operation.work.manifest import ManifestError
from chatgpt_operation.work.matrix import MatrixError, create_bundle, detect_execution_mode, extract_bundle, plan as matrix_plan, run_aggregate as execute_matrix_aggregate, run_case as execute_matrix_case, self_test as matrix_self_test
from chatgpt_operation.work.runner import execute as execute_work, self_test as work_self_test
from chatgpt_operation.work.scaffold import create_manifest

def persist(path: str | None, result: dict) -> None:
    if path:
        Path(path).write_text(json.dumps(result,indent=2,sort_keys=True)+"\\n",encoding="utf-8")

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

def work_new(args: argparse.Namespace) -> int:
    try:
        path=create_manifest(issue=args.issue,kind=args.kind,title=args.title,root=args.root)
    except ValueError as exc:
        print(f"WORK_SCAFFOLD_ERROR: {exc}",file=sys.stderr)
        return 2
    print(path)
    return 0


def work_run(args: argparse.Namespace) -> int:
    try:
        return execute_work(args)
    except ManifestError as exc:
        print(f"WORK_MANIFEST_ERROR: {exc}",file=sys.stderr)
        return 2


def work_test(args: argparse.Namespace) -> int:
    return work_self_test()



def matrix_route_cmd(args: argparse.Namespace) -> int:
    try:
        result = detect_execution_mode(args.manifest)
    except MatrixError as exc:
        print(f"MATRIX_ROUTE_ERROR: {exc}", file=sys.stderr)
        return 2
    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as handle:
            handle.write("mode=" + str(result["mode"]) + "\\n")
            handle.write("case_count=" + str(result["case_count"]) + "\\n")
    print("MATRIX_ROUTE=PASS")
    print(json.dumps(result, sort_keys=True))
    return 0

def matrix_plan_cmd(args: argparse.Namespace) -> int:
    try:
        result = matrix_plan(
            manifest_path=args.manifest,
            control_root=args.control_root,
            issue=args.issue,
            sequence=args.sequence,
        )
    except MatrixError as exc:
        print(f"MATRIX_MANIFEST_ERROR: {exc}", file=sys.stderr)
        return 2
    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as handle:
            handle.write("matrix=" + json.dumps(result["matrix"], separators=(",", ":")) + "\\n")
            handle.write("max_parallel=" + str(result["max_parallel"]) + "\\n")
            handle.write("prepare_manifest=" + str(result["prepare_manifest"]) + "\\n")
            handle.write("has_aggregate=" + ("true" if result["has_aggregate"] else "false") + "\\n")
    print("MATRIX_PLAN=PASS")
    print(json.dumps(result, sort_keys=True))
    return 0


def matrix_bundle_cmd(args: argparse.Namespace) -> int:
    try:
        result = create_bundle(
            manifest_path=args.manifest,
            control_root=args.control_root,
            workspace=args.workspace,
            issue=args.issue,
            sequence=args.sequence,
            output=args.output,
        )
    except MatrixError as exc:
        print(f"MATRIX_BUNDLE_ERROR: {exc}", file=sys.stderr)
        return 2
    print("MATRIX_BUNDLE=PASS")
    print(json.dumps(result, sort_keys=True))
    return 0


def matrix_extract_cmd(args: argparse.Namespace) -> int:
    try:
        result = extract_bundle(archive_path=args.archive, workspace=args.workspace)
    except MatrixError as exc:
        print(f"MATRIX_EXTRACT_ERROR: {exc}", file=sys.stderr)
        return 2
    print("MATRIX_EXTRACT=PASS")
    print(json.dumps(result, sort_keys=True))
    return 0


def matrix_case_cmd(args: argparse.Namespace) -> int:
    try:
        return execute_matrix_case(args)
    except MatrixError as exc:
        print(f"MATRIX_CASE_ERROR: {exc}", file=sys.stderr)
        return 2


def matrix_aggregate_cmd(args: argparse.Namespace) -> int:
    try:
        return execute_matrix_aggregate(args)
    except MatrixError as exc:
        print(f"MATRIX_AGGREGATE_ERROR: {exc}", file=sys.stderr)
        return 2


def matrix_test_cmd(args: argparse.Namespace) -> int:
    try:
        return matrix_self_test()
    except MatrixError as exc:
        print(f"GOVERNED_MATRIX=HARD_STOP {exc}", file=sys.stderr)
        return 2


def actions_observe(args: argparse.Namespace) -> int:
    try:
        snapshot=json.loads(Path(args.input).read_text(encoding="utf-8"))
        result=evaluate_actions_observation(snapshot)
    except (OSError,json.JSONDecodeError) as exc:
        print(f"GITHUB_ACTIONS_OBSERVATION=HARD_STOP {exc}",file=sys.stderr)
        return 2
    print("GITHUB_ACTIONS_OBSERVATION="+result["status"])
    print(json.dumps(result,sort_keys=True))
    try:
        persist(args.result,result)
    except OSError as exc:
        print(f"GITHUB_ACTIONS_OBSERVATION=HARD_STOP result persistence: {exc}",file=sys.stderr)
        return 3
    return 0


def actions_execution_plan(args: argparse.Namespace) -> int:
    try:
        snapshot=json.loads(Path(args.input).read_text(encoding="utf-8"))
        result=evaluate_actions_execution(snapshot)
    except (OSError,json.JSONDecodeError,ActionsExecutionError) as exc:
        print(f"GITHUB_ACTIONS_EXECUTION=HARD_STOP {exc}",file=sys.stderr)
        return 2
    print("GITHUB_ACTIONS_EXECUTION="+result["status"])
    print(json.dumps(result,sort_keys=True))
    try:
        persist(args.result,result)
    except OSError as exc:
        print(f"GITHUB_ACTIONS_EXECUTION=HARD_STOP result persistence: {exc}",file=sys.stderr)
        return 3
    return 0


def actions_execution_test(args: argparse.Namespace) -> int:
    try:
        return actions_execution_self_test()
    except ActionsExecutionError as exc:
        print(f"GITHUB_ACTIONS_EXECUTION=HARD_STOP {exc}",file=sys.stderr)
        return 2


def _action_inputs(values: list[str]) -> dict[str,str]:
    result={}
    for item in values:
        if "=" not in item:
            raise ValueError("--input must use KEY=VALUE")
        key,value=item.split("=",1)
        if not key or key in result:
            raise ValueError("--input keys must be non-empty and unique")
        result[key]=value
    return result


def actions_dispatch(args: argparse.Namespace) -> int:
    token=os.environ.get(args.token_env)
    if not token:
        print(f"{args.token_env} is required",file=sys.stderr)
        return 2
    try:
        inputs=_action_inputs(args.input)
        transport=GitHubActionsTransport(
            args.repository,
            token,
            api_url=args.api_url,
            api_version=args.api_version,
        )
        correlation_input=None if args.no_correlation_input else args.correlation_input
        receipt=dispatch_workflow(
            transport,
            workflow=args.workflow,
            ref=args.ref,
            inputs=inputs,
            correlation_id=args.correlation_id,
            correlation_input=correlation_input,
        )
        result={"dispatch":receipt}
        if args.wait:
            result["observation"]=wait_for_dispatch(
                transport,
                receipt,
                visibility_grace_seconds=args.visibility_grace,
                expected_head_sha=args.expected_head_sha,
                run_attempt=args.run_attempt,
                timeout_seconds=args.timeout,
                poll_interval_seconds=args.poll_interval,
            )
    except (ActionsRuntimeError,ValueError) as exc:
        print(f"GITHUB_ACTIONS_DISPATCH=HARD_STOP {exc}",file=sys.stderr)
        return 2
    print("GITHUB_ACTIONS_DISPATCH=PASS")
    if "observation" in result:
        print("GITHUB_ACTIONS_OBSERVATION="+result["observation"]["status"])
    print(json.dumps(result,sort_keys=True))
    try:
        persist(args.result,result)
    except OSError as exc:
        print(f"GITHUB_ACTIONS_DISPATCH=HARD_STOP result persistence: {exc}",file=sys.stderr)
        return 3
    return 0


def controller_evaluate(args: argparse.Namespace) -> int:
    try:
        snapshot=json.loads(Path(args.input).read_text(encoding="utf-8"))
        result=evaluate_controller(snapshot)
    except (OSError,json.JSONDecodeError,LifecycleError) as exc:
        print(f"CONTROLLER_LIFECYCLE=HARD_STOP {exc}",file=sys.stderr)
        return 2
    print("CONTROLLER_LIFECYCLE="+result["status"])
    print(json.dumps(result,sort_keys=True))
    try:
        persist(args.result,result)
    except OSError as exc:
        print(f"CONTROLLER_LIFECYCLE=HARD_STOP result persistence: {exc}",file=sys.stderr)
        return 3
    return 0


def controller_test(args: argparse.Namespace) -> int:
    try:
        return controller_self_test()
    except LifecycleError as exc:
        print(f"CONTROLLER_LIFECYCLE=HARD_STOP {exc}",file=sys.stderr)
        return 2


def controller_throughput(args: argparse.Namespace) -> int:
    try:
        snapshot=json.loads(Path(args.input).read_text(encoding="utf-8"))
        result=evaluate_throughput(snapshot)
    except (OSError,json.JSONDecodeError,ThroughputError) as exc:
        print(f"CONTROLLER_THROUGHPUT=HARD_STOP {exc}",file=sys.stderr)
        return 2
    print("CONTROLLER_THROUGHPUT="+result["status"])
    print(json.dumps(result,sort_keys=True))
    try:
        persist(args.result,result)
    except OSError as exc:
        print(f"CONTROLLER_THROUGHPUT=HARD_STOP result persistence: {exc}",file=sys.stderr)
        return 3
    return 0


def controller_throughput_test(args: argparse.Namespace) -> int:
    try:
        return throughput_self_test()
    except ThroughputError as exc:
        print(f"CONTROLLER_THROUGHPUT=HARD_STOP {exc}",file=sys.stderr)
        return 2


def controller_state_refresh(args: argparse.Namespace) -> int:
    try:
        snapshot=json.loads(Path(args.input).read_text(encoding="utf-8"))
        result=evaluate_state_refresh(snapshot)
    except (OSError,json.JSONDecodeError,StateRefreshError) as exc:
        print(f"CONTROLLER_STATE_REFRESH=HARD_STOP {exc}",file=sys.stderr)
        return 2
    print("CONTROLLER_STATE_REFRESH="+result["status"])
    print(json.dumps(result,sort_keys=True))
    try:
        persist(args.result,result)
    except OSError as exc:
        print(f"CONTROLLER_STATE_REFRESH=HARD_STOP result persistence: {exc}",file=sys.stderr)
        return 3
    return 0


def controller_state_refresh_test(args: argparse.Namespace) -> int:
    try:
        return state_refresh_self_test()
    except StateRefreshError as exc:
        print(f"CONTROLLER_STATE_REFRESH=HARD_STOP {exc}",file=sys.stderr)
        return 2


def controller_validate_discriminator_plan(args: argparse.Namespace) -> int:
    try:
        plan = load_discriminator_plan(args.input)
        result = summarize_discriminator_plan(plan)
    except ScientificDiscriminatorError as exc:
        print(f"SCIENTIFIC_DISCRIMINATOR=HARD_STOP {exc}", file=sys.stderr)
        return 2
    print("SCIENTIFIC_DISCRIMINATOR=PLAN_VALID")
    print(json.dumps(result, sort_keys=True))
    try:
        persist(args.result, result)
    except OSError as exc:
        print(f"SCIENTIFIC_DISCRIMINATOR=HARD_STOP result persistence: {exc}", file=sys.stderr)
        return 3
    return 0


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

    w=sub.add_parser("work"); ws=w.add_subparsers(dest="command",required=True)
    wn=ws.add_parser("new")
    wn.add_argument("--issue",required=True,type=int); wn.add_argument("--kind",required=True,choices=["experiments","refactor"])
    wn.add_argument("--title",required=True); wn.add_argument("--root",default="automation/manifests")
    wn.set_defaults(func=work_new)

    wr=ws.add_parser("run")
    wr.add_argument("--kind",required=True,choices=["experiments","refactor"])
    wr.add_argument("--manifest",required=True); wr.add_argument("--control-root",required=True)
    wr.add_argument("--workspace",required=True); wr.add_argument("--base-sha",required=True)
    wr.add_argument("--issue",required=True,type=int); wr.add_argument("--sequence",required=True,type=int)
    wr.add_argument("--results",required=True); wr.set_defaults(func=work_run)

    wt=ws.add_parser("self-test"); wt.set_defaults(func=work_test)


    mx=sub.add_parser("matrix"); mxs=mx.add_subparsers(dest="command",required=True)
    mr=mxs.add_parser("route")
    mr.add_argument("--manifest",required=True)
    mr.add_argument("--github-output")
    mr.set_defaults(func=matrix_route_cmd)
    mp=mxs.add_parser("plan")
    mp.add_argument("--manifest",required=True); mp.add_argument("--control-root",required=True)
    mp.add_argument("--issue",required=True,type=int); mp.add_argument("--sequence",required=True,type=int)
    mp.add_argument("--github-output"); mp.set_defaults(func=matrix_plan_cmd)
    mb=mxs.add_parser("bundle")
    mb.add_argument("--manifest",required=True); mb.add_argument("--control-root",required=True)
    mb.add_argument("--workspace",required=True); mb.add_argument("--issue",required=True,type=int)
    mb.add_argument("--sequence",required=True,type=int); mb.add_argument("--output",required=True)
    mb.set_defaults(func=matrix_bundle_cmd)
    me=mxs.add_parser("extract")
    me.add_argument("--archive",required=True); me.add_argument("--workspace",required=True)
    me.set_defaults(func=matrix_extract_cmd)
    mc=mxs.add_parser("run-case")
    mc.add_argument("--manifest",required=True); mc.add_argument("--control-root",required=True)
    mc.add_argument("--workspace",required=True); mc.add_argument("--base-sha",required=True)
    mc.add_argument("--issue",required=True,type=int); mc.add_argument("--sequence",required=True,type=int)
    mc.add_argument("--case",required=True); mc.add_argument("--results",required=True)
    mc.set_defaults(func=matrix_case_cmd)
    ma=mxs.add_parser("aggregate")
    ma.add_argument("--manifest",required=True); ma.add_argument("--control-root",required=True)
    ma.add_argument("--workspace",required=True); ma.add_argument("--base-sha",required=True)
    ma.add_argument("--issue",required=True,type=int); ma.add_argument("--sequence",required=True,type=int)
    ma.add_argument("--evidence-root",required=True); ma.add_argument("--results",required=True)
    ma.set_defaults(func=matrix_aggregate_cmd)
    mt=mxs.add_parser("self-test"); mt.set_defaults(func=matrix_test_cmd)

    gh=sub.add_parser("github"); ghs=gh.add_subparsers(dest="command",required=True)
    go=ghs.add_parser("observe-actions")
    go.add_argument("--input",required=True); go.add_argument("--result")
    go.set_defaults(func=actions_observe)
    gp=ghs.add_parser("plan-actions-execution")
    gp.add_argument("--input",required=True); gp.add_argument("--result")
    gp.set_defaults(func=actions_execution_plan)
    gt=ghs.add_parser("actions-execution-self-test")
    gt.set_defaults(func=actions_execution_test)
    gd=ghs.add_parser("dispatch-actions")
    gd.add_argument("--repository",default=os.environ.get("GITHUB_REPOSITORY"))
    gd.add_argument("--workflow",required=True); gd.add_argument("--ref",required=True)
    gd.add_argument("--input",action="append",default=[])
    gd.add_argument("--correlation-id"); gd.add_argument("--correlation-input",default="correlation_id")
    gd.add_argument("--no-correlation-input",action="store_true"); gd.add_argument("--wait",action="store_true")
    gd.add_argument("--expected-head-sha"); gd.add_argument("--run-attempt",type=int)
    gd.add_argument("--visibility-grace",type=int,default=60)
    gd.add_argument("--timeout",type=float,default=600); gd.add_argument("--poll-interval",type=float,default=5)
    gd.add_argument("--token-env",default="GITHUB_TOKEN")
    gd.add_argument("--api-url",default=os.environ.get("GITHUB_API_URL","https://api.github.com"))
    gd.add_argument("--api-version",default=DEFAULT_API_VERSION); gd.add_argument("--result")
    gd.set_defaults(func=actions_dispatch)

    ctl=sub.add_parser("controller"); ctls=ctl.add_subparsers(dest="command",required=True)
    ce=ctls.add_parser("evaluate"); ce.add_argument("--input",required=True); ce.add_argument("--result")
    ce.set_defaults(func=controller_evaluate)
    ct=ctls.add_parser("self-test"); ct.set_defaults(func=controller_test)
    ctp=ctls.add_parser("throughput"); ctp.add_argument("--input",required=True); ctp.add_argument("--result")
    ctp.set_defaults(func=controller_throughput)
    ctt=ctls.add_parser("throughput-self-test"); ctt.set_defaults(func=controller_throughput_test)
    csr=ctls.add_parser("state-refresh"); csr.add_argument("--input",required=True); csr.add_argument("--result")
    csr.set_defaults(func=controller_state_refresh)
    csrt=ctls.add_parser("state-refresh-self-test"); csrt.set_defaults(func=controller_state_refresh_test)
    cdp=ctls.add_parser("validate-discriminator-plan"); cdp.add_argument("--input",required=True); cdp.add_argument("--result")
    cdp.set_defaults(func=controller_validate_discriminator_plan)
    return p

def main(argv=None) -> int:
    p=parser(); args=p.parse_args(argv)
    if args.group=="repository" and not args.repository:
        p.error("--repository or GITHUB_REPOSITORY is required")
    if args.group=="github" and args.command in {"dispatch-actions","execute-native"} and not args.repository:
        p.error("--repository or GITHUB_REPOSITORY is required")
    return args.func(args)

if __name__=="__main__": raise SystemExit(main())
