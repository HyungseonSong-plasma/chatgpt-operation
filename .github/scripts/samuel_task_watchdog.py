#!/usr/bin/env python3
"""Bounded Samuel liveness check; dispatching the controller is a separate step."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from chatgpt_operation.controller.issue_ingestion import (
    ADMISSION_MARKER, decode_admission_ledger,
)
from chatgpt_operation.controller.task_watchdog import decide_task_wake


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def parse_ledger(pages: object) -> dict:
    # 'gh api --paginate --slurp' yields one array per page, including
    # the empty-list case; default to {} only when no ledger is present.
    if not isinstance(pages, list):
        raise ValueError("malformed Issue #44 comment enumeration")
    if all(isinstance(page, list) for page in pages):
        items = [item for page in pages for item in page]
    elif all(isinstance(item, dict) for item in pages):
        items = pages
    else:
        raise ValueError("malformed comment page")
    matches = [
        item for item in items
        if isinstance(item, dict) and ADMISSION_MARKER in str(item.get("body", ""))
    ]
    if len(matches) > 1:
        raise ValueError("multiple authoritative issue admission ledgers")
    return {} if not matches else decode_admission_ledger(matches[0]["body"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issues", type=Path, required=True)
    parser.add_argument("--comments", type=Path, required=True)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--active-runs", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    issues = read(args.issues)
    if not isinstance(issues, list):
        raise ValueError("open opted-in issue enumeration not an array")
    admitted = parse_ledger(read(args.comments))
    result = read(args.runs)
    active = read(args.active_runs)
    if not isinstance(result, dict) or not isinstance(result.get("workflow_runs"), list):
        raise ValueError("invalid bootstrap workflow run list")
    if not isinstance(active, dict) or not isinstance(active.get("workflow_runs"), list):
        raise ValueError("invalid active bootstrap workflow run list")
    if active.get("total_count", 0) > len(active["workflow_runs"]):
        raise ValueError("active workflow list truncated")
    runs = result["workflow_runs"]
    # Union on exact GitHub run ID. 'active' is fetched separately in case
    # a long-running bootstrap was not in the latest 100.
    ids = {x.get("id") for x in runs if isinstance(x, dict)}
    for x in active["workflow_runs"]:
        if not isinstance(x, dict):
            raise ValueError("malformed active workflow run")
        if x.get("id") not in ids:
            runs.append(x)
            ids.add(x.get("id"))
    # GitHub issues?per_page=100 has no authoritative total_count. At 100,
    # a second page could exist, so this watchdog must not infer completeness.
    decision = decide_task_wake(
        issues=issues,
        admitted_work=admitted,
        bootstrap_runs=runs,
        now=datetime.now(timezone.utc),
        complete_issue_scan=len(issues) < 100,
        complete_active_run_scan=True,
    )
    args.result.write_text(
        json.dumps(decision.to_document(), sort_keys=True, separators=(",", ":"))
        + "\n", encoding="utf-8",
    )
    print("SAMUEL_WATCHDOG=" + decision.status
          + " active_tasks=" + str(len(decision.work_ids))
          + " reason=" + decision.reason)


if __name__ == "__main__":
    main()
