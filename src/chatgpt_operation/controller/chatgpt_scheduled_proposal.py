"""GitHub owner-submitted (including ChatGPT Scheduled Task) proposal bridge.

The ingress authenticates GitHub OWNER issue_comment provenance, not the
originating AI model. Proposal text is untrusted until exact fact, ledger,
ActionPlan and policy validation. Ingestion only writes review_required.
"""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from typing import Any, Mapping

from .action_plan import ActionPlan
from .cross_repository_issue_admission import (
    CrossRepositoryIssueSnapshot, extract_target_issue_acceptance,
)
from .cross_repository_workflow import (
    ForeignWorkState, SOURCE, TARGET, WORK_ID, digest,
)
from .cross_repository_proposal import (
    PROPOSAL_PATH, ProposalPreflightError, verify_proposal_preflight,
    verify_proposed_review,
)

OWNER_ID = 189476866
OWNER = "HyungseonSong-plasma"
SOURCE_WORKFLOW = ".github/workflows/samuel-chatgpt-proposal-ingress.yml"
SOURCE_ISSUE_URL = (
    "https://api.github.com/repos/" + SOURCE + "/issues/220"
)
COMMENT_MARKER = "<!-- samuel-chatgpt-proposal-v1 -->"
PREFIX = COMMENT_MARKER + "\n```json\n"
SUFFIX = "\n```"
EXPECTED_PROPOSAL_KEYS = {
    "schema_version", "work_id", "ledger_revision",
    "target_base_sha", "issue_sha256", "action_plan",
}


class ScheduledProposalError(ValueError):
    pass


def parse_owner_proposal(body: str) -> dict[str, Any]:
    if (
        not isinstance(body, str)
        or len(body.encode("utf-8")) > 48_000
        or not body.startswith(PREFIX)
        or not body.endswith(SUFFIX)
    ):
        raise ScheduledProposalError("proposal comment format invalid")
    try:
        raw = json.loads(body[len(PREFIX):-len(SUFFIX)])
    except (ValueError, TypeError) as exc:
        raise ScheduledProposalError("proposal JSON invalid") from exc
    if (
        not isinstance(raw, dict)
        or set(raw) != EXPECTED_PROPOSAL_KEYS
        or raw["schema_version"] != 1
        or raw["work_id"] != WORK_ID
        or type(raw["ledger_revision"]) is not int
        or raw["ledger_revision"] < 0
        or not isinstance(raw["action_plan"], dict)
    ):
        raise ScheduledProposalError("proposal typed envelope invalid")
    return raw


def validate_owner_comment_context(
    *,
    source_run: Mapping[str, Any],
    source_main_sha: str,
    source_issue: Mapping[str, Any],
    source_comment: Mapping[str, Any],
    event_comment_id: int,
) -> None:
    if (
        not isinstance(source_run, Mapping)
        or source_run.get("event") != "issue_comment"
        or source_run.get("path") not in (
            SOURCE_WORKFLOW,
            SOURCE_WORKFLOW + "@refs/heads/main",
        )
        or source_run.get("head_branch") != "main"
        or source_run.get("head_sha") != source_main_sha
        or source_run.get("repository", {}).get("full_name") != SOURCE
        or source_run.get("actor", {}).get("login") != OWNER
        or not isinstance(source_comment, Mapping)
        or source_comment.get("id") != event_comment_id
        or source_comment.get("issue_url") != SOURCE_ISSUE_URL
        or source_comment.get("user", {}).get("login") != OWNER
        or source_comment.get("user", {}).get("id") != OWNER_ID
        or not isinstance(source_issue, Mapping)
        or source_issue.get("number") != 220
        or source_issue.get("state") != "open"
        or source_issue.get("url") != SOURCE_ISSUE_URL
        or source_issue.get("user", {}).get("login") != OWNER
    ):
        raise ScheduledProposalError("owner source issue_comment attestation denied")


def review_owner_proposal(
    *,
    source_run: Mapping[str, Any],
    source_main_sha: str,
    source_issue: Mapping[str, Any],
    source_comment: Mapping[str, Any],
    event_comment_id: int,
    previous: ForeignWorkState,
    target_issue: Mapping[str, Any],
    target_main_sha: str,
    policy: Mapping[str, Any],
    candidate_absent: bool,
) -> ForeignWorkState:
    """Pure review-only transaction suitable for independent offline tests."""
    validate_owner_comment_context(
        source_run=source_run, source_main_sha=source_main_sha,
        source_issue=source_issue, source_comment=source_comment,
        event_comment_id=event_comment_id,
    )
    if (
        not isinstance(target_issue, Mapping)
        or target_issue.get("number") != 92
        or target_issue.get("state") != "open"
        or target_issue.get("url") != (
            "https://api.github.com/repos/" + TARGET + "/issues/92"
        )
        or target_issue.get("pull_request") is not None
        or not isinstance(target_issue.get("body"), str)
        or not isinstance(target_issue.get("title"), str)
    ):
        raise ScheduledProposalError("target issue identity invalid")
    criteria = extract_target_issue_acceptance(target_issue["body"])
    if not criteria:
        raise ScheduledProposalError("live target acceptance missing")
    issue_sha = sha256(target_issue["body"].encode("utf-8")).hexdigest()
    snapshot = CrossRepositoryIssueSnapshot(
        schema_version=1,
        work_id=WORK_ID,
        source_repository=SOURCE,
        source_issue_number=220,
        target_repository=TARGET,
        target_repository_id=1424293498,
        target_issue_number=92,
        target_issue_url=target_issue.get("html_url", ""),
        title=target_issue["title"],
        issue_body_sha256=issue_sha,
        acceptance_criteria=criteria,
        verified_source_run_id=source_run["id"],
        controller_sha=source_main_sha,
        target_base_sha=target_main_sha,
        status="REASONING_REQUIRED_NO_EXECUTABLE_PLAN",
        action_plan=None,
        merge_authorized=False,
    )
    try:
        verify_proposal_preflight(
            previous, snapshot, policy,
            target_main_sha=target_main_sha,
            candidate_absent=candidate_absent,
        )
    except ProposalPreflightError as exc:
        raise ScheduledProposalError("live external proposal prerequisites denied") from exc
    submitted = parse_owner_proposal(source_comment.get("body", ""))
    if (
        submitted["ledger_revision"] != previous.revision
        or submitted["issue_sha256"] != issue_sha
        or submitted["target_base_sha"] != target_main_sha
    ):
        raise ScheduledProposalError("comment proposal is stale")
    plan=ActionPlan.from_dict(submitted["action_plan"])
    # Do not trust externally supplied idempotency keys: recompute the digest
    # from the reviewed ActionPlan schema in the existing Samuel kernel.
    after=replace(
        previous, revision=previous.revision+1,
        phase="review_required",
        action_plan={
            "schema_version":1,
            "research_id":plan.research_id,
            "stage":plan.stage.value,
            "executor":plan.executor.value,
            "payload":plan.payload,
            "expected_observation":plan.expected_observation,
        },
        action_id=plan.idempotency_key,
        last_failure=None,
    )
    try:
        verify_proposed_review(previous, after, policy)
    except (ProposalPreflightError, ValueError) as exc:
        raise ScheduledProposalError("external ActionPlan failed reviewed scope") from exc
    return after
