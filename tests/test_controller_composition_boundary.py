from pathlib import Path


def test_bootstrap_routes_selection_and_planning_through_composition_root():
    workflow=Path(".github/workflows/samuel-bootstrap.yml").read_text(encoding="utf-8")
    assert workflow.count("controller run-cycle")==1
    assert "select_controller_work" not in workflow
    assert "plan_admitted_issue" not in workflow
    assert "ReasoningProviderRegistry()" not in workflow


def test_cli_routes_run_cycle_through_samuel_controller():
    source=Path("src/chatgpt_operation/cli.py").read_text(encoding="utf-8")
    assert "SamuelController(" in source
    assert "controller.run_cycle(" in source


def test_composition_root_owns_internal_selection_and_preflight_calls():
    source=Path("src/chatgpt_operation/controller/runtime.py").read_text(encoding="utf-8")
    assert "select_controller_work(" in source
    assert "plan_admitted_issue(" in source
