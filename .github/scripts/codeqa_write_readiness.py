#!/usr/bin/env python3
"""Read-only target readiness check; NEVER mutates codeQA or creates a PR.

Used only on a reviewed workflow_dispatch run. A successful result establishes
metadata/readback gates, not ActionPlan-to-mutation E2E or write permission.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from chatgpt_operation.controller.cross_repository_policy import TargetRequest
from chatgpt_operation.controller.cross_repository_live_attestation import (
    attest_live_target, verify_controller_origin,
)

SOURCE = "HyungseonSong-plasma/chatgpt-operation"
TARGET = "HyungseonSong-plasma/codeQA"
POLICY_PATH = Path("automation/samuel/codeqa-write-target-candidate-v1.json")
OUTPUT_PATH = Path("samuel-codeqa-write-readiness.json")


class GitHubReader:
    def __init__(self, token: str):
        if not token:
            raise ValueError("missing GitHub read token")
        self.token = token

    def get(self, path: str):
        req = Request(
            "https://api.github.com" + path,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "samuel-crossrepo-target-readiness",
            },
        )
        with urlopen(req, timeout=20) as response:
            return json.load(response)


def evaluate() -> dict:
    env = os.environ
    if (
        env.get("GITHUB_ACTIONS") != "true"
        or env.get("GITHUB_REPOSITORY") != SOURCE
        or env.get("GITHUB_REF") != "refs/heads/main"
        or not env.get("GITHUB_RUN_ID", "").isdigit()
    ):
        raise ValueError("not the exact trusted Controller workflow context")
    source = GitHubReader(env.get("GITHUB_TOKEN", ""))
    token = env.get("SAMUEL_CODEQA_WRITE_TOKEN", "")
    if not token:
        return {"status": "BLOCKED_MISSING_TARGET_WRITE_CREDENTIAL"}
    target = GitHubReader(token)
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if (
        policy.get("repository") != TARGET
        or type(policy.get("repository_id")) is not int
        or policy.get("head_branch") != "samuel/220-controller-crossrepo-preflight"
        or policy.get("merge_enabled") is not False
        or policy.get("authorization_source") != "OWNER_REVIEW_AND_INDEPENDENT_GITHUB_WORKFLOW_ATTESTATION_REQUIRED"
    ):
        raise ValueError("unexpected target write candidate policy")
    run = source.get("/repos/" + SOURCE + "/actions/runs/" + env["GITHUB_RUN_ID"])
    origin_ok = verify_controller_origin(
        run,
        expected_run_id=int(env["GITHUB_RUN_ID"]),
        expected_sha=env.get("GITHUB_SHA", ""),
    )
    # Independently fetch both Issue identities, not free-form Issue contents
    # presented inside an ActionPlan.
    source_issue = source.get("/repos/" + SOURCE + "/issues/220")
    target_issue = target.get("/repos/" + TARGET + "/issues/92")
    for actual, selected_repo, number in (
        (source_issue, SOURCE, 220), (target_issue, TARGET, 92)
    ):
        if (
            actual.get("number") != number
            or actual.get("state") != "open"
            or actual.get("url") != "https://api.github.com/repos/" + selected_repo + "/issues/" + str(number)
            or "pull_request" in actual
        ):
            raise ValueError("source/target issue identity not independently verified")
    request = TargetRequest(
        repository=policy["repository"],
        repository_id=policy["repository_id"],
        base_branch=policy["base_branch"],
        head_branch=policy["head_branch"],
        base_sha=policy["base_sha"],
        paths=("docs/samuel/220-controller-preflight.md",),
        workflows=tuple(policy["workflows"]),
        operations=tuple(policy["operations"]),
    )
    result = attest_live_target(
        request, policy, transport=target,
        independent_authorization_verified=origin_ok,
    )
    return {
        "status": "READ_ONLY_TARGET_READBACK_READY" if result.ready else "BLOCKED",
        "controller_origin_verified": origin_ok,
        "target_repository": TARGET,
        "target_repository_id": result.observed_repository_id,
        "target_base_sha": result.observed_base_sha,
        "controller_sha": env.get("GITHUB_SHA"),
        "controller_run_id": env["GITHUB_RUN_ID"],
        "reasons": list(result.reasons),
        "allowed_mutations": [],
        "credential_write_proven": False,
        "controller_action_plan_executed": False,
    }


def main() -> int:
    try:
        result = evaluate()
    except (ValueError, TypeError, KeyError, OSError, HTTPError, URLError, json.JSONDecodeError) as exc:
        result = {
            "status": "BLOCKED",
            "reasons": [type(exc).__name__],
            "allowed_mutations": [],
            "credential_write_proven": False,
            "controller_action_plan_executed": False,
        }
    OUTPUT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("SAMUEL_CODEQA_WRITE_READINESS=" + result["status"])
    return 0 if result["status"] == "READ_ONLY_TARGET_READBACK_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
