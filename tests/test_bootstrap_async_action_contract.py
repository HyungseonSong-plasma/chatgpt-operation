from pathlib import Path


def bootstrap_workflow() -> str:
    return Path(".github/workflows/samuel-bootstrap.yml").read_text(encoding="utf-8")


def test_bootstrap_native_action_path_is_non_blocking_and_gateway_owned():
    workflow=bootstrap_workflow()
    assert "dispatch_native_plan(" not in workflow
    assert "dispatch_native_plan_async" not in workflow
    assert "observe_native_intent" not in workflow
    assert "observe_native_plan" not in workflow
    assert workflow.count("controller execute-command")==1


def test_execution_gateway_owns_native_action_runtime():
    gateway=Path(
        "src/chatgpt_operation/controller/execution_gateway.py"
    ).read_text(encoding="utf-8")
    assert "dispatch_native_plan_async(" in gateway
    assert "observe_native_intent(" in gateway
    assert "observe_native_plan(" in gateway
