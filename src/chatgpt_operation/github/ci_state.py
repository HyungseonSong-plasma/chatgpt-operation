"""Deterministic synthesis of GitHub commit status and Actions check runs."""
from __future__ import annotations

from typing import Any

PASSING_CHECK_CONCLUSIONS = {"success", "neutral", "skipped"}
FAILING_STATUS_STATES = {"failure", "error"}


class CIStateError(ValueError):
    pass


def synthesize_ci_state(
    combined_status: dict[str, Any] | None,
    check_runs: dict[str, Any] | None,
) -> str:
    """Return success/pending/failure/unknown from authoritative CI surfaces.

    The combined status endpoint can report pending even when there are no
    legacy status contexts. Treat it as a signal only when statuses is
    non-empty so an empty legacy surface cannot mask successful Actions checks.
    """
    signals: list[str] = []

    if isinstance(combined_status, dict):
        statuses = combined_status.get("statuses")
        if isinstance(statuses, list) and statuses:
            state = combined_status.get("state")
            if state in FAILING_STATUS_STATES:
                signals.append("failure")
            elif state == "pending":
                signals.append("pending")
            elif state == "success":
                signals.append("success")

    if isinstance(check_runs, dict):
        runs = check_runs.get("check_runs")
        if isinstance(runs, list) and runs:
            if any(run.get("status") != "completed" for run in runs):
                signals.append("pending")
            elif any(
                run.get("conclusion") not in PASSING_CHECK_CONCLUSIONS
                for run in runs
            ):
                signals.append("failure")
            else:
                signals.append("success")

    if "failure" in signals:
        return "failure"
    if "pending" in signals:
        return "pending"
    if "success" in signals:
        return "success"
    return "unknown"
