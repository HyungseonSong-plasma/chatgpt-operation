import json
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

from chatgpt_operation.cli import controller_run_cycle
from chatgpt_operation.controller.issue_ingestion import encode_admission_ledger


def test_controller_run_cycle_cli_emits_selected_and_planning_artifacts():
    with TemporaryDirectory() as directory:
        root=Path(directory)
        comments=root/"comments.json"
        pending=root/"pending.json"
        result=root/"cycle.json"
        selected=root/"selected.json"
        planning=root/"planning.json"
        admission_write=root/"admission-write.json"
        state_write=root/"state-write.json"
        work={
            "issue:44":{
                "work_id":"issue:44",
                "issue_number":44,
                "title":"Samuel OS",
                "body":"finish composition root",
                "html_url":"https://github.com/o/r/issues/44",
                "status":"admitted",
            }
        }
        comments.write_text(json.dumps([
            {"id":7,"body":encode_admission_ledger(work)}
        ]),encoding="utf-8")
        pending.write_text(
            json.dumps({"schema_version":1,"work":[]}),
            encoding="utf-8",
        )
        code=controller_run_cycle(Namespace(
            comments=str(comments),
            pending=str(pending),
            decisions="automation/samuel/decisions.json",
            event_name="workflow_dispatch",
            event_action="",
            head_sha="a"*40,
            ref="refs/heads/main",
            result=str(result),
            selected_work_result=str(selected),
            planning_result=str(planning),
            admission_write_result=str(admission_write),
            state_write_result=str(state_write),
        ))
        assert code==0
        cycle=json.loads(result.read_text(encoding="utf-8"))
        selected_payload=json.loads(selected.read_text(encoding="utf-8"))
        planning_payload=json.loads(planning.read_text(encoding="utf-8"))
        assert cycle["selected_work"]==selected_payload
        assert selected_payload["kind"]=="reasoning_required"
        assert planning_payload["outcome"]=="reasoning_required"
        assert planning_payload["action_plan"] is None
        admission_payload=json.loads(admission_write.read_text(encoding="utf-8"))
        assert admission_payload["comment_id"]==7
        assert cycle["admission_write"]==admission_payload
        assert not state_write.exists()


def test_controller_run_cycle_cli_fails_closed_on_bad_comments():
    with TemporaryDirectory() as directory:
        root=Path(directory)
        comments=root/"comments.json"
        pending=root/"pending.json"
        comments.write_text("{}",encoding="utf-8")
        pending.write_text(
            json.dumps({"schema_version":1,"work":[]}),
            encoding="utf-8",
        )
        code=controller_run_cycle(Namespace(
            comments=str(comments),
            pending=str(pending),
            decisions="automation/samuel/decisions.json",
            event_name="workflow_dispatch",
            event_action="",
            head_sha="",
            ref="",
            result=None,
            selected_work_result=None,
            planning_result=None,
            admission_write_result=None,
            state_write_result=None,
        ))
        assert code==2
