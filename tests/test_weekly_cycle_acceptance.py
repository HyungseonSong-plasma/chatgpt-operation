"""Acceptance coverage for the code-owned weekly maintenance routing."""
from __future__ import annotations

import importlib
import sys
from datetime import date


def test_weekday_and_weekend_phase_mapping() -> None:
    schedule = importlib.import_module("chatgpt_operation.weekly_schedule")

    assert schedule.phase_for_date(date(2026, 9, 28)) == "collect"  # Monday
    assert schedule.phase_for_date(date(2026, 10, 3)) == "analyze"  # Saturday
    assert schedule.phase_for_date(date(2026, 10, 4)) == "close"  # Sunday


def test_schedule_import_is_lazy_with_respect_to_weekly_telemetry() -> None:
    module_name = "chatgpt_operation.weekly_maintenance"
    sys.modules.pop(module_name, None)
    sys.modules.pop("chatgpt_operation.weekly_schedule", None)

    importlib.import_module("chatgpt_operation.weekly_schedule")

    assert module_name not in sys.modules
