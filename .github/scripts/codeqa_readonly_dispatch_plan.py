#!/usr/bin/env python3
"""Compile pinned source/target GitHub read-only dispatch from live GitHub facts.

Execution is separate and requires an owner-configured target Actions token.
The script cannot mutate target or originate its own repository permission.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from chatgpt_operation.controller.cross_repo_preflight import compile_codeqa_preflight


def main() -> None:
    ap = argparse.ArgumentParser()
    for key in ("policy", "source-issue", "target-issue", "head-snapshot", "output", "dispatch"):
        ap.add_argument("--" + key, type=Path, required=True)
    ap.add_argument("--actor", required=True)
    ap.add_argument("--run-id", required=True)
    args = ap.parse_args()

    def read(path: Path):
        return json.loads(path.read_text(encoding="utf-8"))

    heads = read(args.head_snapshot)
    if not isinstance(heads, dict) or set(heads) != {
        "observed_source_sha", "observed_target_sha",
        "expected_source_sha", "expected_target_sha",
    }:
        raise ValueError("independent source/target head context missing")
    plan = compile_codeqa_preflight(
        read(args.policy),
        source_issue=read(args.source_issue), target_issue=read(args.target_issue),
        actor=args.actor, source_run_id=args.run_id, **heads,
    )
    data = plan.to_document()
    args.output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    # Exactly the target workflow's documented inputs. Never pass a file
    # change, merge instruction, token or arbitrary user-authored expression.
    dispatch = {
        "ref": plan.target_ref,
        "inputs": {
            "source_run_id": plan.source_run_id,
            "controller_sha": plan.source_head_sha,
            "expected_target_sha": plan.target_head_sha,
            "work_id": plan.work_id,
        },
    }
    args.dispatch.write_text(json.dumps(dispatch, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
    print("SAMUEL_CROSSREPO=READY_FOR_READ_ONLY_DISPATCH"
          + " work_id=" + plan.work_id
          + " source_run=" + plan.source_run_id)


if __name__ == "__main__":
    main()
