"""Deterministic interpretation of caller-supplied GitHub Actions evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

TERMINAL_STATUSES = {"completed"}


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def evaluate(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return a fail-closed observation status and matching run ids."""
    request = snapshot.get("request")
    observation = snapshot.get("observation")
    if not isinstance(request, dict) or not isinstance(observation, dict):
        return {"status": "OBSERVATION_INCOMPLETE", "matched_run_ids": []}
    if observation.get("enumeration_complete") is not True:
        return {"status": "OBSERVATION_INCOMPLETE", "matched_run_ids": []}

    required_request = ("workflow", "event", "requested_at", "visibility_grace_seconds")
    if any(key not in request for key in required_request):
        return {"status": "OBSERVATION_INCOMPLETE", "matched_run_ids": []}
    if "observed_at" not in observation or not isinstance(observation.get("runs"), list):
        return {"status": "OBSERVATION_INCOMPLETE", "matched_run_ids": []}

    try:
        requested_at = _time(request["requested_at"])
        observed_at = _time(observation["observed_at"])
        grace = int(request["visibility_grace_seconds"])
    except (TypeError, ValueError):
        return {"status": "OBSERVATION_INCOMPLETE", "matched_run_ids": []}

    constraints = ("workflow", "event", "correlation_id", "head_sha", "ref", "run_attempt")
    identity_candidates: list[dict[str, Any]] = []
    eligible: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []

    for run in observation["runs"]:
        if not isinstance(run, dict) or any(k not in run for k in ("run_id", "workflow", "event", "created_at", "run_attempt", "status")):
            return {"status": "OBSERVATION_INCOMPLETE", "matched_run_ids": []}
        supplied = [key for key in constraints if request.get(key) is not None]
        if any(run.get(key) is None for key in supplied):
            # A plausible run lacking evidence required by the request cannot be safely excluded.
            if run.get("workflow") == request.get("workflow") and run.get("event") == request.get("event"):
                return {"status": "OBSERVATION_INCOMPLETE", "matched_run_ids": []}
            continue
        if not all(run.get(key) == request.get(key) for key in supplied):
            continue
        identity_candidates.append(run)
        try:
            created_at = _time(run["created_at"])
        except (TypeError, ValueError):
            return {"status": "OBSERVATION_INCOMPLETE", "matched_run_ids": []}
        if created_at < requested_at:
            stale.append(run)
        else:
            eligible.append(run)

    ids = [run["run_id"] for run in eligible]
    if len(eligible) > 1:
        return {"status": "AMBIGUOUS_MATCH", "matched_run_ids": ids}
    if len(eligible) == 1:
        status = "MATCHED_TERMINAL" if eligible[0]["status"] in TERMINAL_STATUSES else "MATCHED_ACTIVE"
        result = {"status": status, "matched_run_ids": ids}
        if status == "MATCHED_TERMINAL":
            result["conclusion"] = eligible[0].get("conclusion")
        return result
    if stale:
        return {"status": "STALE_ONLY", "matched_run_ids": [run["run_id"] for run in stale]}
    if (observed_at - requested_at).total_seconds() <= grace:
        return {"status": "PENDING_VISIBILITY", "matched_run_ids": []}
    return {"status": "NO_MATCH", "matched_run_ids": []}
