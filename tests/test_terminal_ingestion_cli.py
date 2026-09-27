import json
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

from chatgpt_operation.cli import controller_ingest_terminal
from chatgpt_operation.controller.action_plan import ActionPlan, ExecutorKind
from chatgpt_operation.controller.diagnostic import (
    enqueue_suspended_action,
    record_action_dispatch,
    record_action_dispatch_intent,
)
from chatgpt_operation.controller.durable_state import decode_state, encode_state
from chatgpt_operation.controller.execution import ExecutionResult, ExecutionStatus
from chatgpt_operation.controller.research import ResearchStage, ResearchState


HEAD="b"*40


def test_ingest_terminal_cli_emits_one_state_write():
    with TemporaryDirectory() as directory:
        root=Path(directory)
        p=ActionPlan.from_dict({
            "schema_version":1,"research_id":"r","stage":"execute",
            "executor":"github_native",
            "payload":{
                "action":"comment_issue","repository":"o/r",
                "target":{"issue_number":44},
                "preconditions":{"state":"open"},
                "desired_postcondition":{"comment_present":True},
            },
            "expected_observation":"verified",
        })
        state=ResearchState("r","work",stage=ResearchStage.EXECUTE)
        enqueue_suspended_action(state,p)
        record_action_dispatch_intent(
            state,p.idempotency_key,
            workflow="samuel-native-github.yml",ref="main",
            requested_at="2026-09-27T20:00:00Z",expected_head_sha=HEAD,
        )
        record_action_dispatch(state,p.idempotency_key,{
            "workflow_path":".github/workflows/samuel-native-github.yml",
            "ref":"main","correlation_id":p.idempotency_key,
            "workflow_run_id":99,
        })
        result=ExecutionResult(
            research_id="r",action_id=p.idempotency_key,
            executor=ExecutorKind.GITHUB_NATIVE,
            status=ExecutionStatus.PASS,
            observation="verified",
            details={
                "after":{"comment_present":True},
                "provenance":{
                    "schema_version":1,"workflow_run_id":99,"run_attempt":1,
                    "head_sha":HEAD,"action_id":p.idempotency_key,
                },
            },
        )
        comments=root/"comments.json"
        artifact=root/"artifact.json"
        gateway=root/"gateway.json"
        state_write=root/"state-write.json"
        summary=root/"summary.json"
        comments.write_text(
            json.dumps([{"id":1,"body":encode_state(state)}]),encoding="utf-8"
        )
        artifact.write_text(json.dumps(result.to_dict()),encoding="utf-8")
        gateway.write_text(json.dumps({
            "schema_version":1,"surface":"action",
            "action_id":p.idempotency_key,"status":"terminal",
            "receipt":None,
            "observation":{"status":"MATCHED_TERMINAL","conclusion":"success"},
            "terminal_run_id":99,
        }),encoding="utf-8")
        code=controller_ingest_terminal(Namespace(
            surface="action",run_id=99,artifact=str(artifact),
            gateway_result=str(gateway),comments=str(comments),
            result=str(summary),state_write_result=str(state_write),
        ))
        assert code==0
        request=json.loads(state_write.read_text())
        proposed=decode_state(request["body"])
        assert proposed.action_queue[p.idempotency_key]["status"]=="complete"
        assert json.loads(summary.read_text())["outcome"]=="applied"
