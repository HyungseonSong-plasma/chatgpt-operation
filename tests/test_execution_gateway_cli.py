import json
import os
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from chatgpt_operation.cli import controller_execute_command
from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.controller.command import ControllerCommand, ControllerCommandKind
from chatgpt_operation.controller.diagnostic import (
    enqueue_suspended_action,
    record_action_dispatch_intent,
)
from chatgpt_operation.controller.durable_state import decode_state, encode_state
from chatgpt_operation.controller.execution_gateway import GatewayResult, GatewayStatus
from chatgpt_operation.controller.research import ResearchStage, ResearchState


def base_args(root, command_path, comments_path):
    return dict(
        command=str(command_path),
        comments=str(comments_path),
        repository="o/r",
        token_env="GITHUB_TOKEN",
        api_url="https://api.github.com",
        api_version="2026-03-10",
        result=str(root/"gateway.json"),
        state_write_result=None,
        action_run_id_result=None,
        evidence_run_id_result=None,
        diagnostic_run_id_result=None,
        action_terminal_observation_result=None,
    )


def action_plan():
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


def test_execute_command_cli_materializes_terminal_outputs():
    with TemporaryDirectory() as directory:
        root=Path(directory)
        command_path=root/"command.json"
        comments_path=root/"comments.json"
        run_id_path=root/"run-id.txt"
        observation_path=root/"observation.json"
        state=ResearchState("r","work",revision=2)
        command=ControllerCommand(
            ControllerCommandKind.OBSERVE_ACTION,
            "a"*64,
            "r",
            2,
        )
        command_path.write_text(json.dumps(command.to_dict()),encoding="utf-8")
        comments_path.write_text(
            json.dumps([{"id":1,"body":encode_state(state)}]),encoding="utf-8"
        )
        gateway_result=GatewayResult(
            "action",
            "a"*64,
            GatewayStatus.TERMINAL,
            observation={"status":"MATCHED_TERMINAL","conclusion":"success"},
            terminal_run_id=99,
        )
        values=base_args(root,command_path,comments_path)
        values["action_run_id_result"]=str(run_id_path)
        values["action_terminal_observation_result"]=str(observation_path)
        with patch.dict(os.environ,{"GITHUB_TOKEN":"secret"}), patch(
            "chatgpt_operation.cli.ExecutionGateway.execute",
            return_value=gateway_result,
        ):
            code=controller_execute_command(Namespace(**values))
        assert code==0
        assert json.loads((root/"gateway.json").read_text())["status"]=="terminal"
        assert run_id_path.read_text().strip()=="99"
        assert json.loads(observation_path.read_text())["status"]=="MATCHED_TERMINAL"


def test_execute_command_cli_turns_receipt_into_one_state_write():
    with TemporaryDirectory() as directory:
        root=Path(directory)
        command_path=root/"command.json"
        comments_path=root/"comments.json"
        state_write_path=root/"state-write.json"
        p=action_plan()
        state=ResearchState("r","work",stage=ResearchStage.EXECUTE)
        enqueue_suspended_action(state,p)
        record_action_dispatch_intent(
            state,p.idempotency_key,
            workflow="samuel-native-github.yml",
            ref="main",
            requested_at="2026-09-27T20:00:00Z",
            expected_head_sha="b"*40,
        )
        command=ControllerCommand(
            ControllerCommandKind.DISPATCH_ACTION,
            p.idempotency_key,
            "r",
            state.revision,
        )
        command_path.write_text(json.dumps(command.to_dict()),encoding="utf-8")
        comments_path.write_text(
            json.dumps([{"id":1,"body":encode_state(state)}]),encoding="utf-8"
        )
        receipt={
            "workflow_path":".github/workflows/samuel-native-github.yml",
            "ref":"main",
            "correlation_id":p.idempotency_key,
            "workflow_run_id":99,
        }
        gateway_result=GatewayResult(
            "action",p.idempotency_key,GatewayStatus.RECEIPT,receipt=receipt
        )
        values=base_args(root,command_path,comments_path)
        values["state_write_result"]=str(state_write_path)
        with patch.dict(os.environ,{"GITHUB_TOKEN":"secret"}), patch(
            "chatgpt_operation.cli.ExecutionGateway.execute",
            return_value=gateway_result,
        ):
            code=controller_execute_command(Namespace(**values))
        assert code==0
        request=json.loads(state_write_path.read_text())
        proposed=decode_state(request["body"])
        item=proposed.action_queue[p.idempotency_key]
        assert item["status"]=="dispatched"
        assert item["dispatch_receipt"]==receipt
        assert request["expected_previous_revision"]==state.revision
        assert request["expected_revision"]==state.revision+1


def test_execute_command_cli_requires_durable_state():
    with TemporaryDirectory() as directory:
        root=Path(directory)
        command_path=root/"command.json"
        comments_path=root/"comments.json"
        command=ControllerCommand(
            ControllerCommandKind.DISPATCH_ACTION,
            "a"*64,
            "r",
            0,
        )
        command_path.write_text(json.dumps(command.to_dict()),encoding="utf-8")
        comments_path.write_text("[]",encoding="utf-8")
        values=base_args(root,command_path,comments_path)
        with patch.dict(os.environ,{"GITHUB_TOKEN":"secret"}):
            code=controller_execute_command(Namespace(**values))
        assert code==2
