import json
import os
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from chatgpt_operation.cli import controller_execute_command
from chatgpt_operation.controller.command import ControllerCommand, ControllerCommandKind
from chatgpt_operation.controller.durable_state import encode_state
from chatgpt_operation.controller.execution_gateway import GatewayResult, GatewayStatus
from chatgpt_operation.controller.research import ResearchState


def test_execute_command_cli_materializes_surface_outputs():
    with TemporaryDirectory() as directory:
        root=Path(directory)
        command_path=root/"command.json"
        comments_path=root/"comments.json"
        result_path=root/"gateway.json"
        receipt_path=root/"receipt.json"
        run_id_path=root/"run-id.txt"
        observation_path=root/"observation.json"
        state=ResearchState("r","work",revision=2)
        command=ControllerCommand(
            ControllerCommandKind.OBSERVE_ACTION,
            "a"*64,
            "r",
            2,
        )
        command_path.write_text(
            json.dumps(command.to_dict()),encoding="utf-8"
        )
        comments_path.write_text(
            json.dumps([{"id":1,"body":encode_state(state)}]),encoding="utf-8"
        )
        gateway_result=GatewayResult(
            "action",
            "a"*64,
            GatewayStatus.TERMINAL,
            receipt={"workflow_run_id":99},
            observation={"status":"MATCHED_TERMINAL","conclusion":"success"},
            terminal_run_id=99,
        )
        args=Namespace(
            command=str(command_path),
            comments=str(comments_path),
            repository="o/r",
            token_env="GITHUB_TOKEN",
            api_url="https://api.github.com",
            api_version="2026-03-10",
            result=str(result_path),
            action_receipt_result=str(receipt_path),
            evidence_receipt_result=None,
            diagnostic_receipt_result=None,
            action_run_id_result=str(run_id_path),
            evidence_run_id_result=None,
            diagnostic_run_id_result=None,
            action_terminal_observation_result=str(observation_path),
        )
        with patch.dict(os.environ,{"GITHUB_TOKEN":"secret"}), patch(
            "chatgpt_operation.cli.ExecutionGateway.execute",
            return_value=gateway_result,
        ):
            code=controller_execute_command(args)
        assert code==0
        assert json.loads(result_path.read_text())["status"]=="terminal"
        assert json.loads(receipt_path.read_text())["workflow_run_id"]==99
        assert run_id_path.read_text().strip()=="99"
        assert json.loads(observation_path.read_text())["status"]=="MATCHED_TERMINAL"


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
        args=Namespace(
            command=str(command_path),
            comments=str(comments_path),
            repository="o/r",
            token_env="GITHUB_TOKEN",
            api_url="https://api.github.com",
            api_version="2026-03-10",
            result=None,
            action_receipt_result=None,
            evidence_receipt_result=None,
            diagnostic_receipt_result=None,
            action_run_id_result=None,
            evidence_run_id_result=None,
            diagnostic_run_id_result=None,
            action_terminal_observation_result=None,
        )
        with patch.dict(os.environ,{"GITHUB_TOKEN":"secret"}):
            code=controller_execute_command(args)
        assert code==2
