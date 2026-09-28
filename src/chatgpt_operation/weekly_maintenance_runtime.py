"""Trusted weekly maintenance runtime for evidence-first Paul operations.

This module is invoked only by the reviewed Samuel weekly-maintenance workflow.
It observes public consumer Actions data, preserves raw evidence, and derives
Saturday/Sunday artifacts without mutating Skills or consumer repositories.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Callable
from urllib import error, parse, request

from chatgpt_operation.weekly_maintenance import (
    improvement_transactions,
    select_candidates,
    summarize_week,
    full_week_dry_run,
)

CONSUMERS = (
    "HyungseonSong-plasma/simulation-ontology",
    "HyungseonSong-plasma/sol-adapter-moose",
    "HyungseonSong-plasma/moose-test-repo",
)
DEFAULT_API_URL = "https://api.github.com"
RAW_SCHEMA_VERSION = 1


class WeeklyMaintenanceRuntimeError(RuntimeError):
    pass


class GitHubPublicActions:
    """Read-only GitHub Actions transport with public fallback.

    The workflow token is repository-scoped. Cross-repository reads target only
    the fixed public consumer allowlist above. If an installation token cannot
    read one of those public resources, retry the GET without Authorization.
    """

    def __init__(
        self,
        *,
        token: str | None,
        api_url: str = DEFAULT_API_URL,
        opener: Callable[..., Any] = request.urlopen,
    ):
        self.token = (token or "").strip()
        self.api_url = api_url.rstrip("/")
        self.opener = opener

    def _read(
        self,
        path: str,
        *,
        accept: str = "application/vnd.github+json",
    ) -> bytes:
        url = self.api_url + path
        attempts = [True, False] if self.token else [False]
        last: Exception | None = None
        for authorized in attempts:
            headers = {
                "Accept": accept,
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "samuel-weekly-maintenance",
            }
            if authorized:
                headers["Authorization"] = "Bearer " + self.token
            req = request.Request(url, headers=headers)
            try:
                with self.opener(req, timeout=30) as response:
                    return response.read()
            except error.HTTPError as exc:
                last = exc
                # Only public read failures may fall back to unauthenticated GET.
                if not authorized or exc.code not in {401, 403, 404}:
                    break
            except (error.URLError, TimeoutError) as exc:
                last = exc
                break
        raise WeeklyMaintenanceRuntimeError(
            f"GitHub public Actions GET failed: {path}: {last}"
        )

    def json(self, path: str) -> dict[str, Any]:
        try:
            raw = json.loads(self._read(path).decode())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WeeklyMaintenanceRuntimeError(
                f"GitHub response is not JSON: {path}"
            ) from exc
        if not isinstance(raw, dict):
            raise WeeklyMaintenanceRuntimeError(
                f"GitHub response is not an object: {path}"
            )
        return raw

    def text_or_none(self, path: str) -> str | None:
        try:
            return self._read(path, accept="text/plain").decode(
                errors="replace"
            )
        except WeeklyMaintenanceRuntimeError:
            return None


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise WeeklyMaintenanceRuntimeError("GitHub timestamp is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def utc_week_window(as_of: datetime) -> tuple[datetime, datetime]:
    as_of = as_of.astimezone(timezone.utc)
    monday = as_of.date() - timedelta(days=as_of.weekday())
    start = datetime.combine(monday, time.min, tzinfo=timezone.utc)
    return start, as_of


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized[:80] or "unknown"


def _evidence_flags(step_name: str, log_text: str | None) -> dict[str, bool]:
    name = step_name.lower()
    log = (log_text or "").lower()
    external = bool(
        re.search(
            r"\b(?:http\s*)?(?:502|503|504)\b|"
            r"connection reset|temporary failure|timed out|timeout|"
            r"could not resolve|name resolution|service unavailable",
            log,
        )
    )
    transient = bool(
        re.search(
            r"runner.*lost|hosted runner|rate limit|temporar(?:y|ily)|"
            r"connection reset|timed out|timeout",
            log,
        )
    ) and not external
    repository_test = (
        any(token in name for token in ("test", "pytest", "unittest", "cargo test"))
        or bool(re.search(r"\b(?:assertion|test[s]? failed|failures:)\b", log))
    ) and not external
    workflow_configuration = (
        "workflow" in name and "config" in name
    ) or bool(
        re.search(
            r"invalid workflow|workflow is not valid|yaml syntax|"
            r"unrecognized named-value|unexpected value",
            log,
        )
    )
    central_skill = (
        "skill" in name and "contract" in name
    ) or bool(
        re.search(
            r"(?:chatgpt-operation|central skill).*(?:contract|skill)"
            r"|(?:contract|skill).*(?:chatgpt-operation|central skill)",
            log,
        )
    )
    return {
        "external_dependency": external,
        "central_skill_contract": central_skill and not external,
        "workflow_configuration": workflow_configuration and not external,
        "repository_test": repository_test and not external,
        "transient_infrastructure": transient,
    }


def _failure_signature(
    *,
    workflow: str,
    job: str,
    step: str,
    flags: dict[str, bool],
) -> str:
    category = next((key for key, value in flags.items() if value), "unknown")
    return "::".join(
        (_slug(workflow), _slug(job), _slug(step), _slug(category))
    )


def collect_repository_failures(
    client: GitHubPublicActions,
    repository: str,
    *,
    since: datetime,
    until: datetime,
) -> list[dict[str, Any]]:
    if repository not in CONSUMERS:
        raise WeeklyMaintenanceRuntimeError(
            f"consumer repository is not allowlisted: {repository}"
        )
    runs = client.json(
        "/repos/"
        + repository
        + "/actions/runs?status=completed&per_page=100"
    ).get("workflow_runs", [])
    if not isinstance(runs, list):
        raise WeeklyMaintenanceRuntimeError("workflow_runs must be a list")

    evidence: list[dict[str, Any]] = []
    for run in runs:
        if not isinstance(run, dict) or run.get("conclusion") != "failure":
            continue
        created = _parse_utc(str(run.get("created_at") or ""))
        if created < since or created > until:
            continue
        run_id = run.get("id")
        attempt = run.get("run_attempt", 1)
        if not isinstance(run_id, int) or isinstance(run_id, bool):
            continue
        jobs = client.json(
            f"/repos/{repository}/actions/runs/{run_id}/jobs"
            "?filter=latest&per_page=100"
        ).get("jobs", [])
        if not isinstance(jobs, list):
            raise WeeklyMaintenanceRuntimeError("jobs must be a list")
        for job in jobs:
            if not isinstance(job, dict) or job.get("conclusion") != "failure":
                continue
            job_name = str(job.get("name") or "unknown-job")
            job_id = job.get("id")
            log_text = (
                client.text_or_none(
                    f"/repos/{repository}/actions/jobs/{job_id}/logs"
                )
                if isinstance(job_id, int) and not isinstance(job_id, bool)
                else None
            )
            failed_steps = [
                step
                for step in (job.get("steps") or [])
                if isinstance(step, dict) and step.get("conclusion") == "failure"
            ]
            if not failed_steps:
                failed_steps = [{"name": "<job-level-failure>"}]
            for step in failed_steps:
                step_name = str(step.get("name") or "<unknown-step>")
                flags = _evidence_flags(step_name, log_text)
                evidence.append(
                    {
                        "repository": repository,
                        "workflow": str(run.get("name") or "unknown-workflow"),
                        "run_id": run_id,
                        "run_attempt": int(attempt or 1),
                        "job": job_name,
                        "step": step_name,
                        "head_sha": str(run.get("head_sha") or ""),
                        "event": str(run.get("event") or ""),
                        "observed_at": str(
                            run.get("updated_at")
                            or run.get("created_at")
                            or ""
                        ),
                        "conclusion": "failure",
                        "failure_signature": _failure_signature(
                            workflow=str(run.get("name") or "unknown-workflow"),
                            job=job_name,
                            step=step_name,
                            flags=flags,
                        ),
                        "evidence_flags": flags,
                    }
                )
    return evidence


def collect_all_failures(
    client: GitHubPublicActions,
    *,
    since: datetime,
    until: datetime,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    sources: dict[str, Any] = {}
    for repository in CONSUMERS:
        try:
            items = collect_repository_failures(
                client, repository, since=since, until=until
            )
        except WeeklyMaintenanceRuntimeError as exc:
            sources[repository] = {
                "status": "unavailable",
                "error": str(exc),
            }
            continue
        failures.extend(items)
        sources[repository] = {
            "status": "observed",
            "failure_records": len(items),
        }
    return failures, sources


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n"
            for item in values
        ),
        encoding="utf-8",
    )


def execute_phase(
    phase: str,
    *,
    client: GitHubPublicActions,
    output_dir: str | Path,
    as_of: datetime,
    lookback_days: int = 2,
) -> dict[str, Any]:
    if phase not in {"collect", "analyze", "close", "dry_run"}:
        raise WeeklyMaintenanceRuntimeError(f"unsupported phase: {phase}")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    if phase == "dry_run":
        result = full_week_dry_run()
        result["execution"] = {
            "mode": "dry_run",
            "consumer_scope": list(CONSUMERS),
            "mutation_performed": False,
        }
        write_json(output / "full-week-dry-run.json", result)
        write_json(
            output / "manifest.json",
            {
                "schema_version": RAW_SCHEMA_VERSION,
                "phase": phase,
                "canonical_timezone": "UTC",
                "consumer_scope": list(CONSUMERS),
                "mutation_performed": False,
            },
        )
        return result

    if phase == "collect":
        since = as_of.astimezone(timezone.utc) - timedelta(days=lookback_days)
    else:
        since, _ = utc_week_window(as_of)
    until = as_of.astimezone(timezone.utc)
    failures, sources = collect_all_failures(
        client, since=since, until=until
    )

    # Issue #23 is the authoritative availability proof for skill activation
    # telemetry. Weekly maintenance consumes explicit skill-event inputs when
    # present; absence is recorded as zero observed events, never as zero usage.
    skill_events: list[dict[str, Any]] = []
    write_jsonl(output / "raw" / "workflow-failures.jsonl", failures)
    write_jsonl(output / "raw" / "skill-activations.jsonl", skill_events)
    manifest = {
        "schema_version": RAW_SCHEMA_VERSION,
        "phase": phase,
        "canonical_timezone": "UTC",
        "window": {
            "since": since.isoformat(),
            "until": until.isoformat(),
        },
        "consumer_scope": list(CONSUMERS),
        "workflow_failure_sources": sources,
        "workflow_failure_records": len(failures),
        "skill_telemetry": {
            "source_issue": 23,
            "status": "available_zero_events_observed",
            "event_records": 0,
            "semantic": (
                "zero observed events is not evidence of zero Skill usage"
            ),
        },
        "mutation_performed": False,
    }
    write_json(output / "manifest.json", manifest)

    if phase == "collect":
        return manifest

    summary = summarize_week(
        skill_events,
        failures,
        known_skills=[],
    )
    candidates = select_candidates(summary)
    write_json(output / "weekly-summary.json", summary)
    write_json(output / "candidates.json", candidates)
    result: dict[str, Any] = {
        "manifest": manifest,
        "summary": summary,
        "candidates": candidates,
    }
    if phase == "close":
        iso = as_of.astimezone(timezone.utc).date().isocalendar()
        iso_week = f"{iso.year}-W{iso.week:02d}"
        transactions = improvement_transactions(
            candidates,
            iso_week=iso_week,
        )
        closure = {
            "schema_version": 1,
            "improvements_merged": [],
            "improvements_proposed": transactions,
            "candidates_rejected": [],
            "known_external_failures_not_actionable_in_skills": sorted(
                {
                    item["failure_signature"]
                    for item in summary["normalized_failures"]
                    if item["failure_class"] == "EXTERNAL_DEPENDENCY_FAILURE"
                }
            ),
            "consumer_migrations_pending": [],
            "next_week_observation_questions": [
                "Do repeated actionable signatures recur after review?"
            ],
            "silent_direct_mutation": False,
        }
        write_json(output / "improvement-transactions.json", transactions)
        write_json(output / "sunday-closure.json", closure)
        result["closure"] = closure
    return result


def _parse_as_of(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise WeeklyMaintenanceRuntimeError("--as-of must include timezone")
    return parsed.astimezone(timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run trusted Samuel weekly maintenance observation"
    )
    parser.add_argument(
        "--phase",
        required=True,
        choices=("collect", "analyze", "close", "dry_run"),
    )
    parser.add_argument("--output", default="samuel-weekly-output")
    parser.add_argument("--as-of")
    parser.add_argument("--lookback-days", type=int, default=2)
    args = parser.parse_args(argv)
    if args.lookback_days < 1 or args.lookback_days > 31:
        parser.error("--lookback-days must be in [1, 31]")
    try:
        result = execute_phase(
            args.phase,
            client=GitHubPublicActions(
                token=os.environ.get("GITHUB_TOKEN"),
                api_url=os.environ.get("GITHUB_API_URL", DEFAULT_API_URL),
            ),
            output_dir=args.output,
            as_of=_parse_as_of(args.as_of),
            lookback_days=args.lookback_days,
        )
    except WeeklyMaintenanceRuntimeError as exc:
        print(f"SAMUEL_WEEKLY_MAINTENANCE=HARD_STOP {exc}")
        return 2
    print(
        "SAMUEL_WEEKLY_MAINTENANCE=PASS "
        + f"phase={args.phase} output={args.output}"
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
