"""Evidence-first weekly Paul skill-maintenance primitives.

Normal initialization never imports this module. Scheduled maintenance workflows
invoke it explicitly and preserve raw observations separately from derived summaries.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from typing import Any

from chatgpt_operation.telemetry import aggregate as aggregate_skill_activations
from chatgpt_operation.weekly_schedule import phase_for_day

FAILURE_CLASSES = {
    "REPOSITORY_TEST_FAILURE",
    "CENTRAL_SKILL_CONTRACT_FAILURE",
    "WORKFLOW_CONFIGURATION_FAILURE",
    "EXTERNAL_DEPENDENCY_FAILURE",
    "TRANSIENT_INFRASTRUCTURE_FAILURE",
    "UNKNOWN",
}
ACTIONABLE_FAILURE_CLASSES = {
    "REPOSITORY_TEST_FAILURE",
    "CENTRAL_SKILL_CONTRACT_FAILURE",
    "WORKFLOW_CONFIGURATION_FAILURE",
}


class WeeklyMaintenanceError(ValueError):
    pass


def classify_failure(raw: dict[str, Any]) -> str:
    """Classify only from explicit machine evidence; uncertainty remains UNKNOWN."""
    flags = raw.get("evidence_flags")
    if not isinstance(flags, dict):
        raise WeeklyMaintenanceError("evidence_flags must be an object")
    if flags.get("external_dependency") is True:
        return "EXTERNAL_DEPENDENCY_FAILURE"
    if flags.get("central_skill_contract") is True:
        return "CENTRAL_SKILL_CONTRACT_FAILURE"
    if flags.get("workflow_configuration") is True:
        return "WORKFLOW_CONFIGURATION_FAILURE"
    if flags.get("repository_test") is True:
        return "REPOSITORY_TEST_FAILURE"
    if flags.get("transient_infrastructure") is True:
        return "TRANSIENT_INFRASTRUCTURE_FAILURE"
    return "UNKNOWN"


def normalize_failure(raw: dict[str, Any]) -> dict[str, Any]:
    required = {
        "repository", "workflow", "run_id", "run_attempt", "job", "step",
        "head_sha", "event", "observed_at", "conclusion",
        "failure_signature", "evidence_flags",
    }
    if not isinstance(raw, dict) or set(raw) != required:
        raise WeeklyMaintenanceError("invalid workflow failure schema")
    if raw["conclusion"] != "failure":
        raise WeeklyMaintenanceError("only failure observations are accepted")
    if not isinstance(raw["run_id"], int) or isinstance(raw["run_id"], bool) or raw["run_id"] < 1:
        raise WeeklyMaintenanceError("run_id must be positive")
    if not isinstance(raw["run_attempt"], int) or isinstance(raw["run_attempt"], bool) or raw["run_attempt"] < 1:
        raise WeeklyMaintenanceError("run_attempt must be positive")
    if not isinstance(raw["head_sha"], str) or len(raw["head_sha"]) != 40:
        raise WeeklyMaintenanceError("head_sha must be a 40-character identity")
    try:
        observed = datetime.fromisoformat(str(raw["observed_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise WeeklyMaintenanceError("observed_at must be ISO-8601") from exc
    if observed.tzinfo is None:
        raise WeeklyMaintenanceError("observed_at must be timezone-aware")
    item = dict(raw)
    item["failure_class"] = classify_failure(raw)
    return item


def failure_identity(item: dict[str, Any]) -> str:
    """Retry identity excludes run_attempt so reruns cannot inflate evidence."""
    return "|".join(
        str(item[key])
        for key in (
            "repository", "workflow", "run_id", "job", "step", "failure_signature"
        )
    )


def dedupe_failures(
    raw_failures: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    unique: dict[str, dict[str, Any]] = {}
    duplicate_count = 0
    for raw in raw_failures:
        item = normalize_failure(raw)
        key = failure_identity(item)
        previous = unique.get(key)
        if previous is None:
            unique[key] = item
            continue
        duplicate_count += 1
        if item["run_attempt"] > previous["run_attempt"]:
            unique[key] = item
    return [unique[key] for key in sorted(unique)], duplicate_count


def summarize_week(
    skill_events: list[dict[str, Any]],
    workflow_failures: list[dict[str, Any]],
    *,
    known_skills: list[str] | None = None,
) -> dict[str, Any]:
    """Build a reproducible summary from raw Monday-Friday observations."""
    failures, duplicate_count = dedupe_failures(workflow_failures)
    by_repository = Counter(x["repository"] for x in failures)
    by_workflow = Counter(f"{x['repository']}|{x['workflow']}" for x in failures)
    by_class = Counter(x["failure_class"] for x in failures)
    signatures = Counter(x["failure_signature"] for x in failures)
    return {
        "schema_version": 1,
        "skill_utilization": aggregate_skill_activations(
            skill_events, known_skills=known_skills
        ),
        "workflow_failures": {
            "event_count": len(failures),
            "duplicate_count": duplicate_count,
            "by_repository": dict(sorted(by_repository.items())),
            "by_workflow": dict(sorted(by_workflow.items())),
            "by_class": dict(sorted(by_class.items())),
            "repeated_signatures": {
                key: value
                for key, value in sorted(signatures.items())
                if key and value >= 2
            },
        },
        "normalized_failures": failures,
    }


def select_candidates(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Frequency prioritizes inspection; actionable evidence is still required."""
    failures = list(summary.get("normalized_failures") or [])
    counts = Counter(x["failure_signature"] for x in failures)
    result = []
    seen = set()
    for item in failures:
        signature = item["failure_signature"]
        if (
            signature in seen
            or counts[signature] < 2
            or item["failure_class"] not in ACTIONABLE_FAILURE_CLASSES
        ):
            continue
        seen.add(signature)
        result.append(
            {
                "signature": signature,
                "failure_class": item["failure_class"],
                "occurrences": counts[signature],
                "current_owner": (
                    "central_skill"
                    if item["failure_class"] == "CENTRAL_SKILL_CONTRACT_FAILURE"
                    else "consumer_repository"
                ),
                "evidence_references": sorted(
                    {
                        f"{x['repository']}#{x['run_id']}:{x['job']}:{x['step']}"
                        for x in failures
                        if x["failure_signature"] == signature
                    }
                ),
            }
        )
    return result


def improvement_transactions(
    candidates: list[dict[str, Any]],
    *,
    iso_week: str,
) -> list[dict[str, Any]]:
    """Produce reviewable branch/PR boundaries; never silent direct mutation."""
    return [
        {
            "candidate": candidate,
            "branch": f"samuel/weekly-{iso_week}-{index:02d}",
            "pr": {
                "required": True,
                "auto_merge": False,
                "title": (
                    "Weekly skill maintenance: "
                    + candidate["failure_class"].lower().replace("_", " ")
                ),
            },
            "required_validation": [
                "central tests/self-tests",
                "representative consumer parity",
            ],
            "rollback_boundary": "reviewable PR/revert",
        }
        for index, candidate in enumerate(candidates, start=1)
    ]


def full_week_dry_run() -> dict[str, Any]:
    """CI proof of the Mon-Sun cadence and evidence/candidate boundaries."""
    days = [date(2026, 9, 21 + offset) for offset in range(7)]
    flags = {
        "external_dependency": False,
        "central_skill_contract": True,
        "workflow_configuration": False,
        "repository_test": False,
        "transient_infrastructure": False,
    }
    base = {
        "repository": "HyungseonSong-plasma/moose-test-repo",
        "workflow": "Repository CI",
        "run_attempt": 1,
        "job": "test",
        "step": "contract test",
        "head_sha": "a" * 40,
        "event": "push",
        "conclusion": "failure",
        "failure_signature": "central-contract-regression",
        "evidence_flags": flags,
    }
    failures = [
        {
            **base,
            "run_id": 100 + index,
            "observed_at": f"2026-09-{21 + index:02d}T06:00:00Z",
        }
        for index in range(2)
    ]
    failures.append(
        {
            **base,
            "repository": "HyungseonSong-plasma/sol-adapter-moose",
            "workflow": "SOL Runtime Integration",
            "run_id": 200,
            "job": "integration",
            "step": "dependency fetch",
            "observed_at": "2026-09-23T06:00:00Z",
            "failure_signature": "inl-conda-http-502",
            "evidence_flags": {
                **flags,
                "central_skill_contract": False,
                "external_dependency": True,
            },
        }
    )
    summary = summarize_week([], failures, known_skills=[])
    candidates = select_candidates(summary)
    transactions = improvement_transactions(candidates, iso_week="2026-W39")
    return {
        "schema_version": 1,
        "canonical_timezone": "UTC",
        "days": [
            {"date": day.isoformat(), "phase": phase_for_day(day)}
            for day in days
        ],
        "saturday": {
            "summary": summary,
            "candidates": candidates,
        },
        "sunday": {
            "improvements_merged": [],
            "improvements_proposed": transactions,
            "candidates_rejected": [
                {
                    "signature": "inl-conda-http-502",
                    "reason": "external dependency is not a Skill-quality failure",
                }
            ],
            "known_external_failures_not_actionable_in_skills": [
                "inl-conda-http-502"
            ],
            "consumer_migrations_pending": [],
            "next_week_observation_questions": [
                "Does central-contract-regression recur after review?"
            ],
        },
    }
