from chatgpt_operation.controller.action_plan import ActionPlan, ExecutorKind
from chatgpt_operation.controller.diagnostic import (
    attach_source_plan,
    record_corrective_dispatch,
    record_corrective_dispatch_intent,
)
from chatgpt_operation.controller.durable_state import (
    DurableStateError,
    apply_corrective_execution_result,
)
from chatgpt_operation.controller.execution import ExecutionResult, ExecutionStatus
from chatgpt_operation.controller.research import ResearchStage, ResearchState


HEAD="b"*40


def plan():
    return ActionPlan.from_dict({
        "schema_version":1,
        "research_id":"r",
        "stage":"execute",
        "executor":"github_native",
        "payload":{
            "action":"comment_issue",
            "repository":"o/r",
            "target":{"issue_number":44},
            "preconditions":{"state":"open"},
            "desired_postcondition":{"comment_present":True},
        },
        "expected_observation":"verified",
    })


def dispatched_state():
    p=plan()
    s=ResearchState(
        "r","finish",stage=ResearchStage.EXECUTE,
        action_queue={p.idempotency_key:{
            "status":"suspended",
            "plan":{
                "schema_version":1,"research_id":"r","stage":"execute",
                "executor":"github_native","payload":p.payload,
                "expected_observation":"verified","decision_risk":None,
            },
        }},
        diagnostic_recoveries={p.idempotency_key:{
            "status":"open",
            "fingerprint":[],
            "failure":{"details":{
                "provider":"primary",
                "available_providers":["fallback","other"],
            }},
            "root_cause":"provider failure",
            "corrective_action":"retry through eligible provider=fallback",
            "corrective_provider":"fallback",
            "resolution_evidence":None,
        }},
        revision=7,
    )
    attach_source_plan(s,p.idempotency_key,p)
    _,dispatch_id=record_corrective_dispatch_intent(
        s,p.idempotency_key,workflow="samuel-native-github.yml",
        ref="feature",requested_at="2026-09-27T20:00:00Z",
        expected_head_sha=HEAD,
    )
    record_corrective_dispatch(s,p.idempotency_key,{
        "workflow_path":".github/workflows/samuel-native-github.yml",
        "ref":"feature","correlation_id":dispatch_id,"workflow_run_id":99,
    })
    return p,s,dispatch_id


def result(p,status,run_id=99,verified=True):
    details={
        "provenance":{
            "schema_version":1,"workflow_run_id":run_id,"run_attempt":1,
            "head_sha":HEAD,"action_id":p.idempotency_key,
        },
    }
    if status is ExecutionStatus.PASS and verified:
        details["after"]={"comment_present":True}
    if status is ExecutionStatus.NOOP and verified:
        details["before"]={"comment_present":True}
    if status is ExecutionStatus.FAILED:
        details.update({"error_type":"HTTPError","provider_status":"403"})
    return ExecutionResult(
        research_id="r",action_id=p.idempotency_key,
        executor=ExecutorKind.GITHUB_NATIVE,status=status,
        observation="corrective execution result",
        retryable=status is ExecutionStatus.FAILED,
        details=details,
    )


def test_verified_corrective_success_resolves_and_resumes_source_action_atomically():
    p,s,_=dispatched_state()
    before=s.revision
    proposed=apply_corrective_execution_result(
        s,p.idempotency_key,result(p,ExecutionStatus.PASS)
    )
    assert s.diagnostic_recoveries[p.idempotency_key]["status"]=="open"
    recovery=proposed.diagnostic_recoveries[p.idempotency_key]
    assert recovery["status"]=="resolved"
    assert "corrective_dispatch" not in recovery
    assert proposed.action_queue[p.idempotency_key]["status"]=="pending"
    assert proposed.revision==before+1


def test_corrective_failure_records_provider_evidence_and_returns_to_provider_selection():
    p,s,_=dispatched_state()
    before=s.revision
    proposed=apply_corrective_execution_result(
        s,p.idempotency_key,result(p,ExecutionStatus.FAILED)
    )
    recovery=proposed.diagnostic_recoveries[p.idempotency_key]
    assert recovery["status"]=="open"
    assert recovery["corrective_action"] is None
    assert "corrective_provider" not in recovery
    assert "corrective_dispatch" not in recovery
    assert recovery["failure"]["details"]["provider_failures"][0]["provider"]=="fallback"
    assert proposed.action_queue[p.idempotency_key]["status"]=="suspended"
    assert proposed.revision==before+1


def test_unverified_corrective_pass_is_provider_failure_not_resolution():
    p,s,_=dispatched_state()
    proposed=apply_corrective_execution_result(
        s,p.idempotency_key,result(p,ExecutionStatus.PASS,verified=False)
    )
    recovery=proposed.diagnostic_recoveries[p.idempotency_key]
    assert recovery["status"]=="open"
    assert recovery["corrective_action"] is None
    assert proposed.action_queue[p.idempotency_key]["status"]=="suspended"


def test_corrective_result_from_foreign_run_is_rejected():
    p,s,_=dispatched_state()
    try:
        apply_corrective_execution_result(
            s,p.idempotency_key,result(p,ExecutionStatus.PASS,run_id=100)
        )
    except Exception as exc:
        assert "workflow_run_id mismatch" in str(exc)
    else:
        raise AssertionError("foreign corrective workflow result must fail closed")
