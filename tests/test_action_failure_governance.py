from chatgpt_operation.controller.action_plan import ActionPlan, ExecutorKind
from chatgpt_operation.controller.diagnostic import (
    enqueue_suspended_action, record_action_dispatch, record_action_dispatch_intent,
)
from chatgpt_operation.controller.durable_state import (
    apply_action_failure,
    retire_orphaned_repository_policy_failures,
)
from chatgpt_operation.controller.execution import ExecutionResult, ExecutionStatus
from chatgpt_operation.controller.research import ResearchStage, ResearchState


HEAD_SHA="b"*40


def make_plan():
    return ActionPlan.from_dict({"schema_version":1,"research_id":"r","stage":"execute",
        "executor":"github_native","payload":{"action":"comment_issue","repository":"o/r",
        "target":{"issue_number":44},"preconditions":{"state":"open"},
        "desired_postcondition":{"comment_present":True}},"expected_observation":"verified"})


def repository_plan():
    return ActionPlan.from_dict({
        "schema_version":1,
        "research_id":"r",
        "stage":"implement",
        "executor":"repository_mutation",
        "payload":{
            "schema_version":1,
            "repository":"HyungseonSong-plasma/chatgpt-operation",
            "resource":"file",
            "action":"create",
            "target":{
                "path":".github/workflows/paul-weekly-maintenance.yml",
                "branch":"samuel/issue-24",
            },
            "expected":{"absent":True},
            "desired":{"content":"name: Paul weekly maintenance\n"},
            "commit_message":"add workflow",
        },
        "expected_observation":"workflow exists",
    })


def dispatch(s,p,run_id):
    workflow=(
        "samuel-repository-mutation.yml"
        if p.executor is ExecutorKind.REPOSITORY_MUTATION
        else "samuel-native-github.yml"
    )
    record_action_dispatch_intent(
        s,p.idempotency_key,workflow=workflow,ref="main",
        requested_at=f"2026-09-27T12:{run_id % 60:02d}:00Z",expected_head_sha=HEAD_SHA,
    )
    record_action_dispatch(s,p.idempotency_key,{
        "workflow_path":".github/workflows/"+workflow,
        "ref":"main","correlation_id":p.idempotency_key,"workflow_run_id":run_id,
    })


def failed(p,run_id,retryable=True):
    return ExecutionResult(research_id="r",action_id=p.idempotency_key,
        executor=ExecutorKind.GITHUB_NATIVE,status=ExecutionStatus.FAILED,
        observation="provider failed",retryable=retryable,
        details={"provider":"native","error_type":"HTTPError","provider_status":"403",
                 "provenance":{"schema_version":1,"workflow_run_id":run_id,"run_attempt":1,
                               "head_sha":HEAD_SHA,"action_id":p.idempotency_key}})


def test_first_retryable_failure_returns_action_to_clean_pending_state():
    p=make_plan(); s=ResearchState("r","finish",stage=ResearchStage.EXECUTE)
    enqueue_suspended_action(s,p); dispatch(s,p,99)
    once=apply_action_failure(s,failed(p,99))
    item=once.action_queue[p.idempotency_key]
    assert item["status"]=="pending"
    assert "dispatch_intent" not in item
    assert "dispatch_receipt" not in item


def test_second_identical_retryable_failure_suspends_and_opens_diagnosis():
    p=make_plan(); s=ResearchState("r","finish",stage=ResearchStage.EXECUTE)
    enqueue_suspended_action(s,p); dispatch(s,p,99)
    once=apply_action_failure(s,failed(p,99))
    dispatch(once,p,100)
    twice=apply_action_failure(once,failed(p,100))
    assert twice.action_queue[p.idempotency_key]["status"]=="suspended"
    recovery=twice.diagnostic_recoveries[p.idempotency_key]
    assert recovery["status"]=="open"
    assert recovery["source_plan"]["payload"]==p.payload


def test_legacy_nonretryable_kernel_failure_returns_to_pending():
    p=make_plan(); s=ResearchState("r","finish",stage=ResearchStage.EXECUTE)
    enqueue_suspended_action(s,p); dispatch(s,p,101)
    result=ExecutionResult(
        research_id="r",
        action_id=p.idempotency_key,
        executor=ExecutorKind.GITHUB_NATIVE,
        status=ExecutionStatus.FAILED,
        observation="native execution kernel failed closed",
        retryable=False,
        details={
            "provider":"repository-native",
            "error_type":"ExecutionKernelError",
            "error":"Resource not accessible by integration",
            "available_providers":[],
            "provenance":{
                "schema_version":1,
                "workflow_run_id":101,
                "run_attempt":1,
                "head_sha":HEAD_SHA,
                "action_id":p.idempotency_key,
            },
        },
    )
    recovered=apply_action_failure(s,result)
    item=recovered.action_queue[p.idempotency_key]
    assert item["status"]=="pending"
    assert "dispatch_intent" not in item
    assert "dispatch_receipt" not in item
    evidence=recovered.execution_results[p.idempotency_key]
    assert evidence["details"]["governance_retryable"] is True


def test_repository_policy_failure_is_rejected_for_replan_not_suspended():
    p=repository_plan()
    s=ResearchState("r","finish",stage=ResearchStage.EXECUTE)
    enqueue_suspended_action(s,p)
    dispatch(s,p,102)
    result=ExecutionResult(
        research_id="r",
        action_id=p.idempotency_key,
        executor=ExecutorKind.REPOSITORY_MUTATION,
        status=ExecutionStatus.FAILED,
        observation="repository mutation failed closed",
        retryable=False,
        details={
            "provider":"repository-native",
            "error_type":"PolicyError",
            "error":"file path denied: .github/workflows/paul-weekly-maintenance.yml",
            "available_providers":[],
            "provenance":{
                "schema_version":1,
                "workflow_run_id":102,
                "run_attempt":1,
                "head_sha":HEAD_SHA,
                "action_id":p.idempotency_key,
            },
        },
    )
    proposed=apply_action_failure(s,result)
    item=proposed.action_queue[p.idempotency_key]
    assert item["status"]=="rejected"
    assert item["rejection_reason"]=="deterministic_repository_policy_replan"
    assert proposed.diagnostic_recoveries=={}
    assert proposed.execution_results[p.idempotency_key]["details"][
        "governance_retryable"
    ] is False


def test_legacy_orphan_suspended_policy_failure_is_migrated_to_rejected():
    p=repository_plan()
    s=ResearchState("r","finish",stage=ResearchStage.EXECUTE,revision=17)
    enqueue_suspended_action(s,p)
    s.action_queue[p.idempotency_key]["status"]="suspended"
    s.execution_results[p.idempotency_key]={
        "schema_version":1,
        "research_id":"r",
        "action_id":p.idempotency_key,
        "executor":"repository_mutation",
        "status":"failed",
        "observation":"repository mutation failed closed",
        "retryable":False,
        "details":{
            "provider":"repository-native",
            "error_type":"PolicyError",
            "error":"file path denied",
            "governance_retryable":False,
        },
    }
    proposed=retire_orphaned_repository_policy_failures(s)
    assert proposed is not None
    assert s.action_queue[p.idempotency_key]["status"]=="suspended"
    item=proposed.action_queue[p.idempotency_key]
    assert item["status"]=="rejected"
    assert item["rejection_reason"]=="deterministic_repository_policy_replan"
    assert proposed.revision==18


def test_orphan_suspended_unknown_failure_remains_fail_closed():
    p=repository_plan()
    s=ResearchState("r","finish",stage=ResearchStage.EXECUTE,revision=17)
    enqueue_suspended_action(s,p)
    s.action_queue[p.idempotency_key]["status"]="suspended"
    s.execution_results[p.idempotency_key]={
        "schema_version":1,
        "research_id":"r",
        "action_id":p.idempotency_key,
        "executor":"repository_mutation",
        "status":"failed",
        "observation":"unknown failure",
        "retryable":False,
        "details":{
            "provider":"repository-native",
            "error_type":"UnknownFailure",
            "governance_retryable":False,
        },
    }
    assert retire_orphaned_repository_policy_failures(s) is None
    assert s.action_queue[p.idempotency_key]["status"]=="suspended"


def test_failure_from_foreign_workflow_is_rejected():
    p=make_plan(); s=ResearchState("r","finish",stage=ResearchStage.EXECUTE)
    enqueue_suspended_action(s,p); dispatch(s,p,99)
    try:
        apply_action_failure(s,failed(p,100))
    except Exception as exc:
        assert "workflow_run_id mismatch" in str(exc)
    else:
        raise AssertionError("foreign workflow failure must fail closed")
