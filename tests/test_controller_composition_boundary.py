from pathlib import Path


def test_bootstrap_routes_selection_and_planning_through_composition_root():
    workflow=Path(".github/workflows/samuel-bootstrap.yml").read_text(encoding="utf-8")
    assert workflow.count("controller run-cycle")==1
    assert "select_controller_work" not in workflow
    assert "plan_admitted_issue" not in workflow
    assert "consume_reasoning_submission" not in workflow
    assert "transition_issue_status" not in workflow
    assert "record_action_dispatch_intent" not in workflow
    assert "record_evidence_dispatch_intent" not in workflow
    assert "record_diagnostic_dispatch_intent" not in workflow
    assert "from chatgpt_operation.controller.issue_ingestion import admit_issue" not in workflow
    assert "--issue-json" in workflow
    for forbidden in (
        "dispatch_workflow",
        "observe_dispatch_once",
        "dispatch_native_plan_async",
        "observe_native_intent",
        "observe_native_plan",
        "resume_dispatch_intent",
        "resume_dispatched_action",
        "resume_evidence_dispatch_intent",
        "resume_dispatched_evidence",
        "resume_diagnostic_dispatch_intent",
        "resume_dispatched_diagnostic",
        "record_action_dispatch(",
        "record_evidence_dispatch(",
        "record_diagnostic_dispatch(",
    ):
        assert forbidden not in workflow
    assert workflow.count("controller execute-command")==1
    assert workflow.count("controller persist-state")==3
    for forbidden_state_write in (
        "validate_state_write_precondition",
        "load_state_comment",
        "decode_state",
        "STATE_MARKER",
    ):
        assert forbidden_state_write not in workflow
    assert "ReasoningProviderRegistry()" not in workflow


def test_cli_routes_run_cycle_through_samuel_controller():
    source=Path("src/chatgpt_operation/cli.py").read_text(encoding="utf-8")
    assert "SamuelController(" in source
    assert "controller.run_cycle(" in source


def test_composition_root_owns_internal_selection_and_preflight_calls():
    source=Path("src/chatgpt_operation/controller/runtime.py").read_text(encoding="utf-8")
    assert "select_controller_work(" in source
    assert "plan_admitted_issue(" in source
    assert "consume_reasoning_submission(" in source
    assert "transition_issue_status(" in source
    assert "record_action_dispatch_intent(" in source
    assert "record_evidence_dispatch_intent(" in source
    assert "record_diagnostic_dispatch_intent(" in source


def test_execution_gateway_owns_privileged_actions_runtime_calls():
    source=Path("src/chatgpt_operation/controller/execution_gateway.py").read_text(
        encoding="utf-8"
    )
    assert "dispatch_workflow(" in source
    assert "observe_dispatch_once(" in source
    assert "dispatch_native_plan_async(" in source
    assert "observe_native_intent(" in source
    assert "observe_native_plan(" in source


def test_state_kernel_owns_dispatch_receipt_binding():
    source=Path("src/chatgpt_operation/controller/durable_state.py").read_text(
        encoding="utf-8"
    )
    assert "def apply_dispatch_receipt(" in source
    assert "record_action_dispatch" in source
    assert "record_evidence_dispatch" in source
    assert "record_diagnostic_dispatch" in source


def test_terminal_semantics_are_not_implemented_in_bootstrap_workflow():
    workflow=Path(".github/workflows/samuel-bootstrap.yml").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "apply_action_completion",
        "apply_action_failure",
        "apply_evidence_patch",
        "apply_diagnostic_patch",
        "record_native_dispatch_evidence_failure",
    ):
        assert forbidden not in workflow
    assert workflow.count("controller ingest-terminal")==1


def test_terminal_ingestion_module_owns_terminal_state_semantics():
    source=Path(
        "src/chatgpt_operation/controller/terminal_ingestion.py"
    ).read_text(encoding="utf-8")
    assert "apply_action_completion(" in source
    assert "apply_action_failure(" in source
    assert "apply_evidence_patch(" in source
    assert "apply_diagnostic_patch(" in source
    assert "record_native_dispatch_evidence_failure(" in source
