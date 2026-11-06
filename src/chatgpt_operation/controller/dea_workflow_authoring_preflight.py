"""DEA #254 — fail-closed *planning* check for a narrow Workflow Draft PR.

This helper has NO GitHub mutation integration and cannot authorize writes.
A trusted external adapter MUST separately authenticate GitHub policy,
the protected-base snapshot, human authority clearance, and the blocker
journal, then enforce all pre-write gates at the actual connector boundary.
No caller-provided booleans, simulated approval, or receipt grant authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from hashlib import sha256
import re
from typing import Any

from chatgpt_operation.repository.mutation import parse_policy, PolicyError

REPO = "HyungseonSong-plasma/chatgpt-operation"
WORK_ID = "DEA-254-PRODUCER-SMOKE"
PATH = ".github/workflows/dea-evidence-producer.yml"
BRANCH = "issue-254-producer-adoption"
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_MAX_YAML_BYTES = 64_000


@dataclass(frozen=True)
class WorkflowDraftIntent:
    repository: str
    work_id: str
    path: str
    action: str
    branch: str
    base_branch: str
    expected_base_sha: str
    draft: bool
    content: bytes


@dataclass(frozen=True)
class DraftPreflight:
    status: str
    reasons: tuple[str, ...]
    content_sha256: str | None
    # A local predicate is not a capability/permission, ever.
    write_authorized: bool = False
    workflow_dispatch_authorized: bool = False
    merge_authorized: bool = False


def assess_workflow_draft_intent(
    request: WorkflowDraftIntent,
    *,
    observed_main_sha: str,
    trusted_reference_yaml: bytes,
    policy_document: dict[str, Any],
) -> DraftPreflight:
    """Compare proposed bytes and scoped policy (NOT credential/owner proof).

    This routine must not call GitHub or execute any mutation. Its source
    arguments require separately verified GitHub readbacks to be useful.
    """
    problems: list[str] = []
    if not isinstance(request, WorkflowDraftIntent):
        raise TypeError("typed workflow draft intent required")
    if request.repository != REPO or request.work_id != WORK_ID:
        problems.append("WORK_IDENTITY_MISMATCH")
    if request.path != PATH or request.action != "create":
        problems.append("WRONG_WORKFLOW_PATH_OR_ACTION")
    if (request.branch != BRANCH or request.base_branch != "main"
            or request.draft is not True):
        problems.append("DRAFT_BRANCH_OR_BASE_MISMATCH")
    if not (isinstance(request.expected_base_sha, str)
            and _SHA.fullmatch(request.expected_base_sha)
            and isinstance(observed_main_sha, str)
            and _SHA.fullmatch(observed_main_sha)
            and request.expected_base_sha == observed_main_sha):
        problems.append("STALE_OR_INVALID_MAIN_SHA")
    candidate = request.content
    source = trusted_reference_yaml
    if (not isinstance(candidate, bytes) or not isinstance(source, bytes)
            or not 0 < len(candidate) <= _MAX_YAML_BYTES
            or candidate != source):
        problems.append("WORKFLOW_BYTES_NOT_EXACT_REVIEWED_SOURCE")
    try:
        policy = parse_policy(policy_document)
    except (PolicyError, TypeError, KeyError, ValueError):
        policy = None
    if policy is None or policy.repository != REPO:
        problems.append("POLICY_UNAVAILABLE_OR_FOREIGN")
    else:
        workflow_allow = [x for x in policy.file_allow if
                          x.startswith(".github/workflows/")]
        if workflow_allow != [PATH] or (
            any(fnmatchcase(PATH, pattern) for pattern in policy.file_deny)
        ):
            problems.append("EXACT_PATH_POLICY_NOT_ADOPTED")
        if not (BRANCH in policy.branch_allow
                or any(fnmatchcase(BRANCH, p) for p in policy.branch_allow)):
            problems.append("BRANCH_POLICY_DENIED")
        if any(fnmatchcase(BRANCH, p) for p in policy.branch_deny):
            problems.append("BRANCH_POLICY_DENIED")
        if "main" not in policy.branch_deny:
            problems.append("PROTECTED_MAIN_DENY_NOT_PRESERVED")
    return DraftPreflight(
        status=("INTENT_MATCHES_PROPOSED_SCOPE_NOT_AUTHORIZED"
                if not problems else "NOT_READY_FOR_PRIVILEGED_REVIEW"),
        reasons=tuple(sorted(set(problems))),
        content_sha256=(sha256(candidate).hexdigest()
                        if isinstance(candidate, bytes) else None),
    )
