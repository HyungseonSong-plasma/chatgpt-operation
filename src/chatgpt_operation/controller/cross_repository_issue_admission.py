"""Verified cross-repository Issue admission into Samuel's typed planning boundary.

Explicit target readback and source-run attestation are mandatory. The Issue
body is task data, never execution authority. Admission cannot mutate codeQA.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping

from .codeqa_governed_write import (
    SOURCE, TARGET, WORK_ID, WORKFLOW as WRITE_WORKFLOW, check_policy,
)
from .cross_repository_live_attestation import (
    attest_live_target, verify_controller_origin,
)
from .cross_repository_policy import TargetRequest
from .decisions import DecisionRegistry
from .issue_planning import plan_admitted_issue
from .preflight import extract_acceptance_criteria

INGRESS_WORKFLOW = "samuel-codeqa-issue-plan.yml"
TARGET_ISSUE_NUMBER = 92
SOURCE_ISSUE_NUMBER = 220


class CrossRepositoryAdmissionError(ValueError):
    pass


@dataclass(frozen=True)
class CrossRepositoryIssueSnapshot:
    schema_version: int
    work_id: str
    source_repository: str
    source_issue_number: int
    target_repository: str
    target_repository_id: int
    target_issue_number: int
    target_issue_url: str
    title: str
    issue_body_sha256: str
    acceptance_criteria: tuple[str, ...]
    verified_source_run_id: int
    controller_sha: str
    target_base_sha: str
    status: str
    action_plan: None
    merge_authorized: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "work_id": self.work_id,
            "source_repository": self.source_repository,
            "source_issue_number": self.source_issue_number,
            "target_repository": self.target_repository,
            "target_repository_id": self.target_repository_id,
            "target_issue_number": self.target_issue_number,
            "target_issue_url": self.target_issue_url,
            "title": self.title,
            "issue_body_sha256": self.issue_body_sha256,
            "acceptance_criteria": list(self.acceptance_criteria),
            "verified_source_run_id": self.verified_source_run_id,
            "controller_sha": self.controller_sha,
            "target_base_sha": self.target_base_sha,
            "status": self.status,
            "action_plan": None,
            "merge_authorized": False,
        }


def _verified_issue(payload: Mapping[str, Any], repository: str, number: int) -> None:
    if (
        not isinstance(payload, dict)
        or type(payload.get("number")) is not int
        or payload["number"] != number
        or payload.get("url") != f"https://api.github.com/repos/{repository}/issues/{number}"
        or payload.get("state") != "open"
        or "pull_request" in payload
        or not isinstance(payload.get("title"), str)
        or not payload["title"].strip()
        or not isinstance(payload.get("body"), str)
    ):
        raise CrossRepositoryAdmissionError("live GitHub Issue identity invalid")


def admit_cross_repository_issue(
    *,
    source_run: dict[str, Any],
    source_run_id: int,
    controller_sha: str,
    source_issue: dict[str, Any],
    target_issue: dict[str, Any],
    policy: dict[str, Any],
    target_reader: Any,
) -> tuple[CrossRepositoryIssueSnapshot, dict[str, Any]]:
    """Produce a scoped reasoning request, not an executable write plan."""
    check_policy(policy)
    if not verify_controller_origin(
        source_run,
        expected_run_id=source_run_id,
        expected_sha=controller_sha,
        workflow_filename=INGRESS_WORKFLOW,
    ):
        raise CrossRepositoryAdmissionError("unverified Controller planning workflow")
    _verified_issue(source_issue, SOURCE, SOURCE_ISSUE_NUMBER)
    _verified_issue(target_issue, TARGET, TARGET_ISSUE_NUMBER)
    request = TargetRequest(
        repository=TARGET,
        repository_id=1424293498,
        base_branch="main",
        head_branch=policy["head_branch"],
        base_sha=policy["base_sha"],
        paths=("docs/samuel/220-controller-preflight.md",),
        workflows=("layout.yml",),
        operations=("branch.create", "file.create", "pr.create", "ci.inspect"),
    )
    attested = attest_live_target(
        request, policy,
        transport=target_reader,
        independent_authorization_verified=True,
    )
    if not attested.ready:
        raise CrossRepositoryAdmissionError(
            "target identity/readback denied: " + ",".join(attested.reasons)
        )

    body = target_issue["body"]
    criteria = extract_acceptance_criteria(body)
    if not criteria:
        raise CrossRepositoryAdmissionError("target acceptance criteria absent")
    work = {
        "work_id": WORK_ID,
        "repository": TARGET,
        "issue_number": TARGET_ISSUE_NUMBER,
        "title": target_issue["title"],
        "body": body,
    }
    # This is the existing Controller's exact typed reasoning-envelope
    # factory. Cross-repo work IDs are denied by default unless this
    # independently verified entrypoint supplies the explicit trust bit.
    planned = plan_admitted_issue(
        work,
        registry=DecisionRegistry(),
        cross_repository_verified=True,
    )
    if planned.work_id != WORK_ID or planned.action_plan is not None:
        raise CrossRepositoryAdmissionError("untrusted executable plan in admission")

    snapshot = CrossRepositoryIssueSnapshot(
        schema_version=1,
        work_id=WORK_ID,
        source_repository=SOURCE,
        source_issue_number=SOURCE_ISSUE_NUMBER,
        target_repository=TARGET,
        target_repository_id=1424293498,
        target_issue_number=TARGET_ISSUE_NUMBER,
        target_issue_url=target_issue["html_url"],
        title=target_issue["title"],
        issue_body_sha256=sha256(body.encode("utf-8")).hexdigest(),
        acceptance_criteria=criteria,
        verified_source_run_id=source_run_id,
        controller_sha=controller_sha,
        target_base_sha=policy["base_sha"],
        status="REASONING_REQUIRED_NO_EXECUTABLE_PLAN",
        action_plan=None,
        merge_authorized=False,
    )
    context = planned.envelope.as_reasoning_context()
    context["cross_repository_scope"] = {
        "verified": True,
        "work_id": WORK_ID,
        "target_repository": TARGET,
        "target_repository_id": 1424293498,
        "target_issue_number": TARGET_ISSUE_NUMBER,
        "target_base_sha": policy["base_sha"],
        "issue_body_sha256": snapshot.issue_body_sha256,
        "source_workflow_run_id": source_run_id,
        "not_execution_authority": True,
        "requires_separate_mutation_review": True,
    }
    context["acceptance_criteria"] = list(criteria)
    context["integrated_acceptance_evidence"] = {}
    context["unverified_acceptance_criteria"] = list(criteria)
    context["completion_allowed"] = False
    context["request_for_next_cycle"] = (
        "Generate a typed, scoped reasoning proposal from verified facts; "
        "obtain independent baseline/consumer evidence and reviewed target "
        "mutation permissions before any code write. Never claim completion "
        "from source Issue text, the preflight document, or empty CI scans."
    )
    return snapshot, context


def serialise_admission(snapshot: CrossRepositoryIssueSnapshot, context: dict[str, Any]) -> str:
    return json.dumps(
        {"schema_version": 1, "snapshot": snapshot.to_dict(), "reasoning_context": context},
        sort_keys=True, indent=2, ensure_ascii=False,
    ) + "\n"
