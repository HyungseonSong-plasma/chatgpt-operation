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
from chatgpt_operation.controller.execution import ExecutionResult, ExecutionStatus
from chatgpt_operation.github.native_executor import NativeGitHubError
from chatgpt_operation.github.execution_kernel import ExecutionKernel, native_runtime_provider
from chatgpt_operation.controller.diagnostic import recovery_authorization_from_dict
from chatgpt_operation.controller.durable_state import (
    apply_dispatch_receipt,
    decode_state,
    load_state_comment,
    state_write_request,
)
from chatgpt_operation.controller.command import ControllerCommand, ControllerCommandError
from chatgpt_operation.controller.execution_gateway import (
    ExecutionGateway,
    ExecutionGatewayError,
    GatewayStatus,
)
from chatgpt_operation.controller.research import ResearchState
from chatgpt_operation.controller.bootstrap import load_pending
from chatgpt_operation.controller.decisions import DecisionRegistry
from chatgpt_operation.controller.reasoning_provider import (
    ProviderUnavailable,
    ReasoningProviderRegistry,
)
from chatgpt_operation.controller.openai_reasoning_provider import OpenAIReasoningProvider
from chatgpt_operation.controller.reasoning import ReasoningNodeError
from chatgpt_operation.controller.runtime import (
    ControllerTrigger,
    SamuelController,
    TriggerKind,
)
from chatgpt_operation.controller.terminal_ingestion import (
    TerminalIngestionError,
    TerminalSurface,
    ingest_terminal_artifact,
)
from chatgpt_operation.controller.state_persistence import (
    StatePersistenceError,
    persist_state_write,
)
from chatgpt_operation.controller.qualification_gate import (
    QualificationCheck,
    QualificationGateError,
    QualificationMetrics,
    evaluate_qualification_gate,
    load_qualification_policy,
)
from chatgpt_operation.github.native_runtime import GitHubNativeTransport, NativeGitHubRuntimeError
from chatgpt_operation.github.native_orchestration import NativeOrchestrationError, dispatch_native_plan
from chatgpt_operation.repository.action_plan_adapter import to_repository_manifest
from chatgpt_operation.repository.mutation import (
    Engine as RepositoryMutationEngine,
    GitHubTransport as RepositoryGitHubTransport,
    MutationError,
    execute_from_files,
    load_json as load_repository_json,
    parse_policy as parse_repository_policy,
)
from chatgpt_operation.source import SourceVerificationError, verify_git_source
from chatgpt_operation.skills.contracts import SkillContractError, validate_catalog
from chatgpt_operation.skills.capability_registry import CapabilityRegistryError, validate_registry
from chatgpt_operation.work.manifest import ManifestError
from chatgpt_operation.work.matrix import MatrixError, create_bundle, detect_execution_mode, extract_bundle, plan as matrix_plan, run_aggregate as execute_matrix_aggregate, run_case as execute_matrix_case, self_test as matrix_self_test
from chatgpt_operation.work.runner import execute as execute_work, self_test as work_self_test
from chatgpt_operation.work.scaffold import create_manifest

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

def repository_execute_plan(args: argparse.Namespace) -> int:
    token=os.environ.get(args.token_env)
    if not token:
        print(f"{args.token_env} is required",file=sys.stderr)
        return 2
    plan=None
    try:
        raw=json.loads(Path(args.input).read_text(encoding="utf-8"))
        plan=ActionPlan.from_dict(raw)
        manifest=to_repository_manifest(
            plan,expected_repository=args.repository
        )
        policy=parse_repository_policy(load_repository_json(args.policy))
        transport=RepositoryGitHubTransport(
            args.repository,token,api_url=args.api_url
        )
        mutation=RepositoryMutationEngine(
            transport,
            repository=args.repository,
            policy=policy,
            current_run_id=args.current_run_id,
        ).execute(manifest)
        status=(
            ExecutionStatus.NOOP
            if mutation["status"]=="NO_MUTATION_NEEDED"
            else ExecutionStatus.PASS
        )
        result=ExecutionResult(
            research_id=plan.research_id,
            action_id=plan.idempotency_key,
            executor=plan.executor,
            status=status,
            observation=(
                "desired repository postcondition already holds"
                if status is ExecutionStatus.NOOP
                else "repository mutation verified by postcondition readback"
            ),
            retryable=False,
            details={"mutation":mutation,"after":mutation},
        )
        rc=0
    except (
        MutationError,
    ) as exc:
        if plan is None:
            print(
                f"REPOSITORY_PLAN_EXECUTION=HARD_STOP {exc}",
                file=sys.stderr,
            )
            return 2
        result=ExecutionResult(
            research_id=plan.research_id,
            action_id=plan.idempotency_key,
            executor=plan.executor,
            status=ExecutionStatus.FAILED,
            observation="repository mutation failed closed",
            retryable=False,
            details={
                "provider":"repository-native",
                "error_type":type(exc).__name__,
                "error":str(exc),
                "available_providers":[],
            },
        )
        rc=2
    except (OSError,json.JSONDecodeError,ActionPlanError,ValueError) as exc:
        print(
            f"REPOSITORY_PLAN_EXECUTION=HARD_STOP {exc}",
            file=sys.stderr,
        )
        return 2
    encoded=result.to_dict()
    try:
        persist(args.result,encoded)
    except OSError as exc:
        print(
            f"REPOSITORY_PLAN_EXECUTION=HARD_STOP result persistence: {exc}",
            file=sys.stderr,
        )
        return 3
    print("REPOSITORY_PLAN_EXECUTION="+result.status.value.upper())
    print(json.dumps(encoded,sort_keys=True))
    return rc


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


def github_native_execute(args: argparse.Namespace) -> int:
    token = os.environ.get(args.token_env)
    if not token:
        print(f"{args.token_env} is required", file=sys.stderr)
        return 2
    try:
        raw = json.loads(Path(args.input).read_text(encoding="utf-8"))
        plan = ActionPlan.from_dict(raw)
        transport = GitHubNativeTransport(
            repository=args.repository,
            token=token,
            api_url=args.api_url,
            api_version=args.api_version,
        )
        if getattr(args, "recovery_state", None):
            state = decode_state(Path(args.recovery_state).read_text(encoding="utf-8"))
            auth_raw = json.loads(Path(args.recovery_authorization).read_text(encoding="utf-8"))
            auth = recovery_authorization_from_dict(auth_raw)
        else:
            state = ResearchState(
                research_id=plan.research_id,
                objective="native execution",
                stage=plan.stage,
            )
            auth = None
        receipt = ExecutionKernel(
            [native_runtime_provider("repository-native", transport)],
            state=state,
        ).execute(plan, recovery_authorization=auth)
        result = receipt.result
    except (OSError, json.JSONDecodeError, ActionPlanError, NativeGitHubError, NativeGitHubRuntimeError) as exc:
        print(f"GITHUB_NATIVE_EXECUTION_ERROR: {exc}", file=sys.stderr)
        return 2
    if bool(getattr(args, "recovery_state", None)) != bool(getattr(args, "recovery_authorization", None)):
        print("GITHUB_NATIVE_EXECUTION_ERROR: recovery state and authorization must be supplied together", file=sys.stderr)
        return 2
    encoded = result.to_dict()
    persist(args.result, encoded)
    print("GITHUB_NATIVE_EXECUTION=" + result.status.value.upper())
    print(json.dumps(encoded, sort_keys=True))
    return 0 if result.status.value in {"pass", "noop"} else 2

def github_native_dispatch(args: argparse.Namespace) -> int:
    token = os.environ.get(args.token_env)
    if not token:
        print(f"{args.token_env} is required", file=sys.stderr)
        return 2
    try:
        raw = json.loads(Path(args.input).read_text(encoding="utf-8"))
        plan = ActionPlan.from_dict(raw)
        transport = GitHubActionsTransport(
            args.repository, token, api_url=args.api_url, api_version=args.api_version
        )
        result = dispatch_native_plan(
            plan,
            transport=transport,
            workflow=args.workflow,
            ref=args.ref,
            expected_head_sha=args.expected_head_sha,
            timeout_seconds=args.timeout,
            poll_interval_seconds=args.poll_interval,
        )
    except (OSError, json.JSONDecodeError, ActionPlanError, ActionsRuntimeError, NativeOrchestrationError) as exc:
        print(f"GITHUB_NATIVE_DISPATCH=HARD_STOP {exc}", file=sys.stderr)
        return 2
    print("GITHUB_NATIVE_DISPATCH=PASS")
    print(json.dumps(result, sort_keys=True))
    try:
        persist(args.result, result)
    except OSError as exc:
        print(f"GITHUB_NATIVE_DISPATCH=HARD_STOP result persistence: {exc}", file=sys.stderr)
        return 3
    return 0


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


def skills_validate(args: argparse.Namespace) -> int:
    try:
        result = validate_catalog(args.catalog)
    except (OSError, json.JSONDecodeError, SkillContractError, ImportError) as exc:
        print(f"SKILL_CONTRACTS=HARD_STOP {exc}", file=sys.stderr)
        return 2
    print("SKILL_CONTRACTS=PASS")
    print(json.dumps(result, sort_keys=True))
    return 0


def skills_validate_capabilities(args: argparse.Namespace) -> int:
    try:
        result = validate_registry(args.registry)
    except (OSError, json.JSONDecodeError, CapabilityRegistryError, ImportError) as exc:
        print(f"CAPABILITY_REGISTRY=HARD_STOP {exc}", file=sys.stderr)
        return 2
    print("CAPABILITY_REGISTRY=PASS")
    print(json.dumps(result, sort_keys=True))
    return 0


def controller_run_cycle(args: argparse.Namespace) -> int:
    try:
        comments=json.loads(Path(args.comments).read_text(encoding="utf-8"))
        issue=json.loads(getattr(args,"issue_json","null"))
        if issue is not None and not isinstance(issue,dict):
            raise ValueError("controller issue payload must be an object or null")
        trigger=ControllerTrigger(
            kind=TriggerKind(args.event_name),
            action=args.event_action or "",
            head_sha=args.head_sha or "",
            ref=args.ref or "",
            executor_ref=args.executor_ref or "",
            executor_head_sha=args.executor_head_sha or "",
        )
        repository_context={}
        context_path=getattr(args,"repository_context",None)
        if context_path:
            repository_context=json.loads(
                Path(context_path).read_text(encoding="utf-8")
            )
            if not isinstance(repository_context,dict):
                raise ValueError("repository reasoning context must be an object")
        mode=os.environ.get("SAMUEL_REASONING_MODE","EXTERNAL").strip().upper()
        if mode in {"AUTO_WITH_AUDIT","AUTO"}:
            reasoning=ReasoningProviderRegistry(
                OpenAIReasoningProvider.from_env(allow_action_plan=True)
            )
        elif mode in {"EXTERNAL","OFF","SHADOW"}:
            reasoning=ReasoningProviderRegistry()
        else:
            raise ValueError("unsupported SAMUEL_REASONING_MODE")
        controller=SamuelController(
            decisions=DecisionRegistry.load(args.decisions),
            reasoning=reasoning,
        )
        cycle=controller.run_cycle(
            trigger,
            comments=comments,
            pending=load_pending(args.pending),
            issue=issue,
            repository_context=repository_context,
        )
        result=cycle.to_dict()
    except (
        OSError,json.JSONDecodeError,ValueError,
        ProviderUnavailable,ReasoningNodeError,
    ) as exc:
        print(f"CONTROLLER_CYCLE=HARD_STOP {exc}",file=sys.stderr)
        return 2
    print("CONTROLLER_CYCLE="+cycle.selected_work["kind"].upper())
    print(json.dumps(result,sort_keys=True))
    try:
        persist(args.result,result)
        persist(args.selected_work_result,cycle.selected_work)
        if cycle.issue_planning is not None:
            persist(args.planning_result,cycle.issue_planning)
        if cycle.admission_write is not None:
            persist(args.admission_write_result,cycle.admission_write)
        if cycle.state_write is not None:
            persist(args.state_write_result,cycle.state_write)
        if cycle.execution_command is not None:
            persist(args.execution_command_result,cycle.execution_command.to_dict())
    except OSError as exc:
        print(f"CONTROLLER_CYCLE=HARD_STOP result persistence: {exc}",file=sys.stderr)
        return 3
    return 0


def controller_execute_command(args: argparse.Namespace) -> int:
    token=os.environ.get(args.token_env)
    if not token:
        print(f"{args.token_env} is required",file=sys.stderr)
        return 2
    try:
        command=ControllerCommand.from_dict(
            json.loads(Path(args.command).read_text(encoding="utf-8"))
        )
        comments=json.loads(Path(args.comments).read_text(encoding="utf-8"))
        if not isinstance(comments,list):
            raise ValueError("controller comments must be a list")
        state=load_state_comment(comments)
        if state is None:
            raise ValueError("durable controller state is required")
        transport=GitHubActionsTransport(
            args.repository,
            token,
            api_url=args.api_url,
            api_version=args.api_version,
        )
        result=ExecutionGateway(transport).execute(command,state=state)
        encoded=result.to_dict()
    except (
        OSError,json.JSONDecodeError,ValueError,ControllerCommandError,
        ExecutionGatewayError,ActionsRuntimeError,NativeOrchestrationError,
    ) as exc:
        print(f"CONTROLLER_COMMAND=HARD_STOP {exc}",file=sys.stderr)
        return 2

    print("CONTROLLER_COMMAND="+result.status.value.upper())
    print(json.dumps(encoded,sort_keys=True))
    try:
        persist(args.result,encoded)
        run_id_paths={
            "action":args.action_run_id_result,
            "evidence":args.evidence_run_id_result,
            "diagnostic":args.diagnostic_run_id_result,
            "corrective":getattr(args,"corrective_run_id_result",None),
        }
        if result.receipt is not None:
            proposed=apply_dispatch_receipt(
                state,
                surface=result.surface,
                action_id=result.action_id,
                receipt=result.receipt,
            )
            persist(args.state_write_result,state_write_request(comments,proposed))
        if result.terminal_run_id is not None:
            target=run_id_paths[result.surface]
            if target:
                Path(target).write_text(str(result.terminal_run_id)+"\n",encoding="utf-8")
        if (
            result.surface=="action"
            and result.status is GatewayStatus.TERMINAL
            and result.observation is not None
        ):
            persist(args.action_terminal_observation_result,result.observation)
    except OSError as exc:
        print(f"CONTROLLER_COMMAND=HARD_STOP output persistence: {exc}",file=sys.stderr)
        return 3
    return 0


def controller_persist_state(args: argparse.Namespace) -> int:
    token=os.environ.get(args.token_env)
    if not token:
        print(f"{args.token_env} is required",file=sys.stderr)
        return 2
    try:
        request_payload=json.loads(Path(args.request).read_text(encoding="utf-8"))
        transport=GitHubActionsTransport(
            args.repository,
            token,
            api_url=args.api_url,
            api_version=args.api_version,
        )
        result=persist_state_write(
            transport,
            issue_number=int(args.issue_number),
            request=request_payload,
        ).to_dict()
    except (
        OSError,json.JSONDecodeError,ValueError,
        StatePersistenceError,ActionsRuntimeError,
    ) as exc:
        print(f"CONTROLLER_STATE_PERSIST=HARD_STOP {exc}",file=sys.stderr)
        return 2
    print("CONTROLLER_STATE_PERSIST=PASS")
    print(json.dumps(result,sort_keys=True))
    try:
        persist(args.result,result)
    except OSError as exc:
        print(
            f"CONTROLLER_STATE_PERSIST=HARD_STOP result persistence: {exc}",
            file=sys.stderr,
        )
        return 3
    return 0


def controller_ingest_terminal(args: argparse.Namespace) -> int:
    try:
        comments=json.loads(Path(args.comments).read_text(encoding="utf-8"))
        if not isinstance(comments,list):
            raise ValueError("controller comments must be a list")
        state=load_state_comment(comments)
        if state is None:
            raise ValueError("durable controller state is required")
        gateway_result=json.loads(
            Path(args.gateway_result).read_text(encoding="utf-8")
        )
        artifact_text=Path(args.artifact).read_text(encoding="utf-8")
        ingestion=ingest_terminal_artifact(
            state,
            surface=TerminalSurface(args.surface),
            run_id=int(args.run_id),
            artifact_text=artifact_text,
            gateway_result=gateway_result,
        )
        result=ingestion.to_dict()
        request=(
            None if ingestion.proposed_state is None
            else state_write_request(comments,ingestion.proposed_state)
        )
    except (
        OSError,json.JSONDecodeError,ValueError,TerminalIngestionError,
    ) as exc:
        print(f"CONTROLLER_TERMINAL=HARD_STOP {exc}",file=sys.stderr)
        return 2
    print("CONTROLLER_TERMINAL="+ingestion.outcome.value.upper())
    print(json.dumps(result,sort_keys=True))
    try:
        persist(args.result,result)
        if request is not None:
            persist(args.state_write_result,request)
    except OSError as exc:
        print(f"CONTROLLER_TERMINAL=HARD_STOP output persistence: {exc}",file=sys.stderr)
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


def controller_qualify(args: argparse.Namespace) -> int:
    try:
        raw_checks=json.loads(Path(args.checks).read_text(encoding="utf-8"))
        if not isinstance(raw_checks,dict) or set(raw_checks)!={"schema_version","checks"}:
            raise QualificationGateError("invalid qualification checks envelope")
        if raw_checks["schema_version"] != 1 or not isinstance(raw_checks["checks"],list):
            raise QualificationGateError("invalid qualification checks envelope")
        checks=[QualificationCheck.from_dict(item) for item in raw_checks["checks"]]
        metrics=QualificationMetrics.from_dict(
            json.loads(Path(args.metrics).read_text(encoding="utf-8"))
        )
        policy=load_qualification_policy(args.policy)
        result=evaluate_qualification_gate(
            checks=checks,metrics=metrics,policy=policy
        ).to_dict()
    except (OSError,json.JSONDecodeError,QualificationGateError,ValueError) as exc:
        print(f"CONTROLLER_QUALIFICATION=HARD_STOP {exc}",file=sys.stderr)
        return 2
    print("CONTROLLER_QUALIFICATION="+(
        "PASS" if result["passed"] else "BLOCKED"
    ))
    print(json.dumps(result,sort_keys=True))
    try:
        persist(args.result,result)
    except OSError as exc:
        print(f"CONTROLLER_QUALIFICATION=HARD_STOP result persistence: {exc}",file=sys.stderr)
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
    ep=rs.add_parser("execute-plan")
    ep.add_argument("--input",required=True)
    ep.add_argument(
        "--policy",
        default="automation/samuel/repository-mutation-policy.json",
    )
    ep.add_argument("--repository",default=os.environ.get("GITHUB_REPOSITORY"))
    ep.add_argument("--token-env",default="GITHUB_TOKEN")
    ep.add_argument(
        "--current-run-id",default=os.environ.get("GITHUB_RUN_ID")
    )
    ep.add_argument(
        "--api-url",
        default=os.environ.get("GITHUB_API_URL","https://api.github.com"),
    )
    ep.add_argument("--result")
    ep.set_defaults(func=repository_execute_plan)

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
    gnd=ghs.add_parser("dispatch-native")
    gnd.add_argument("--input",required=True); gnd.add_argument("--result")
    gnd.add_argument("--repository",default=os.environ.get("GITHUB_REPOSITORY"))
    gnd.add_argument("--workflow",default="samuel-native-github.yml")
    gnd.add_argument("--ref",default="main"); gnd.add_argument("--expected-head-sha")
    gnd.add_argument("--timeout",type=float,default=600); gnd.add_argument("--poll-interval",type=float,default=5)
    gnd.add_argument("--token-env",default="GITHUB_TOKEN")
    gnd.add_argument("--api-url",default=os.environ.get("GITHUB_API_URL","https://api.github.com"))
    gnd.add_argument("--api-version",default=DEFAULT_API_VERSION)
    gnd.set_defaults(func=github_native_dispatch)
    gn=ghs.add_parser("execute-native")
    gn.add_argument("--input",required=True); gn.add_argument("--result")
    gn.add_argument("--recovery-state"); gn.add_argument("--recovery-authorization")
    gn.add_argument("--repository",default=os.environ.get("GITHUB_REPOSITORY"))
    gn.add_argument("--token-env",default="GITHUB_TOKEN")
    gn.add_argument("--api-url",default=os.environ.get("GITHUB_API_URL","https://api.github.com"))
    gn.add_argument("--api-version",default=DEFAULT_API_VERSION)
    gn.set_defaults(func=github_native_execute)

    sk=sub.add_parser("skills"); sks=sk.add_subparsers(dest="command",required=True)
    sv=sks.add_parser("validate-contracts")
    sv.add_argument("--catalog",default="skills/catalog.json")
    sv.set_defaults(func=skills_validate)
    sc=sks.add_parser("validate-capabilities")
    sc.add_argument("--registry",default="skills/capability-registry.json")
    sc.set_defaults(func=skills_validate_capabilities)

    ctl=sub.add_parser("controller"); ctls=ctl.add_subparsers(dest="command",required=True)
    crc=ctls.add_parser("run-cycle")
    crc.add_argument("--comments",required=True)
    crc.add_argument("--pending",default="automation/samuel/bootstrap.json")
    crc.add_argument("--decisions",default="automation/samuel/decisions.json")
    crc.add_argument(
        "--event-name",required=True,
        choices=[item.value for item in TriggerKind],
    )
    crc.add_argument("--event-action",default="")
    crc.add_argument("--issue-json",default="null")
    crc.add_argument("--repository-context")
    crc.add_argument("--head-sha",default="")
    crc.add_argument("--ref",default="")
    crc.add_argument("--executor-ref",default="")
    crc.add_argument("--executor-head-sha",default="")
    crc.add_argument("--result")
    crc.add_argument("--selected-work-result")
    crc.add_argument("--planning-result")
    crc.add_argument("--admission-write-result")
    crc.add_argument("--state-write-result")
    crc.add_argument("--execution-command-result")
    crc.set_defaults(func=controller_run_cycle)

    cec=ctls.add_parser("execute-command")
    cec.add_argument("--command",required=True)
    cec.add_argument("--comments",required=True)
    cec.add_argument("--repository",required=True)
    cec.add_argument("--token-env",default="GITHUB_TOKEN")
    cec.add_argument("--api-url",default="https://api.github.com")
    cec.add_argument("--api-version",default=DEFAULT_API_VERSION)
    cec.add_argument("--result")
    cec.add_argument("--state-write-result")
    cec.add_argument("--action-run-id-result")
    cec.add_argument("--evidence-run-id-result")
    cec.add_argument("--diagnostic-run-id-result")
    cec.add_argument("--corrective-run-id-result")
    cec.add_argument("--action-terminal-observation-result")
    cec.set_defaults(func=controller_execute_command)

    cps=ctls.add_parser("persist-state")
    cps.add_argument("--request",required=True)
    cps.add_argument("--repository",required=True)
    cps.add_argument("--issue-number",type=int,default=44)
    cps.add_argument("--token-env",default="GITHUB_TOKEN")
    cps.add_argument("--api-url",default="https://api.github.com")
    cps.add_argument("--api-version",default=DEFAULT_API_VERSION)
    cps.add_argument("--result")
    cps.set_defaults(func=controller_persist_state)

    cit=ctls.add_parser("ingest-terminal")
    cit.add_argument("--surface",required=True,choices=[x.value for x in TerminalSurface])
    cit.add_argument("--run-id",required=True,type=int)
    cit.add_argument("--artifact",required=True)
    cit.add_argument("--gateway-result",required=True)
    cit.add_argument("--comments",required=True)
    cit.add_argument("--result")
    cit.add_argument("--state-write-result")
    cit.set_defaults(func=controller_ingest_terminal)
    ce=ctls.add_parser("evaluate"); ce.add_argument("--input",required=True); ce.add_argument("--result")
    ce.set_defaults(func=controller_evaluate)
    cq=ctls.add_parser("qualify")
    cq.add_argument("--checks",required=True)
    cq.add_argument("--metrics",required=True)
    cq.add_argument("--policy",default="automation/samuel/qualification-policy.json")
    cq.add_argument("--result")
    cq.set_defaults(func=controller_qualify)
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
    if args.group=="github" and args.command in {"dispatch-actions","dispatch-native","execute-native"} and not args.repository:
        p.error("--repository or GITHUB_REPOSITORY is required")
    return args.func(args)

if __name__=="__main__": raise SystemExit(main())
