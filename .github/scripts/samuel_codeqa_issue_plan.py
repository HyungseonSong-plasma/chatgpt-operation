#!/usr/bin/env python3
"""Read-only source-owned Issue #92 ingress into Samuel typed reasoning.

No target mutations, no PR creation or auto-merges. Errors produce explicit
HARD_STOP receipts rather than manufactured action-plan success.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from codeqa_governed_write import API, POLICY_FILE, SOURCE, TARGET, _identity_env
from chatgpt_operation.controller.cross_repository_issue_admission import (
    CrossRepositoryAdmissionError,
    admit_cross_repository_issue,
    serialise_admission,
)

RESULT_FILE = Path("samuel-codeqa-issue-admission.json")

# Constant-only error codes: never upload token, response body or untrusted
# exception text. The previous live failure recorded only the exception type.
_SAFE_ADMISSION_REASONS = {
    "target acceptance criteria absent": "TARGET_ACCEPTANCE_SECTION_MISSING",
    "ambiguous acceptance section": "AMBIGUOUS_ACCEPTANCE_SECTION",
    "unverified Controller planning workflow": "UNVERIFIED_SOURCE_WORKFLOW",
    "live GitHub Issue identity invalid": "LIVE_ISSUE_IDENTITY_INVALID",
    "untrusted executable plan in admission": "UNTRUSTED_ACTION_PLAN_BLOCKED",
}


def safe_admission_reason(exc: Exception) -> str:
    if isinstance(exc, CrossRepositoryAdmissionError):
        message = str(exc)
        if message.startswith("target identity/readback denied:"):
            return "TARGET_ATTESTATION_DENIED"
        return _SAFE_ADMISSION_REASONS.get(message, "OTHER_ADMISSION_ERROR")
    return "NON_ADMISSION_ERROR"


def run() -> dict:
    run_id, sha = _identity_env()
    policy = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
    source = API(os.environ.get("GITHUB_TOKEN", ""))
    # Distinct codeQA-only token is used ONLY for target metadata readback.
    target = API(os.environ.get("SAMUEL_CODEQA_WRITE_TOKEN", ""))
    src = "/repos/" + SOURCE
    dst = "/repos/" + TARGET
    snapshot, context = admit_cross_repository_issue(
        source_run=source.get(src + "/actions/runs/" + str(run_id)),
        source_run_id=run_id,
        controller_sha=sha,
        source_issue=source.get(src + "/issues/220"),
        target_issue=target.get(dst + "/issues/92"),
        policy=policy,
        target_reader=target,
    )
    document = json.loads(serialise_admission(snapshot, context))
    if document["snapshot"]["action_plan"] is not None:
        raise ValueError("unreviewed target mutation plan prohibited")
    return document


def main() -> int:
    try:
        payload = run()
        rc = 0
    except Exception as exc:
        payload = {
            "schema_version": 1,
            "status": "HARD_STOP",
            "error_type": type(exc).__name__,
            "error_code": safe_admission_reason(exc),
            "action_plan": None,
            "target_mutation_performed": False,
            "merge_authorized": False,
        }
        rc = 2
    RESULT_FILE.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    status = payload.get("status") or payload.get("snapshot", {}).get("status")
    print("SAMUEL_CODEQA_ISSUE_INGRESS=" + str(status))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
