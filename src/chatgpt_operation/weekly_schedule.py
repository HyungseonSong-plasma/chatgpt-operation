"""Code-owned weekly cadence over Samuel's existing durable bootstrap scheduler."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any


CANONICAL_TIMEZONE = "UTC"
SCHEDULER_WORKFLOW = ".github/workflows/samuel-bootstrap.yml"
SCHEDULER_CRON = "9 * * * *"
SCHEDULER_CAPABILITY = "existing_scheduled_runtime"
PHASES = ("collect", "analyze", "close")


def phase_for_day(day: date) -> str:
    """Map canonical UTC weekdays to the Paul weekly maintenance phase."""
    if day.weekday() <= 4:
        return "collect"
    if day.weekday() == 5:
        return "analyze"
    return "close"


def canonical_slot(now: datetime) -> dict[str, Any]:
    """Return deterministic UTC slot metadata for one bootstrap invocation."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    current = now.astimezone(timezone.utc)
    iso = current.isocalendar()
    return {
        "date": current.date().isoformat(),
        "iso_week": f"{iso.year}-W{iso.week:02d}",
        "phase": phase_for_day(current.date()),
        "canonical_timezone": CANONICAL_TIMEZONE,
    }


def scheduled_runtime_reasoning_contract(
    now: datetime | None = None,
    *,
    scheduler_surfaces: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Expose the observed bootstrap scheduler as an executable alternative capability."""
    slot = canonical_slot(now or datetime.now(timezone.utc))
    observed = list(scheduler_surfaces or [])
    available = (
        True
        if scheduler_surfaces is None
        else any(
            item.get("workflow") == SCHEDULER_WORKFLOW
            and item.get("event") == "schedule"
            and item.get("cron") == SCHEDULER_CRON
            and item.get("mutation_required") is False
            for item in observed
            if isinstance(item, dict)
        )
    )
    return {
        "schema_version": 1,
        "capability": SCHEDULER_CAPABILITY,
        "existing_durable_scheduler": available,
        "workflow": SCHEDULER_WORKFLOW,
        "cron": SCHEDULER_CRON,
        "canonical_timezone": CANONICAL_TIMEZONE,
        "workflow_file_mutation_required": False,
        "code_owned_phase_routing": True,
        "allowed_implementation_surface": "src/**",
        "phase_mapping": {
            "monday_friday": "collect",
            "saturday": "analyze",
            "sunday": "close",
        },
        "current_slot": slot,
        "observed_scheduler_surfaces": observed,
        "planning_rule": (
            "When workflow-file mutation is unavailable, reuse this existing durable "
            "scheduler and implement cadence/phase behavior in allowed code-owned "
            "surfaces. Do not request governance revision solely to obtain a new "
            "scheduled workflow."
        ),
    }
