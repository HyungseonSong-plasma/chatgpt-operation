"""Read-only Production Schema A/B probe, outside Samuel's Issue selection loop.

This module imports no GitHub mutation adapters, never compiles or dispatches
ActionPlans, and writes only classified provider evidence (not raw responses).
The two requests differ only by goal/observations within a fixed context.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .issue_reasoning import IssueReasoningProposal
from .openai_reasoning_provider import (
    OpenAIReasoningProvider, PRODUCTION_ISSUE_REASONING_SCHEMA,
)
from .reasoning_provider import ProviderRequestFailure, ProviderUnavailable

REPOSITORY = "HyungseonSong-plasma/chatgpt-operation"
EXPECTED_SHA = "b4afd1d69ed32523b369461bc51162482c4a9fb9"
TASK = "Produce one typed Samuel Issue reasoning proposal from the supplied context."

CASES = (
    (
        "A_READ_ONLY",
        "Assess branch naming Ruleset evidence without proposing a mutation",
        "GitHub Ruleset #26695930 is active; agent/branch-ruleset-verify-20261106 "
        "was created at an independently read back SHA, and the feat/* control "
        "was rejected with 422 and remained absent. Analyze the evidence only.",
    ),
    (
        "B_BRANCH_DELETE_INTENT",
        "Assess an owner-approved exact-SHA branch deletion operation",
        "Owner requests deleting only agent/branch-ruleset-verify-20261106 "
        "from HyungseonSong-plasma/chatgpt-operation. The exact expected head "
        "SHA is " + EXPECTED_SHA + ". It is not main and has no open PR. "
        "Use the GITHUB_BRANCH_DELETE skill and registered provider; do not "
        "propose unsupported executor payload shapes.",
    ),
)

_COMMON_CONTEXT: dict[str, Any] = {
    "allowed_reasoning_operations": [
        "analyze", "implement_gap", "propose_revision",
    ],
    "locked_decisions": [
        {
            "decision_id": "github_execution_authority",
            "version": 1,
            "statement": "Mutation is owned by deterministic Samuel execution",
            "invariants": ["typed_execution_evidence", "no_direct_llm_mutation"],
        }
    ],
    "implementation_gaps": [],
    "durable_state": {
        "stage": "define_problem",
        "action_statuses": {},
        "execution_results": {},
    },
    "escalation_constraints": [
        "no_raw_issue_execution", "explicit_revision_for_locked_decisions",
    ],
    "execution_contracts": [
        {
            "capability": "GITHUB_BRANCH_DELETE",
            "owner": "repository-mutation",
            "providers": ["repository-native", "github-connector"],
        }
    ],
}


def schema_digest() -> str:
    normalized = json.dumps(
        PRODUCTION_ISSUE_REASONING_SCHEMA,
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def context_for(case: tuple[str, str, str]) -> dict[str, Any]:
    _, goal, observation = case
    # Round-trip to give each provider call an isolated, identical common map.
    common = json.loads(json.dumps(_COMMON_CONTEXT))
    return {**common, "goal": goal, "observations": [observation]}


def _digest(data: dict[str, Any]) -> str:
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def run_case(provider: Any, case: tuple[str, str, str]) -> dict[str, Any]:
    case_id = case[0]
    context = context_for(case)
    evidence: dict[str, Any] = {
        "case_id": case_id,
        "request_context_sha256": _digest(context),
        "attempts": 1,
        "executed": False,
    }
    try:
        raw = provider.reason(
            task=TASK, context=context, attempt=1, validation_error=None,
        )
        proposal = IssueReasoningProposal.from_dict(raw)
        evidence.update({
            "outcome": "typed_response",
            "operation": proposal.operation,
            "action_plan_present": proposal.action_plan is not None,
            "blocker_present": proposal.blocker is not None,
            "revision_requested": proposal.revision_requested,
        })
    except ProviderRequestFailure as exc:
        evidence.update({
            "outcome": "http_or_network_failure",
            "failure_kind": exc.kind,
            "http_status": exc.status,
            "provider_code": exc.provider_code,
            "retryable": exc.retryable,
        })
    except ProviderUnavailable as exc:
        evidence.update({
            "outcome": "provider_unavailable",
            "exception_type": type(exc).__name__,
        })
    except (TypeError, ValueError) as exc:
        evidence.update({
            "outcome": "response_schema_error",
            "exception_type": type(exc).__name__,
        })
    # Deliberately discard the raw proposal, especially executable plans.
    return evidence


def classify(rows: list[dict[str, Any]]) -> str:
    if len(rows) != 2:
        raise ValueError("expected exactly two comparison cases")
    a, b = rows
    if a["outcome"] == b["outcome"] == "typed_response":
        return "both_typed_responses"
    if a["outcome"] == "typed_response" and b["outcome"] != "typed_response":
        return "delete_context_only_failure"
    if a["outcome"] != "typed_response" and b["outcome"] == "typed_response":
        return "read_context_only_failure"
    failure_keys = ("outcome", "failure_kind", "http_status", "provider_code")
    if all(a.get(k) == b.get(k) for k in failure_keys):
        return "shared_failure_signature"
    return "mixed_failure_signatures"


def run_ab(provider: Any) -> dict[str, Any]:
    if not getattr(provider, "allow_action_plan", False):
        raise ValueError("Production Schema mode is mandatory")
    rows = [run_case(provider, case) for case in CASES]
    return {
        "schema_version": 1,
        "mode": "PRODUCTION_READ_ONLY_AB",
        "model": provider.model,
        "production_schema_sha256": schema_digest(),
        "request_task_sha256": hashlib.sha256(TASK.encode()).hexdigest(),
        "mutation_executed": False,
        "case_results": rows,
        "comparison": classify(rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        provider = OpenAIReasoningProvider.from_env(allow_action_plan=True)
        record = run_ab(provider)
    except ProviderUnavailable as exc:
        record = {
            "schema_version": 1,
            "mode": "PRODUCTION_READ_ONLY_AB",
            "mutation_executed": False,
            "configuration": type(exc).__name__,
            "comparison": "not_executed",
        }
    Path(args.output).write_text(
        json.dumps(record, sort_keys=True, indent=2) + "\n", encoding="utf-8",
    )
    print("SAMUEL_REASONING_AB=" + record["comparison"])
    return 0 if record["comparison"] == "both_typed_responses" else 1


if __name__ == "__main__":
    raise SystemExit(main())
