import json
from pathlib import Path

import pytest

from chatgpt_operation.controller.action_lifecycle import ActionLifecycle
from chatgpt_operation.controller.action_plan import ActionPlan, ExecutorKind
from chatgpt_operation.controller.bootstrap import select_controller_work
from chatgpt_operation.controller.diagnostic import (
    enqueue_suspended_action,
    record_action_dispatch,
    record_action_dispatch_intent,
)
from chatgpt_operation.controller.execution import ExecutionResult, ExecutionStatus
from chatgpt_operation.controller.research import ResearchStage, ResearchState
from chatgpt_operation.controller.runtime import (
    _reasoning_audit_context,
    _validate_executable_plan,
)
from chatgpt_operation.controller.terminal_ingestion import (
    TerminalIngestionOutcome,
    TerminalSurface,
    ingest_terminal_artifact,
)
from chatgpt_operation.github.native_executor import NativeGitHubError


HEAD="a"*40
NEW_HEAD="b"*40


def merge_plan(*, expected=HEAD, include_preconditions=True):
    payload={
        "action":"merge_pr",
        "repository":"HyungseonSong-plasma/chatgpt-operation",
        "target":{"number":136,"expected_head_sha":expected},
        "desired_postcondition":{"merged":True},
    }
    if include_preconditions:
        payload["preconditions"]={
            "head_sha":expected,
            "mergeable":True,
            "ci":"success",
        }
    return ActionPlan.from_dict({
        "schema_version":1,
        "research_id":"issue:44",
        "stage":"execute",
        "executor":"github_native",
        "payload":payload,
        "expected_observation":"PR is merged at exact verified head",
    })


def dispatched_state(plan):
    state=ResearchState("issue:44","replan",stage=ResearchStage.EXECUTE)
    enqueue_suspended_action(state,plan)
    record_action_dispatch_intent(
        state,
        plan.idempotency_key,
        workflow="samuel-native-github.yml",
        ref="main",
        requested_at="2026-09-27T22:00:00Z",
        expected_head_sha=HEAD,
    )
    record_action_dispatch(state,plan.idempotency_key,{
        "workflow_path":".github/workflows/samuel-native-github.yml",
        "ref":"main",
        "correlation_id":plan.idempotency_key,
        "workflow_run_id":900,
    })
    return state


def gateway(action_id):
    return {
        "schema_version":1,
        "surface":"action",
        "action_id":action_id,
        "status":"terminal",
        "receipt":None,
        "observation":{
            "status":"MATCHED_TERMINAL",
            "conclusion":"failure",
        },
        "terminal_run_id":900,
    }


def test_merge_plan_requires_closed_world_preconditions_before_queue():
    with pytest.raises((NativeGitHubError, KeyError)):
        _validate_executable_plan(
            merge_plan(include_preconditions=False),
            {
                "open_pull_requests":[
                    {"number":136,"head_sha":HEAD,"base":"main"}
                ]
            },
        )


def test_merge_plan_rejects_stale_observed_pr_head_before_queue():
    with pytest.raises(ValueError,match="expected_head_sha is stale"):
        _validate_executable_plan(
            merge_plan(expected=HEAD),
            {
                "open_pull_requests":[
                    {"number":136,"head_sha":NEW_HEAD,"base":"main"}
                ]
            },
        )


def test_rejected_terminal_retires_action_for_semantic_replan():
    plan=merge_plan()
    state=dispatched_state(plan)
    result=ExecutionResult(
        research_id="issue:44",
        action_id=plan.idempotency_key,
        executor=ExecutorKind.GITHUB_NATIVE,
        status=ExecutionStatus.REJECTED,
        observation="GitHub precondition mismatch; refusing stale mutation",
        retryable=False,
        details={
            "before":{
                "merged":False,
                "head_sha":NEW_HEAD,
                "mergeable":True,
                "ci":"success",
            },
            "required":{
                "head_sha":HEAD,
                "mergeable":True,
                "ci":"success",
            },
            "provenance":{
                "schema_version":1,
                "workflow_run_id":900,
                "run_attempt":1,
                "head_sha":HEAD,
                "action_id":plan.idempotency_key,
            },
        },
    )
    ingestion=ingest_terminal_artifact(
        state,
        surface=TerminalSurface.ACTION,
        run_id=900,
        artifact_text=json.dumps(result.to_dict()),
        gateway_result=gateway(plan.idempotency_key),
    )
    assert ingestion.outcome is TerminalIngestionOutcome.APPLIED
    item=ingestion.proposed_state.action_queue[plan.idempotency_key]
    assert item["status"]==ActionLifecycle.RETIRED.value
    assert item["retirement_result"]["status"]=="rejected"
    assert select_controller_work(
        [],
        action_queue=ingestion.proposed_state.action_queue,
    ) is None


def test_reasoning_audit_context_does_not_duplicate_issue_bodies_or_action_payloads():
    context={
        "goal":"finish issue",
        "locked_decisions":[{"decision_id":"github_execution_authority","statement":"x"*2000}],
        "implementation_gaps":[],
        "durable_state":{
            "revision":36,
            "action_queue":{"x":{"plan":{"payload":{"content":"y"*20000}}}},
        },
        "repository_context":{
            "observed_head_sha":HEAD,
            "open_issues":[{"number":24,"body":"z"*20000}],
            "open_pull_requests":[
                {"number":136,"head_sha":NEW_HEAD,"base":"main","title":"telemetry"}
            ],
            "samuel_branches":[
                {"ref":"refs/heads/samuel/issues-24-43","head_sha":NEW_HEAD}
            ],
        },
    }
    audit=_reasoning_audit_context(context)
    encoded=json.dumps(audit)
    assert len(encoded)<5000
    assert audit["durable_state_revision"]==36
    assert audit["repository"]["open_issue_numbers"]==[24]
    assert audit["repository"]["open_pull_requests"][0]["head_sha"]==NEW_HEAD
    assert "y"*100 not in encoded
    assert "z"*100 not in encoded


def test_bootstrap_planning_write_uses_file_payload_not_shell_body_argument():
    text=Path(".github/workflows/samuel-bootstrap.yml").read_text()
    section=text.split("- name: Persist guarded Issue planning evidence",1)[1].split(
        "- name: Execute root-issued controller command",1
    )[0]
    assert "samuel-planning-request.json" in section
    assert "--input samuel-planning-request.json" in section
    assert '-f body="$body"' not in section
