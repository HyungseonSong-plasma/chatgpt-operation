from __future__ import annotations

import importlib


def test_issue_23_equivalent_skill_activation_event_source_exists() -> None:
    module = importlib.import_module(
        "chatgpt_operation.controller.skill_telemetry"
    )

    assert module.__file__
    public_symbols = {
        name for name in vars(module) if not name.startswith("_")
    }
    assert public_symbols
