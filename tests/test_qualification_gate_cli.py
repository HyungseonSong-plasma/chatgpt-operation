import json
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

from chatgpt_operation.cli import controller_qualify


def write(path, payload):
    Path(path).write_text(json.dumps(payload), encoding="utf-8")


def test_controller_qualify_writes_shadow_report_without_execution():
    with TemporaryDirectory() as directory:
        root=Path(directory)
        checks=root/"checks.json"
        metrics=root/"metrics.json"
        result=root/"result.json"
        domains=[
            "reasoning","execution","observation","science",
            "state","provenance","liveness","architecture",
        ]
        write(checks,{
            "schema_version":1,
            "checks":[{
                "schema_version":1,
                "check_id":domain,
                "domain":domain,
                "passed":True,
                "mandatory":True,
                "details":{"source":"deterministic-test"},
            } for domain in domains],
        })
        write(metrics,{
            "schema_version":1,
            "cycles":0,
            "unsafe_action_proposals":0,
            "decision_drifts":0,
            "false_blocked":0,
            "unnecessary_escalations":0,
            "provider_failures":0,
        })
        code=controller_qualify(Namespace(
            checks=str(checks),
            metrics=str(metrics),
            policy="automation/samuel/qualification-policy.json",
            result=str(result),
        ))
        assert code==0
        report=json.loads(result.read_text(encoding="utf-8"))
        assert report["highest_mode"]=="shadow"
        assert report["eligible_modes"]==["shadow"]
        assert report["passed"] is True


def test_controller_qualify_fails_closed_on_invalid_check_envelope():
    with TemporaryDirectory() as directory:
        root=Path(directory)
        checks=root/"checks.json"
        metrics=root/"metrics.json"
        write(checks,{"schema_version":1,"wrong":[]})
        write(metrics,{
            "schema_version":1,
            "cycles":0,
            "unsafe_action_proposals":0,
            "decision_drifts":0,
            "false_blocked":0,
            "unnecessary_escalations":0,
            "provider_failures":0,
        })
        code=controller_qualify(Namespace(
            checks=str(checks),
            metrics=str(metrics),
            policy="automation/samuel/qualification-policy.json",
            result=None,
        ))
        assert code==2
