"""Issue #92 proposal-only preflight and independently bounded review.

No codeQA mutation or GitHub dispatch. The source Ledger is the durable
review boundary; this stage must never change either repository main.
"""
from __future__ import annotations

from typing import Any, Mapping

from .cross_repository_issue_admission import CrossRepositoryIssueSnapshot
from .cross_repository_workflow import (
    ForeignWorkState, WORK_ID, TARGET, validate_foreign_plan,
)
from .action_plan import ActionPlan

PROPOSAL_PATH = "tests/test_samuel_issue92_external_sdk_contract.py"
PROPOSAL_BRANCH = "samuel/92-governed-implementation"
POLICY_PREFIXES = (
    "fixtures/python-sdk/",
    "src/codeqa/evaluation/",
    "tests/test_samuel_issue92_",
    "docs/python-sdk-",
)
REQUIRED_CI = (
    "layout.yml",
    "pinned-python-sdk.yml",
    "self-audit.yml",
    "semgrep-gate.yml",
)


class ProposalPreflightError(ValueError):
    pass


def verify_proposal_preflight(
    state: ForeignWorkState,
    snapshot: CrossRepositoryIssueSnapshot,
    policy: Mapping[str, Any],
    *,
    target_main_sha: str,
    candidate_absent: bool,
) -> None:
    """Require actual, unchanged source/target facts BEFORE invoking the LLM."""
    if (
        state.work_id != WORK_ID
        or state.phase != "reasoning_required"
        or state.action_plan is not None
        or state.action_id is not None
        or state.receipt is not None
        or state.target_pr is not None
        or state.ci_evidence
        or state.last_failure is not None
        or snapshot.work_id != WORK_ID
        or snapshot.status != "REASONING_REQUIRED_NO_EXECUTABLE_PLAN"
        or snapshot.issue_body_sha256 != state.issue_sha
        or state.criteria_sha != _criteria_digest(snapshot)
        or not isinstance(target_main_sha, str)
        or target_main_sha != state.base_sha
        or target_main_sha != snapshot.target_base_sha
        or not candidate_absent
    ):
        raise ProposalPreflightError("foreign proposal live Ledger/base/input preflight rejected")
    if (
        not isinstance(policy, Mapping)
        or policy.get("schema_version") != 1
        or policy.get("policy_id") != "samuel-codeqa-issue92-execution-v1"
        or policy.get("enabled") is not False
        or policy.get("repository") != TARGET
        or policy.get("repository_id") != 1424293498
        or policy.get("base_branch") != "main"
        or policy.get("base_sha") != target_main_sha
        or policy.get("head_branch") != PROPOSAL_BRANCH
        or policy.get("path_prefixes") != list(POLICY_PREFIXES)
        or policy.get("required_workflows") != list(REQUIRED_CI)
        or policy.get("merge_enabled") is not False
        or policy.get("executor_workflow") != "samuel-codeqa-issue-execute.yml"
    ):
        raise ProposalPreflightError("proposal execution candidate policy is not exact/disabled")


def _criteria_digest(snapshot: CrossRepositoryIssueSnapshot) -> str:
    from .cross_repository_workflow import digest
    return digest(list(snapshot.acceptance_criteria))


def proposed_reasoning_context(
    verified_context: Mapping[str, Any],
    snapshot: CrossRepositoryIssueSnapshot,
) -> dict[str, Any]:
    """Small, explicit one-file proposal schema; Issue text remains untrusted."""
    context = dict(verified_context)
    context["execution_contracts"] = [
        {
            "executor": "repository_mutation",
            "stage": "execute",
            "research_id": WORK_ID,
            "payload": {
                "schema_version": 1,
                "repository": TARGET,
                "resource": "file",
                "action": "create",
                "target": {"path": PROPOSAL_PATH, "branch": PROPOSAL_BRANCH},
                "expected": {"absent": True},
                "desired": {"content": "<non-empty reviewed Python test source>"},
                "commit_message": "test(#92): propose independently reviewable external SDK evidence guard",
            },
            "expected_observation": "A separately reviewed target-owned Draft PR and exact-head CI",
            "decision_risk": None,
        }
    ]
    context["verified_target_file_precondition"] = {
        "path": PROPOSAL_PATH,
        "branch": "main",
        "base_sha": snapshot.target_base_sha,
        "absent": True,
    }
    context["proposal_limitations"] = (
        "Draft one additive, reviewable Python test file only. No target writes, "
        "no GitHub workflow dispatch, no issue closure, no merge, and no claims "
        "of completed SDK/DTO/DB compatibility. Use only the real stated "
        "acceptance criteria; no fabricated pinned SDK, public consumer schema "
        "or migration baseline. If meaningful tests require missing external "
        "evidence, return an analyze proposal with action_plan=null and a "
        "typed blocker instead. If an ActionPlan is supplied, use exactly the "
        "single execution_contracts file.create target with stage=execute, "
        "decision_risk=null, compatible_with_locked_decisions=true, and "
        "revision_requested=false."
    )
    context["completion_allowed"] = False
    return context


def verify_proposed_review(
    before: ForeignWorkState,
    after: ForeignWorkState,
    policy: Mapping[str, Any],
) -> None:
    """A provider proposal cannot skip independent human review."""
    if (
        after.work_id != before.work_id
        or after.issue_sha != before.issue_sha
        or after.base_sha != before.base_sha
        or after.criteria_sha != before.criteria_sha
        or after.admission_run_id != before.admission_run_id
        or after.revision != before.revision+1
        or after.phase not in {"review_required","reasoning_required","revision_required"}
        or after.receipt is not None
        or after.target_pr is not None
        or after.ci_evidence
    ):
        raise ProposalPreflightError("proposed state violated review-only transition")
    if after.phase != "review_required":
        if after.action_plan is not None or after.action_id is not None:
            raise ProposalPreflightError("unapproved executable action in non-review state")
        return
    if after.action_plan is None or after.action_id is None:
        raise ProposalPreflightError("review state lacks a typed ActionPlan")
    plan=ActionPlan.from_dict(after.action_plan)
    inspect=dict(policy)
    inspect["enabled"]=True  # Structural inspection ONLY; no execution credential.
    validate_foreign_plan(plan,inspect)
    payload=plan.payload
    if (
        plan.idempotency_key != after.action_id
        or payload.get("resource") != "file"
        or payload.get("action") != "create"
        or payload.get("target") != {
            "path": PROPOSAL_PATH, "branch": PROPOSAL_BRANCH,
        }
        or payload.get("expected") != {"absent": True}
        or payload.get("desired",{}).get("content", "").strip() == ""
    ):
        raise ProposalPreflightError("provider action exceeded one-file read-only proposal contract")
