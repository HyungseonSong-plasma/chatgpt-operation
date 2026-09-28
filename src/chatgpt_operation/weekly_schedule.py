"""Code-owned weekday/weekend routing for the Paul maintenance cycle.

This module is intentionally import-safe: telemetry is loaded only when a phase
is explicitly executed, so normal Paul initialization does not read weekly data.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

Phase = Literal["collect", "analyze", "improve", "close"]


def phase_for_date(day: date) -> Phase:
    """Return the deterministic UTC-calendar phase for *day*."""
    weekday = day.isoweekday()
    if weekday <= 5:
        return "collect"
    if weekday == 6:
        return "analyze"
    return "close"


def phase_for_utc_date(day: date | None = None) -> Phase:
    """Return the phase for an explicitly supplied UTC date.

    The caller supplies the scheduler's UTC date; no telemetry or skill data is
    read while resolving the phase.
    """
    return phase_for_date(day or date.today())


def run_phase(phase: Phase) -> object:
    """Lazily execute the existing maintenance implementation for *phase*."""
    from .weekly_maintenance import run_phase as execute_phase

    return execute_phase(phase)
