"""Workload-gated Samuel watchdog: retry *stalled* opted-in work after 1 hour.

Never synthesizes ActionPlans, merges PRs, or authorizes cross-repository writes.
The existing bootstrap owns admitted Issue execution and terminal continuation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from .issue_ingestion import ADMISSION_LABEL


class TaskWatchdogError(ValueError):
    """Evidence incomplete or malformed; do not dispatch a speculative wake."""


_RECOVERABLE = frozenset({"admitted", "reasoning_required", "planned", "active"})
_SUSPENDED = frozenset({"blocked", "revision_required", "complete"})
_KNOWN = _RECOVERABLE | _SUSPENDED
_BUSY = frozenset({"queued", "in_progress", "waiting", "requested", "pending"})


@dataclass(frozen=True)
class WatchdogDecision:
    status: Literal["WAKE", "IDLE", "BUSY", "DEFER", "PAUSED"]
    reason: str
    work_ids: tuple[str, ...]
    latest_run_at: str | None = None

    def to_document(self) -> dict[str, Any]:
        return asdict(self)


def _parse_utc(value: str, *, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise TaskWatchdogError(field + " timestamp missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TaskWatchdogError(field + " timestamp invalid") from exc
    if parsed.utcoffset() is None:
        raise TaskWatchdogError(field + " timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def decide_task_wake(
    *, issues: list[dict[str, Any]], admitted_work: dict[str, dict[str, Any]],
    bootstrap_runs: list[dict[str, Any]], now: datetime,
    recovery_seconds: int = 3600, complete_issue_scan: bool = True,
    complete_active_run_scan: bool = True,
) -> WatchdogDecision:
    """Wake iff opted-in unresolved work exists and no bootstrap ran for >= 1h.

    Github's hourly cron is a *liveness check*, not a work-creation trigger.
    A currently queued/running bootstrap always wins over timeout-based
    recovery. Empty/blocked/terminal queues do not run the Controller.
    """
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise TaskWatchdogError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    if not isinstance(recovery_seconds, int) or isinstance(recovery_seconds, bool) or recovery_seconds < 3600:
        raise TaskWatchdogError("recovery interval cannot be shorter than one hour")
    if not complete_issue_scan or not complete_active_run_scan:
        raise TaskWatchdogError("incomplete live issue/run enumeration")
    if not isinstance(issues, list) or not isinstance(admitted_work, dict) or not isinstance(bootstrap_runs, list):
        raise TaskWatchdogError("expected exact live issue, ledger and run collections")

    eligible: list[str] = []
    suspended: list[str] = []
    seen: set[int] = set()
    for issue in issues:
        if not isinstance(issue, dict):
            raise TaskWatchdogError("invalid issue entry")
        number = issue.get("number")
        if type(number) is not int or number < 1 or number in seen:
            raise TaskWatchdogError("invalid/duplicated issue number")
        seen.add(number)
        if issue.get("pull_request") is not None:
            continue
        labels = issue.get("labels")
        if not isinstance(labels, list):
            raise TaskWatchdogError("issue labels not attested")
        names = {
            x if isinstance(x, str) else x.get("name")
            for x in labels if isinstance(x, (str, dict))
        }
        if ADMISSION_LABEL not in names or issue.get("state") != "open":
            continue
        if number == 44:
            raise TaskWatchdogError("Controller state Issue #44 cannot be admitted as work")
        work_id = f"issue:{number}"
        record = admitted_work.get(work_id)
        if record is not None:
            if not isinstance(record, dict) or record.get("work_id") != work_id or record.get("issue_number") != number:
                raise TaskWatchdogError("admitted issue identity mismatch")
            status = record.get("status")
            if status not in _KNOWN:
                raise TaskWatchdogError("unknown admitted issue lifecycle status")
            if status in _SUSPENDED:
                suspended.append(work_id)
                continue
        # An opted-in issue may precede first successful ledger persistence.
        eligible.append(work_id)

    if not eligible:
        return WatchdogDecision("PAUSED" if suspended else "IDLE",
                                "no runnable admitted work", tuple(sorted(suspended)))
    if not bootstrap_runs:
        return WatchdogDecision("WAKE", "runnable work has no bootstrap run",
                                tuple(sorted(eligible)))

    last = None
    for run in bootstrap_runs:
        if not isinstance(run, dict):
            raise TaskWatchdogError("invalid bootstrap run")
        status = run.get("status")
        if status in _BUSY:
            return WatchdogDecision("BUSY", "bootstrap queued or running",
                                    tuple(sorted(eligible)))
        if status != "completed":
            raise TaskWatchdogError("unknown bootstrap run state")
        if not isinstance(run.get("id"), int) or run["id"] < 1:
            raise TaskWatchdogError("missing bootstrap run identity")
        observed = _parse_utc(run.get("updated_at"), field="bootstrap updated_at")
        if observed > now + timedelta(minutes=5):
            raise TaskWatchdogError("bootstrap evidence comes from the future")
        last = max(last, observed) if last is not None else observed

    if last is None:
        raise TaskWatchdogError("no timestamped bootstrap observation")
    elapsed = (now - last).total_seconds()
    if elapsed < recovery_seconds:
        return WatchdogDecision("DEFER", "last bootstrap is younger than recovery interval",
                                tuple(sorted(eligible)), last.isoformat())
    return WatchdogDecision("WAKE", "runnable task stalled for >= 1 hour",
                            tuple(sorted(eligible)), last.isoformat())
