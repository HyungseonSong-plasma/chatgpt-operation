from __future__ import annotations

import importlib
import sys


def test_normal_paul_init_does_not_load_weekly_telemetry() -> None:
    telemetry_module = "chatgpt_operation.weekly_maintenance"
    sys.modules.pop(telemetry_module, None)
    sys.modules.pop("chatgpt_operation.weekly_schedule", None)

    importlib.import_module("chatgpt_operation.weekly_schedule")

    assert telemetry_module not in sys.modules
