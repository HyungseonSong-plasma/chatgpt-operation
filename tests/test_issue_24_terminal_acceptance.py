from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import os
import subprocess
import sys

from chatgpt_operation.weekly_analysis import analyze_snapshot
from chatgpt_operation.weekly_schedule import phase_for_day
from chatgpt_operation.workflow_failure_ingestion import WorkflowFailureIngestor


def test_issue_24_acceptance_boundaries() -> None:
    ingestor = WorkflowFailureIngestor()
    event = {
        "consumer": "sol-adapter-moose",
        "repository": "org/sol-adapter-moose",
        "workflow": "ci",
        "run_id": "run-1",
        "job": "tests",
        "step": "pytest",
        "head_sha": "abc123",
        "event_type": "workflow_run",
        "occurred_at": "2026-09-28T17:00:00Z",
        "conclusion": "failure",
        "retry_attempt": 1,
        "failure_signature": "dependency-502",
        "dependency_status": "external",
    }
    first = ingestor.ingest(event)
    assert ingestor.ingest(dict(event)) == first
    retry = dict(event, retry_attempt=2)
    assert ingestor.ingest(retry).stable_identity != first.stable_identity
    assert first.failure_category == "EXTERNAL_DEPENDENCY_FAILURE"

    monday = date(2026, 9, 28)
    phases = [phase_for_day(monday + timedelta(days=i)) for i in range(7)]
    assert phases == ["collect"] * 5 + ["analyze", "close"]

    observations = [
        {"identity": "a", "occurred_at": "2026-09-28T17:00:00Z", "consumer": "x", "failure_category": "UNKNOWN"},
        {"identity": "b", "occurred_at": "2026-09-29T17:00:00Z", "consumer": "x", "failure_category": "UNKNOWN"},
    ]
    assert analyze_snapshot(observations) == analyze_snapshot(list(reversed(observations)))


def test_normal_paul_init_does_not_load_weekly_telemetry_data() -> None:
    contract=Path("skills/session-bootstrap/README.md").read_text(encoding="utf-8")
    assert "Do not preload every central skill merely because it exists." in contract
    weekly_runtime_modules=(
        "chatgpt_operation.weekly_raw_evidence",
        "chatgpt_operation.weekly_analysis",
        "chatgpt_operation.workflow_failure_ingestion",
    )
    for module in weekly_runtime_modules:
        assert module.rsplit(".",1)[-1] not in contract

    script = """
import sys
import chatgpt_operation.controller.bootstrap
for name in (
    "chatgpt_operation.weekly_raw_evidence",
    "chatgpt_operation.weekly_analysis",
    "chatgpt_operation.workflow_failure_ingestion",
):
    assert name not in sys.modules, name
"""
    env=dict(os.environ)
    env["PYTHONPATH"]="src"
    subprocess.run([sys.executable,"-c",script],check=True,env=env)
