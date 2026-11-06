"""DEA human-only emergency environment configuration *preflight*.

Checks snapshots from GitHub GET responses. This is NOT approval or activation.
No actor-controlled JSON can grant a force operation, clear repository policy,
deploy a workflow, attest a user, or waive independent review.
"""
from __future__ import annotations

from typing import Any

ENV_NAME = "dea-human-break-glass"
MAIN_REF = "refs/heads/main"


def assess_human_environment(
    environment: dict[str, Any] | None,
    branch_policies: dict[str, Any] | None,
    rulesets: list[dict[str, Any]] | None,
    *, nominated_human_logins: set[str],
) -> dict[str, Any]:
    """Inspect configuration evidence, never execute or confer permissions.

    Snapshot freshness and owner identity must be authenticated by the
    external GitHub reader; the API cannot establish a person is human.
    """
    problems: list[str] = []
    if not isinstance(environment, dict) or environment.get("name") != ENV_NAME:
        problems.append("ENVIRONMENT_NOT_VERIFIED")
        environment = {}
    if not nominated_human_logins or any(
        not isinstance(x, str) or not x or x.endswith("[bot]")
        for x in nominated_human_logins
    ):
        problems.append("NAMED_HUMAN_ALLOWLIST_REQUIRED")
    rules = environment.get("protection_rules")
    reviewers = [
        r for r in rules if isinstance(r, dict)
        and r.get("type") == "required_reviewers"
    ] if isinstance(rules, list) else []
    if len(reviewers) != 1:
        problems.append("REQUIRED_REVIEWERS_NOT_CONFIGURED")
    else:
        specified = reviewers[0].get("reviewers")
        entries = specified if isinstance(specified, list) else []
        logins: set[str] = set()
        eligible = bool(entries) and len(entries) <= 6
        for item in entries:
            if not isinstance(item, dict) or item.get("type") != "User":
                eligible = False
                continue
            user = item.get("reviewer")
            login = user.get("login") if isinstance(user, dict) else None
            if not isinstance(login, str) or not login or login.endswith("[bot]"):
                eligible = False
                continue
            logins.add(login)
        if not eligible or not logins or logins != nominated_human_logins:
            problems.append("REVIEWERS_NOT_EXACT_NAMED_HUMAN_ALLOWLIST")
    if any(isinstance(r, dict) and r.get("type") == "wait_timer"
           and r.get("wait_timer", 0) != 0 for r in (rules or [])
           if isinstance(rules, list)):
        problems.append("WAIT_TIMER_NOT_ZERO")
    policy = environment.get("deployment_branch_policy")
    if not isinstance(policy, dict) or (
        policy.get("protected_branches") is not False
        or policy.get("custom_branch_policies") is not True
    ):
        problems.append("SELECTED_BRANCH_POLICY_REQUIRED")
    if not isinstance(branch_policies, dict) or (
        type(branch_policies.get("total_count")) is not int
        or branch_policies["total_count"] != 1
        or not isinstance(branch_policies.get("branch_policies"), list)
        or len(branch_policies["branch_policies"]) != 1
        or not isinstance(branch_policies["branch_policies"][0], dict)
        or branch_policies["branch_policies"][0].get("name") != "main"
    ):
        problems.append("MAIN_ONLY_BRANCH_POLICY_NOT_VERIFIED")
    # Require full ruleset detail, not the truncated list-ruleset snapshot.
    matched = [
        r for r in rulesets or []
        if isinstance(r, dict) and r.get("enforcement") == "active"
        and r.get("target") == "branch"
        and isinstance(r.get("conditions"), dict)
        and isinstance(r["conditions"].get("ref_name"), dict)
        and r["conditions"]["ref_name"].get("include") == [MAIN_REF]
        and r["conditions"]["ref_name"].get("exclude") == []
    ] if isinstance(rulesets, list) else []
    protected = False
    for r in matched:
        detail = r.get("rules")
        kinds = {
            x.get("type") for x in detail if isinstance(x, dict)
        } if isinstance(detail, list) else set()
        if {"pull_request", "required_status_checks", "non_fast_forward",
            "deletion"}.issubset(kinds):
            status_rules = [x for x in detail if isinstance(x, dict)
                            and x.get("type") == "required_status_checks"]
            if any(isinstance(x.get("parameters"), dict) and
                   any(z.get("context") == "test" for z in
                       x["parameters"].get("required_status_checks", [])
                       if isinstance(z, dict))
                   for x in status_rules):
                protected = True
    if not protected:
        problems.append("MAIN_RULESET_WITH_CI_AND_PR_PROTECTION_NOT_VERIFIED")
    # GitHub GET Environment schema may not independently reveal whether
    # administrators can bypass protection. Require human UI inspection.
    return {
        "schema_version": 1,
        "status": ("CONFIGURATION_SNAPSHOT_MATCH"
                   if not problems else "CONFIGURATION_INCOMPLETE"),
        "missing_protections": sorted(set(problems)),
        "human_admin_bypass_setting": "REQUIRES_HUMAN_UI_CONFIRMATION",
        "github_human_identity": "NOT_ATTESTED_BY_THIS_CHECK",
        "reviewer_permission": "NOT_ATTESTED_BY_THIS_CHECK",
        "workflow_producer_deployed": False,
        "actual_deployment_approval_test": "NOT_PERFORMED",
        "current_repo_policy_workflow_denial": "NOT_CLEARED",
        "human_only_break_glass_active": False,
        "controller_force_execution_authorized": False,
        "repository_mutation_authorized": False,
    }
