"""Governed, bounded Samuel -> codeQA write proof (owner-dispatched only).

A verified controller-side workflow on protected main *constructs* each typed
ActionPlan from an owner-reviewed policy and independent live GitHub facts.
No untrusted Issue text or dispatch input may provide a repository mutation.
This is a preflight lane, NOT general codeQA Issue automation or merge authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Callable

from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.controller.cross_repository_live_attestation import (
    attest_live_target, verify_controller_origin,
)
from chatgpt_operation.controller.cross_repository_policy import TargetRequest
from chatgpt_operation.github.native_executor import NativeGitHubCommand
from chatgpt_operation.repository.action_plan_adapter import to_repository_manifest
from chatgpt_operation.repository.mutation import (
    Engine, GitHubTransport, parse_policy,
)

SOURCE = "HyungseonSong-plasma/chatgpt-operation"
TARGET = "HyungseonSong-plasma/codeQA"
HEAD = "samuel/220-controller-crossrepo-preflight"
PATH = "docs/samuel/220-controller-preflight.md"
WORK_ID = "github:HyungseonSong-plasma/codeQA:issue:92"
OPERATIONS = ("branch.create", "file.create", "pr.create", "ci.inspect")
WORKFLOWS = ("layout.yml",)
POLICY_ID = "samuel-codeqa-write-preflight-candidate-v1"
WORKFLOW = "samuel-codeqa-write-execute.yml"
SHA_LEN = 40


class CodeQAWriteError(ValueError):
    pass


@dataclass(frozen=True)
class WriteProof:
    controller_run_id: int
    controller_sha: str
    target_base_sha: str
    target_repository_id: int
    branch_plan: ActionPlan
    file_plan: ActionPlan
    pr_plan: ActionPlan


def check_policy(policy: Mapping[str, Any]) -> None:
    """Refuse any unexpected broadening, including additional allowed actions."""
    fixed = {
        "schema_version": 1,
        "policy_id": POLICY_ID,
        "enabled": True,
        "repository": TARGET,
        "repository_id": 1424293498,
        "base_branch": "main",
        "head_branch": HEAD,
        "path_prefixes": ["docs/samuel/"],
        "workflows": list(WORKFLOWS),
        "operations": list(OPERATIONS),
        "merge_enabled": False,
        "authorization_source":
            "OWNER_REVIEW_AND_INDEPENDENT_GITHUB_WORKFLOW_ATTESTATION_REQUIRED",
        "credential_name": "SAMUEL_CODEQA_WRITE_TOKEN",
    }
    if any(policy.get(k) != v for k, v in fixed.items()):
        raise CodeQAWriteError("target write policy is not exactly approved")
    if not isinstance(policy.get("base_sha"), str) or len(policy["base_sha"]) != SHA_LEN:
        raise CodeQAWriteError("base SHA missing")
    if any(k not in {*fixed, "base_sha", "notes"} for k in policy):
        raise CodeQAWriteError("unexpected target policy field")


def _plan(executor: str, payload: dict[str, Any], note: str) -> ActionPlan:
    return ActionPlan.from_dict({
        "schema_version": 1,
        "research_id": WORK_ID,
        "stage": "execute",
        "executor": executor,
        "payload": payload,
        "expected_observation": note,
    })


def build_governed_write_proof(
    policy: Mapping[str, Any],
    *,
    controller_run: dict[str, Any],
    source_issue: dict[str, Any],
    target_issue: dict[str, Any],
    observed_run_id: int,
    observed_source_sha: str,
    target_reader: Any,
) -> WriteProof:
    """Preflight everything *before* constructing any mutation plan."""
    check_policy(policy)
    if not verify_controller_origin(
        controller_run, expected_run_id=observed_run_id,
        expected_sha=observed_source_sha, workflow_filename=WORKFLOW,
    ):
        raise CodeQAWriteError("controller Actions origin not verified")
    for issue, repo, number in (
        (source_issue, SOURCE, 220),
        (target_issue, TARGET, 92),
    ):
        if (
            not isinstance(issue, dict)
            or type(issue.get("number")) is not int
            or issue["number"] != number
            or issue.get("state") != "open"
            or "pull_request" in issue
            or issue.get("url") != f"https://api.github.com/repos/{repo}/issues/{number}"
        ):
            raise CodeQAWriteError("live source/target Issue identity rejected")

    request = TargetRequest(
        repository=TARGET,
        repository_id=1424293498,
        base_branch="main",
        head_branch=HEAD,
        base_sha=policy["base_sha"],
        paths=(PATH,),
        workflows=WORKFLOWS,
        operations=OPERATIONS,
    )
    result = attest_live_target(
        request, dict(policy), transport=target_reader,
        independent_authorization_verified=True,
    )
    if not result.ready:
        raise CodeQAWriteError(
            "target live-readback rejected: " + ",".join(result.reasons)
        )

    branch = _plan("repository_mutation", {
        "schema_version": 1, "repository": TARGET,
        "resource": "branch", "action": "create",
        "target": {"name": HEAD},
        "expected": {"absent": True},
        "desired": {"sha": policy["base_sha"]},
    }, "exact target codeQA branch exists at the pinned main commit")
    file_content = (
        "# Samuel codeQA #92 bounded write proof\n\n"
        f"Source workflow run: {observed_run_id}\n\n"
        f"Controller SHA: {observed_source_sha}\n\n"
        f"Target base SHA: {policy['base_sha']}\n\n"
        "Scope: isolated draft PR, no merging or Issue closure.\n"
    )
    file = _plan("repository_mutation", {
        "schema_version": 1, "repository": TARGET,
        "resource": "file", "action": "create",
        "target": {"path": PATH, "branch": HEAD},
        "expected": {"absent": True},
        "desired": {"content": file_content},
        "commit_message": "test(#92): bounded Samuel Controller-origin write proof",
    }, "exact codeQA evidence file content independently read back")
    pr = _plan("github_native", {
        "action": "create_pr", "repository": TARGET,
        "target": {
            "head": HEAD, "base": "main",
            "title": "[Samuel #220] Controller-origin codeQA write preflight",
            "body": (
                "Source workflow run ID: " + str(observed_run_id)
                + "\nController SHA: " + observed_source_sha
                + "\nTarget pinned main SHA: " + policy["base_sha"]
                + "\nTyped ActionPlans: "
                + ", ".join((branch.idempotency_key, file.idempotency_key))
                + "\nTest document only. DRAFT; no approval to merge."
            ),
        },
        "preconditions": {"pr_present": False},
        "desired_postcondition": {"pr_present": True},
    }, "one codeQA draft PR exists at the exact produced branch HEAD")
    for item in (branch, file):
        to_repository_manifest(item, expected_repository=TARGET)
    NativeGitHubCommand.from_plan(pr)
    return WriteProof(
        observed_run_id, observed_source_sha,
        policy["base_sha"], 1424293498, branch, file, pr,
    )


def repository_policy() -> dict[str, Any]:
    """Self-contained minimal target policy, unrelated to protected self-policy."""
    return {
        "schema_version": 1, "repository": TARGET,
        "mutation": {
            "allow": {"file": ["create"], "branch": ["create"]},
            "file_paths": {"allow": [PATH], "deny": [".github/**"]},
            "branch_names": {"allow": [HEAD], "deny": ["main", "master"]},
        },
        "validation_gate": {
            "mode": "off", "workflows": [], "ignore_current_run": False,
        },
    }


def execute_branch_and_file(
    proof: WriteProof, *, transport: GitHubTransport,
    on_result: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Execute only the two independently validated ActionPlans, with readback."""
    policy = parse_policy(repository_policy())
    engine = Engine(transport, repository=TARGET, policy=policy)
    records = []
    for action in (proof.branch_plan, proof.file_plan):
        manifest = to_repository_manifest(action, expected_repository=TARGET)
        result = engine.execute(manifest)
        if result.get("status") not in ("PASS", "NO_MUTATION_NEEDED"):
            raise CodeQAWriteError("unexpected target mutation outcome")
        record = {
            "action_id": action.idempotency_key, "operation_id": manifest.operation_id,
            "status": result["status"], "result_identity": result.get("result_identity"),
        }
        records.append(record)
        if on_result is not None:
            on_result(dict(record))
    return records
