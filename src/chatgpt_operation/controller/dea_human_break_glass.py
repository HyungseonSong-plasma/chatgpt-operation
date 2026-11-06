"""DEA v0.2 human-exclusive emergency authority requests.

This module only prepares audit-ready, tightly scoped requests. It cannot
authenticate a GitHub user, grant a privilege or perform a forced action.
Only GitHub's protected human-controlled lane may make the decision.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from typing import Any

_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_ACTIONS = frozenset({
    "EXPEDITE_EVIDENCE_REVIEW",
    "REQUEST_PROTECTED_PRODUCER_RUN",
    "REQUEST_WORKFLOW_POLICY_ADOPTION",
    "REQUEST_HUMAN_ONLY_MANUAL_RECOVERY",
})
_MAX_MINUTES = 30


class EmergencyAuthorityError(ValueError):
    pass


def _check(ok: bool, message: str) -> None:
    if not ok:
        raise EmergencyAuthorityError(message)


def _time(value: str) -> datetime:
    _check(isinstance(value, str), "time must be UTC ISO 8601")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EmergencyAuthorityError("invalid ISO timestamp") from exc
    _check(parsed.tzinfo is not None
           and parsed.utcoffset() == timedelta(0),
           "exact UTC timestamp required")
    return parsed


def prepare_emergency_request(
    *, repository: str, target_head_sha: str, action: str,
    work_id: str, reason_code: str,
    created_at_utc: str, expires_at_utc: str,
    run_id: int | None = None,
    artifact_id: int | None = None,
) -> dict[str, Any]:
    """Create a one-time *request*, never authorization.

    A chat user, tool, bot, issue comment or manifest cannot self-attest
    the approver role. Security/policy denials remain binding.
    """
    _check(isinstance(repository, str) and bool(_REPO.fullmatch(repository)),
           "invalid repository")
    _check(isinstance(target_head_sha, str)
           and bool(_SHA40.fullmatch(target_head_sha)),
           "exact source head required")
    _check(action in _ACTIONS, "unapproved emergency action")
    _check(isinstance(work_id, str) and re.fullmatch(r"[A-Za-z0-9_.:#/-]{1,100}", work_id) is not None,
           "stable work ID required")
    _check(reason_code in {
        "TIME_CRITICAL_VERIFICATION",
        "MISSING_OR_INVALID_ARTIFACT",
        "BLOCKED_PROTECTED_PRODUCER",
        "BLOCKED_POLICY_GATE",
    }, "unknown urgency reason")
    _check(run_id is None or type(run_id) is int and run_id > 0,
           "invalid run ID")
    _check(artifact_id is None or type(artifact_id) is int and artifact_id > 0,
           "invalid artifact ID")
    _check(artifact_id is None or run_id is not None,
           "artifact requires exact run")
    start = _time(created_at_utc)
    end = _time(expires_at_utc)
    _check(timedelta(0) < end - start <= timedelta(minutes=_MAX_MINUTES),
           "emergency request window must be at most 30 minutes")
    scope = {
        "repository": repository,
        "target_head_sha": target_head_sha,
        "action": action,
        "work_id": work_id,
        "reason_code": reason_code,
        "created_at_utc": start.isoformat(),
        "expires_at_utc": end.isoformat(),
        "run_id": run_id,
        "artifact_id": artifact_id,
    }
    digest = sha256(json.dumps(scope, sort_keys=True,
                               separators=(",", ":")).encode()).hexdigest()
    return {
        "schema_version": 1,
        "request_id": "dea-human-emergency-" + digest[:24],
        "status": "WAITING_FOR_AUTHENTICATED_HUMAN",
        "scope": scope,
        "approver_type": "NAMED_GITHUB_HUMAN_ONLY",
        "github_environment": "dea-human-break-glass",
        "github_required_reviewers": "NOT_CONFIGURED_BY_THIS_MODULE",
        "github_human_identity_attested": False,
        "self_approval_allowed": False,
        "github_app_or_bot_approval_allowed": False,
        "one_use": True,
        "max_duration_minutes": _MAX_MINUTES,
        "credential_delegation_to_ai": False,
        "force_command_dispatchable_by_controller": False,
        "github_rule_or_policy_override": False,
        "github_tool_safety_override": False,
        "preserve_audit_evidence": True,
        "human_review_required": True,
        "pareto_eligible": False,
        "champion": None,
        "repository_mutation_authorized": False,
    }


def assess_untrusted_force_claim(
    request: dict[str, Any], *,
    claimed_approval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """No caller-supplied approval JSON can elevate a command.

    External trusted GitHub environment/ruleset controls have exclusive
    execution authority. This function never authorizes force execution.
    """
    _check(isinstance(request, dict)
           and request.get("status") == "WAITING_FOR_AUTHENTICATED_HUMAN"
           and request.get("force_command_dispatchable_by_controller") is False,
           "unrecognized emergency request")
    _check(isinstance(request.get("request_id"), str)
           and request["request_id"].startswith("dea-human-emergency-"),
           "invalid emergency request identity")
    _check(claimed_approval is None or isinstance(claimed_approval, dict),
           "malformed claimed approval")
    return {
        "request_id": request["request_id"],
        "status": "EXTERNAL_HUMAN_GITHUB_GATE_REQUIRED",
        "claimed_approval_is_authority": False,
        "human_identity": "NOT_VERIFIED_BY_THIS_MODULE",
        "reviewer_role": "NOT_VERIFIED_BY_THIS_MODULE",
        "policy_clearance": "NOT_VERIFIED_BY_THIS_MODULE",
        "may_prepare_facts": True,
        "may_request_prioritized_human_review": True,
        "may_execute_force": False,
        "may_waive_github_ruleset": False,
        "may_change_workflow_policy": False,
        "may_merge_or_promote": False,
        "repository_mutation_authorized": False,
    }
