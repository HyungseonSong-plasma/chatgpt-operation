"""Bounded evidence inheritance across terminal Samuel workload rollover."""
from __future__ import annotations

import json
import re
from typing import Any

from .research import ResearchState

MAX_INHERITED_EVIDENCE = 16
_SUCCESS_STATUSES = {"pass", "noop"}


def _mentions_issue(value: Any, issue_number: int) -> bool:
    """Match explicit GitHub issue references like #24 without substring collisions."""
    text = value if isinstance(value, str) else json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return re.search(rf"(?<!\d)#{issue_number}(?!\d)", text) is not None


def _successful_terminal_item(item: dict[str, Any]) -> bool:
    if item.get("status") != "complete":
        return False
    result = item.get("completion_result")
    return (
        isinstance(result, dict)
        and str(result.get("status") or "").lower() in _SUCCESS_STATUSES
    )


def _compact_target(target: Any) -> dict[str, Any]:
    if not isinstance(target, dict):
        return {}
    allowed = (
        "number", "name", "branch", "path", "head", "base",
        "expected_head_sha", "workflow", "ref",
    )
    return {
        key: target[key]
        for key in allowed
        if key in target and isinstance(target[key], (str, int, bool))
    }


def _compact_after(result: dict[str, Any]) -> dict[str, Any]:
    details = result.get("details")
    if not isinstance(details, dict):
        return {}
    after = details.get("after")
    if not isinstance(after, dict):
        return {}
    allowed = (
        "merged", "pr_present", "pr_number", "head_sha", "base",
        "result_identity", "status",
    )
    compact = {
        key: after[key]
        for key in allowed
        if key in after and isinstance(after[key], (str, int, bool))
    }
    nested_target = _compact_target(after.get("target"))
    if nested_target:
        compact["target"] = nested_target
    return compact


def _compact_provenance(result: dict[str, Any]) -> dict[str, Any]:
    details = result.get("details")
    if not isinstance(details, dict):
        return {}
    provenance = details.get("provenance")
    if not isinstance(provenance, dict):
        return {}
    allowed = ("workflow_run_id", "run_attempt", "head_sha", "action_id")
    return {
        key: provenance[key]
        for key in allowed
        if key in provenance and isinstance(provenance[key], (str, int))
    }


def inherited_evidence_for_issue(
    state: ResearchState,
    issue_number: int,
) -> list[dict[str, Any]]:
    """Return compact verified evidence explicitly associated with one issue.

    Association is fail-closed:
    - a successful create_pr must explicitly reference #N in title/body;
    - its head branch and observed PR number become trusted correlation keys;
    - successful repository mutations on that branch and a successful merge of
      that PR may then be inherited;
    - other successful actions are inherited only when their own bounded plan
      explicitly references #N.

    The prior action queue itself is never copied into the new workload.
    """
    if not isinstance(issue_number, int) or isinstance(issue_number, bool) or issue_number < 1:
        raise ValueError("issue_number must be positive")

    owned_branches: set[str] = set()
    owned_pr_numbers: set[int] = set()
    explicitly_related_ids: set[str] = set()

    ordered = sorted(state.action_queue.items())
    for action_id, item in ordered:
        if not isinstance(item, dict) or not _successful_terminal_item(item):
            continue
        plan = item.get("plan")
        if not isinstance(plan, dict):
            continue
        payload = plan.get("payload")
        if not isinstance(payload, dict):
            continue
        target = payload.get("target")
        action = payload.get("action")
        relation_surface = {
            "target": target,
            "expected_observation": plan.get("expected_observation"),
        }
        if action == "create_pr" and isinstance(target, dict):
            relation_surface = {
                "title": target.get("title"),
                "body": target.get("body"),
                "expected_observation": plan.get("expected_observation"),
            }
            if _mentions_issue(relation_surface, issue_number):
                explicitly_related_ids.add(action_id)
                head = target.get("head")
                if isinstance(head, str) and head:
                    owned_branches.add(head)
                result = item.get("completion_result")
                if isinstance(result, dict):
                    after = (result.get("details") or {}).get("after")
                    if isinstance(after, dict):
                        pr_number = after.get("pr_number")
                        if isinstance(pr_number, int) and not isinstance(pr_number, bool):
                            owned_pr_numbers.add(pr_number)
            continue
        if _mentions_issue(relation_surface, issue_number):
            explicitly_related_ids.add(action_id)

    evidence: list[dict[str, Any]] = []
    for action_id, item in ordered:
        if len(evidence) >= MAX_INHERITED_EVIDENCE:
            break
        if not isinstance(item, dict) or not _successful_terminal_item(item):
            continue
        plan = item.get("plan")
        result = item.get("completion_result")
        if not isinstance(plan, dict) or not isinstance(result, dict):
            continue
        payload = plan.get("payload")
        if not isinstance(payload, dict):
            continue
        target = payload.get("target")
        action = str(payload.get("action") or "")
        executor = str(plan.get("executor") or "")

        related = action_id in explicitly_related_ids
        if executor == "repository_mutation" and isinstance(target, dict):
            branch = target.get("branch")
            name = target.get("name")
            related = related or (
                isinstance(branch, str) and branch in owned_branches
            ) or (
                isinstance(name, str) and name in owned_branches
            )
        if action == "merge_pr" and isinstance(target, dict):
            number = target.get("number")
            related = related or (
                isinstance(number, int)
                and not isinstance(number, bool)
                and number in owned_pr_numbers
            )
        if not related:
            continue

        item_evidence = {
            "schema_version": 1,
            "source_research_id": state.research_id,
            "source_action_id": action_id,
            "related_issue_number": issue_number,
            "executor": executor,
            "action": action,
            "target": _compact_target(target),
            "expected_observation": str(plan.get("expected_observation") or ""),
            "verified_observation": str(result.get("observation") or ""),
            "verified_status": str(result.get("status") or ""),
        }
        after = _compact_after(result)
        if after:
            item_evidence["after"] = after
        provenance = _compact_provenance(result)
        if provenance:
            item_evidence["provenance"] = provenance
        evidence.append(item_evidence)

    return evidence
