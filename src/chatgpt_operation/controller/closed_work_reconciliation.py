"""Evidence-only release proposal for Samuel's historical Issue #255 global slot.

Not a state writer, issue label editor, or workflow executor. The native
repository-owned caller must independently authenticate the GitHub readbacks
and submit the resulting revision through the existing StateKernel writer.
The original predispatch escalation remains byte-for-byte unchanged.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any

from .durable_state import can_rollover_state, state_write_request
from .issue_ingestion import transition_issue_status
from .research import ResearchState, StateRetirement

REPO = "HyungseonSong-plasma/chatgpt-operation"
BRANCH = "agent/branch-ruleset-verify-20261106"
EXPECTED_REF_SHA = "b4afd1d69ed32523b369461bc51162482c4a9fb9"
APPROVAL_MARKER = "<!-- samuel-closed-work-reconcile-release-v1 -->"
CLOSURE_MARKER = "<!-- samuel-256-diagnostic-closure-v1 -->"


class ExternalReconciliationError(ValueError):
    """Missing owner authority, contradictory results or unsafe StateKernel."""


def _signed_comment(comments: list[dict[str, Any]], *,
                    number: int | None = None, marker: str | None = None):
    matches = [
        row for row in comments
        if isinstance(row, dict)
        and (number is None or row.get("id") == number)
        and (marker is None or
             isinstance(row.get("body"), str) and
             row["body"].startswith(marker))
    ]
    if len(matches) != 1:
        raise ExternalReconciliationError("missing or ambiguous owner evidence")
    row = matches[0]
    if (
        not isinstance(row.get("user"), dict)
        or row["user"].get("login") != "HyungseonSong-plasma"
        or not isinstance(row.get("body"), str)
        or not isinstance(row.get("created_at"), str)
        or row.get("created_at") != row.get("updated_at")
    ):
        raise ExternalReconciliationError("owner evidence not immutable/authenticated")
    return row


def plan_external_noop_reconciliation(
    state: ResearchState, ledger: dict[str, dict[str, Any]],
    *, repository: str, source_main_sha: str,
    issue255: dict[str, Any], issue256: dict[str, Any],
    comments255: list[dict[str, Any]], comments256: list[dict[str, Any]],
    ref_absent: bool, branch_absent: bool, matching_refs_empty: bool,
) -> tuple[ResearchState, dict[str, dict[str, Any]], dict[str, Any]]:
    """Propose auditable #255 retirement and #256 terminal status, never write.

    The native wrapper obtains all issue, comment, ref and branch evidence via
    authenticated GET. The proposal is fail-closed and exact to this one
    owner-approved historical case, not a general unblocking shortcut.
    """
    if (
        repository != REPO or not isinstance(source_main_sha, str)
        or re.fullmatch(r"[0-9a-f]{40}", source_main_sha) is None
        or ref_absent is not True or branch_absent is not True
        or matching_refs_empty is not True
    ):
        raise ExternalReconciliationError("native exact-head absence proof incomplete")
    if (
        state.research_id != "issue:255"
        or state.revision != 2
        or state.retirement is not None
        or state.action_queue or state.execution_results
        or any(isinstance(x, dict) and x.get("status") in
               {"open", "needs_evidence"}
               for x in state.diagnostic_recoveries.values())
        or len(state.predispatch_failures) != 1
    ):
        raise ExternalReconciliationError("global #255 state is no longer original quiescent escalation")
    fingerprint, failure = next(iter(state.predispatch_failures.items()))
    if (
        not isinstance(failure, dict)
        or failure.get("fingerprint") != fingerprint
        or failure.get("status") != "escalated"
        or failure.get("work_id") != "issue:255"
        or failure.get("occurrences") != 2
        or failure.get("last_error") != "OpenAI reasoning provider HTTP request failed"
    ):
        raise ExternalReconciliationError("historical failure was altered or is not the attested escalation")
    if (
        issue255.get("number") != 255
        or issue255.get("state") != "closed"
        or BRANCH not in str(issue255.get("body"))
        or EXPECTED_REF_SHA not in str(issue255.get("body"))
        or issue256.get("number") != 256
        or issue256.get("state") != "closed"
        or "Read-only reasoning baseline" not in str(issue256.get("title"))
    ):
        raise ExternalReconciliationError("source Issue disposition changed")
    reconciliation = _signed_comment(comments255, number=6735864890)
    if (
        "NO_MUTATION_NEEDED" not in reconciliation["body"]
        or BRANCH not in reconciliation["body"]
        or EXPECTED_REF_SHA not in reconciliation["body"]
        or "404" not in reconciliation["body"]
    ):
        raise ExternalReconciliationError("exact no-mutation-needed postcondition evidence absent")
    approval = _signed_comment(comments255, marker=APPROVAL_MARKER)
    required_approval = {
        "issue:255", "issue:256", BRANCH, EXPECTED_REF_SHA,
        "NO_MUTATION_NEEDED", "preserve escalation",
    }
    if not all(value in approval["body"] for value in required_approval):
        raise ExternalReconciliationError("owner did not authorize this precise release")
    classified = _signed_comment(
        comments256, number=6745233284, marker=CLOSURE_MARKER,
    )
    if not all(x in classified["body"] for x in ("401", "invalid_api_key", "DID NOT SUCCEED")):
        raise ExternalReconciliationError("diagnostic classification cannot be proven")
    if (
        not isinstance(ledger, dict)
        or ledger.get("issue:255", {}).get("status") not in {"reasoning_required", "complete"}
        or ledger.get("issue:256", {}).get("status") not in {"admitted", "complete"}
        or "issue:281" in ledger
    ):
        raise ExternalReconciliationError("Admission ledger does not match pinned state")
    original = deepcopy(failure)
    digest = hashlib.sha256(json.dumps(
        original, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    proof = {
        "kind": "external_noop_retirement_v1",
        "schema_version": 1,
        "repository": repository,
        "work_id": state.research_id,
        "issue_number": 255,
        "target_branch": BRANCH,
        "expected_original_sha": EXPECTED_REF_SHA,
        "source_main_sha": source_main_sha,
        "historical_failure_sha256": digest,
        "postcondition": "NO_MUTATION_NEEDED",
        "provider_executed": False,
        "ref_absent": True,
        "branch_absent": True,
        "matching_refs_empty": True,
        "owner_comment_id": approval["id"],
        "resolution_comment_id": reconciliation["id"],
        "issue256_comment_id": classified["id"],
        "issue256_disposition": "classified_http_401_no_model_success",
    }
    proposed = deepcopy(state)
    proposed.inherited_evidence.append(proof)
    proposed.retirement = StateRetirement(
        reason="externally_reconciled_no_mutation",
        issue_number=255,
        workload_mode="actionable",
        retired_from_revision=state.revision,
    )
    proposed.revision += 1
    if (
        proposed.predispatch_failures != state.predispatch_failures
        or not can_rollover_state(proposed)
    ):
        raise ExternalReconciliationError("historical failure was changed or retirement proof invalid")
    admitted = transition_issue_status(ledger, "issue:255", "complete")
    admitted = transition_issue_status(admitted, "issue:256", "complete")
    return proposed, admitted, proof
