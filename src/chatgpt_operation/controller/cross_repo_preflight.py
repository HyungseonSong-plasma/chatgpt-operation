"""Guarded Samuel→codeQA workflow dispatch contract; no target code mutation.

The execution token is supplied only by GitHub Actions secrets. This module
cannot close issues, mutate codeQA, approve PRs, or create its own authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re
from collections.abc import Mapping


class CrossRepoPreflightError(ValueError):
    pass


_SHA = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_KEYS = {
    "schema_version", "policy_id", "source_repository", "source_issue",
    "target_repository", "target_issue", "work_id", "workflow", "ref",
    "approved_actors", "operations", "target_issue_write",
    "target_pr_create", "target_merge", "authorization",
    "credential_name", "credential_scope", "owner_controlled_secret",
}


@dataclass(frozen=True, slots=True)
class CrossRepoPreflightPlan:
    schema_version: int
    status: str
    policy_id: str
    work_id: str
    target_repository: str
    target_issue: int
    target_workflow: str
    target_ref: str
    source_head_sha: str
    target_head_sha: str
    source_run_id: str
    expected_actor: str
    mutation_scope: str
    preflight_identity: str

    def to_document(self) -> dict[str, object]:
        return asdict(self)


def _require_issue(value: Mapping[str, object], repository: str, number: int) -> None:
    if not isinstance(value, Mapping) or value.get("number") != number:
        raise CrossRepoPreflightError("missing or wrong GitHub Issue identity")
    if value.get("state") != "open" or value.get("pull_request") is not None:
        raise CrossRepoPreflightError("target/source Issue not open")
    if value.get("url") != f"https://api.github.com/repos/{repository}/issues/{number}":
        raise CrossRepoPreflightError("Issue repository URL mismatch")


def compile_codeqa_preflight(
    policy: Mapping[str, object], *,
    source_issue: Mapping[str, object],
    target_issue: Mapping[str, object],
    observed_source_sha: str,
    observed_target_sha: str,
    expected_source_sha: str,
    expected_target_sha: str,
    actor: str,
    source_run_id: str,
) -> CrossRepoPreflightPlan:
    if not isinstance(policy, Mapping) or set(policy) != EXPECTED_KEYS:
        raise CrossRepoPreflightError("unsupported policy shape")
    if type(policy.get("schema_version")) is not int or policy["schema_version"] != 1:
        raise CrossRepoPreflightError("unsupported policy version")
    fixed = {
        "source_repository": "HyungseonSong-plasma/chatgpt-operation",
        "source_issue": 220,
        "target_repository": "HyungseonSong-plasma/codeQA",
        "target_issue": 92,
        "work_id": "github:HyungseonSong-plasma/codeQA:issue:92",
        "workflow": "samuel-crossrepo-preflight.yml",
        "ref": "main",
        "operations": ["READ_ONLY_PREFLIGHT_DISPATCH"],
        "approved_actors": ["HyungseonSong-plasma"],
        "target_issue_write": False, "target_pr_create": False,
        "target_merge": False, "owner_controlled_secret": True,
        "authorization": "EXPLICIT_USER_TASK_DIRECTED_READONLY_PREFLIGHT",
        "credential_name": "SAMUEL_CODEQA_DISPATCH_TOKEN",
        "credential_scope": "target_actions_write_only",
    }
    if any(policy.get(key) != value for key, value in fixed.items()):
        raise CrossRepoPreflightError("policy exceeds approved codeQA read-only scope")
    if not isinstance(policy.get("policy_id"), str) or not policy["policy_id"]:
        raise CrossRepoPreflightError("policy identifier missing")
    _require_issue(source_issue, fixed["source_repository"], fixed["source_issue"])
    _require_issue(target_issue, fixed["target_repository"], fixed["target_issue"])
    if not all(isinstance(x, str) and _SHA.fullmatch(x) for x in (
        observed_source_sha, observed_target_sha,
        expected_source_sha, expected_target_sha,
    )):
        raise CrossRepoPreflightError("invalid exact source/target commit")
    if observed_source_sha != expected_source_sha or observed_target_sha != expected_target_sha:
        raise CrossRepoPreflightError("source or target HEAD moved; stale preflight plan")
    if actor not in fixed["approved_actors"]:
        raise CrossRepoPreflightError("unapproved dispatch actor")
    if not isinstance(source_run_id, str) or not source_run_id.isdecimal() or int(source_run_id) <= 0:
        raise CrossRepoPreflightError("missing source workflow run identity")
    fingerprint = {
        "schema_version": 1, "policy": policy["policy_id"],
        "work_id": fixed["work_id"], "source_sha": observed_source_sha,
        "target_sha": observed_target_sha, "source_run_id": source_run_id,
    }
    identity = sha256(json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return CrossRepoPreflightPlan(
        schema_version=1, status="READY_FOR_READ_ONLY_DISPATCH",
        policy_id=policy["policy_id"], work_id=fixed["work_id"],
        target_repository=fixed["target_repository"],
        target_issue=fixed["target_issue"],
        target_workflow=fixed["workflow"], target_ref=fixed["ref"],
        source_head_sha=observed_source_sha, target_head_sha=observed_target_sha,
        source_run_id=source_run_id, expected_actor=actor,
        mutation_scope="NONE", preflight_identity=identity,
    )
