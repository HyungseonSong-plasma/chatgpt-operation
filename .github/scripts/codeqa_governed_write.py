#!/usr/bin/env python3
"""Owner-gated, target-scoped Samuel codeQA proof; no automated merge.

Requires reviewed/enabled policy on source main and an owner-provisioned
SAMUEL_CODEQA_WRITE_TOKEN. The existing dispatch-only token is never used.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from chatgpt_operation.controller.codeqa_governed_write import (
    SOURCE, TARGET, HEAD, PATH, check_policy, build_governed_write_proof,
    execute_branch_and_file,
)
from chatgpt_operation.repository.mutation import GitHubTransport

POLICY_FILE = Path("automation/samuel/codeqa-write-target-candidate-v1.json")
RESULT_FILE = Path("samuel-codeqa-write-result.json")


class API:
    def __init__(self, token: str):
        if not token:
            raise ValueError("missing owner-scoped target credential")
        self.token = token

    def call(self, method: str, path: str, payload: dict | None = None):
        data = None if payload is None else json.dumps(payload).encode()
        req = Request(
            "https://api.github.com" + path, data=data, method=method,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "samuel-codeqa-governed-write-proof",
                "Content-Type": "application/json",
            },
        )
        with urlopen(req, timeout=30) as response:
            raw = response.read()
            return json.loads(raw.decode()) if raw else {}

    def get(self, path: str):
        return self.call("GET", path)


def _identity_env():
    env = os.environ
    if (env.get("GITHUB_ACTIONS") != "true"
        or env.get("GITHUB_REPOSITORY") != SOURCE
        or env.get("GITHUB_REF") != "refs/heads/main"
        or env.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
        or not env.get("GITHUB_RUN_ID", "").isdigit()):
        raise ValueError("not an exact mainline manual Controller workflow")
    return int(env["GITHUB_RUN_ID"]), env.get("GITHUB_SHA", "")


def _create_draft_pr(api: API, proof):
    """Separate draft-only PR creation, with exact target-head postcondition."""
    target = proof.pr_plan.payload["target"]
    path = "/repos/" + TARGET
    head_ref = api.get(path + "/git/ref/heads/" + quote(HEAD, safe=""))
    branch_sha = head_ref.get("object", {}).get("sha")
    if not isinstance(branch_sha, str) or len(branch_sha) != 40:
        raise ValueError("missing exact branch head")
    # Verify our planned file exists on this head, not merely that a branch
    # could be created or some other actor pushed a different commit.
    file = api.get(path + "/contents/" + quote(PATH, safe="/") + "?ref=" + quote(HEAD, safe=""))
    if file.get("type") != "file":
        raise ValueError("planned file not readable from target branch")
    query = urlencode({"state": "open", "head": "HyungseonSong-plasma:" + HEAD, "base": "main", "per_page": "100"})
    existing = api.get(path + "/pulls?" + query)
    if not isinstance(existing, list) or len(existing) > 1:
        raise ValueError("ambiguous target pull request")
    if existing:
        pr = existing[0]
    else:
        pr = api.call("POST", path + "/pulls", {
            "head": HEAD, "base": "main", "draft": True,
            "title": target["title"], "body": target["body"],
        })
    number = pr.get("number")
    if type(number) is not int:
        raise ValueError("target PR number absent")
    verified = api.get(path + "/pulls/" + str(number))
    if (verified.get("head", {}).get("sha") != branch_sha
        or verified.get("head", {}).get("ref") != HEAD
        or verified.get("base", {}).get("ref") != "main"
        or verified.get("head", {}).get("repo", {}).get("full_name") != TARGET
        or verified.get("base", {}).get("repo", {}).get("full_name") != TARGET
        or verified.get("title") != target["title"]
        or verified.get("body") != target["body"]
        or verified.get("draft") is not True
        or verified.get("merged") is True):
        raise ValueError("target Draft PR failed exact-head/scope readback")
    return {"number": number, "head_sha": branch_sha,
            "draft": True, "url": verified.get("html_url"),
            "action_id": proof.pr_plan.idempotency_key}


def _verify_ci(api: API, *, pr_number: int, head_sha: str):
    path = "/repos/" + TARGET
    # Only a separately approved exact workflow is considered required.
    for _ in range(30):
        query = urlencode({"event": "pull_request", "head_sha": head_sha, "per_page": "100"})
        records = api.get(path + "/actions/workflows/layout.yml/runs?" + query)
        runs = records.get("workflow_runs")
        if not isinstance(runs, list):
            raise ValueError("CI enumeration is not a list")
        matching = [
            r for r in runs if r.get("head_sha") == head_sha
            and r.get("event") == "pull_request"
            and r.get("path") == ".github/workflows/layout.yml"
            and any(p.get("number") == pr_number for p in r.get("pull_requests", []) if isinstance(p, dict))
        ]
        if len(matching) > 1:
            raise ValueError("ambiguous exact-head target CI result")
        if matching and matching[0].get("status") == "completed":
            run = matching[0]
            if run.get("conclusion") != "success":
                raise ValueError("required target Layout CI did not succeed")
            return {"workflow": "layout.yml", "run_id": run["id"],
                    "head_sha": head_sha, "conclusion": "success"}
        time.sleep(5)
    raise ValueError("required exact-head target Layout CI not yet verified")


def run():
    source_run_id, source_sha = _identity_env()
    policy = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
    check_policy(policy)  # disabled/malformed policy fails before side effects
    source = API(os.environ.get("GITHUB_TOKEN", ""))
    target_token = os.environ.get("SAMUEL_CODEQA_WRITE_TOKEN", "")
    if not target_token:
        raise ValueError("SAMUEL_CODEQA_WRITE_TOKEN missing")
    target = API(target_token)
    base = "/repos/"
    proof = build_governed_write_proof(
        policy,
        controller_run=source.get(base + SOURCE + "/actions/runs/" + str(source_run_id)),
        source_issue=source.get(base + SOURCE + "/issues/220"),
        target_issue=target.get(base + TARGET + "/issues/92"),
        observed_run_id=source_run_id,
        observed_source_sha=source_sha,
        target_reader=target,
    )
    # A fresh pinned-base ref read prevents executing against a stale policy
    # even if GitHub's target branch moved after initial authorization.
    def assert_target_base():
        x = target.get(base + TARGET + "/git/ref/heads/main")
        if x.get("object", {}).get("sha") != proof.target_base_sha:
            raise ValueError("target base SHA changed before mutation")

    assert_target_base()
    transport = GitHubTransport(TARGET, target_token)
    mutations = execute_branch_and_file(proof, transport=transport)
    assert_target_base()
    pr = _create_draft_pr(target, proof)
    ci = _verify_ci(target, pr_number=pr["number"], head_sha=pr["head_sha"])
    assert_target_base()
    return {
        "status": "CONTROLLER_GOVERNED_DOC_WRITE_PR_CI_CONFIRMED",
        "source_workflow_run_id": source_run_id, "source_sha": source_sha,
        "target_repository": TARGET, "target_repository_id": proof.target_repository_id,
        "target_base_sha": proof.target_base_sha,
        "action_plans": mutations,
        "pr": pr,
        "required_ci": [ci],
        "merge_authorized": False, "merge_performed": False,
        "scope": "ONE_FIXED_DOCUMENT_DRAFT_PR_ONLY",
        "general_issue_execution": False,
    }


def main() -> int:
    try:
        result = run()
    except Exception as exc:
        # Avoid logging API credentials, untrusted server response bodies,
        # or exception strings that could contain token-derived material.
        result = {
            "status": "HARD_STOP", "error_type": type(exc).__name__,
            "merge_authorized": False, "general_issue_execution": False,
        }
    RESULT_FILE.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("SAMUEL_CODEQA_WRITE=" + result["status"])
    return 0 if result["status"] == "CONTROLLER_GOVERNED_DOC_WRITE_PR_CI_CONFIRMED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
