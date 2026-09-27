from pathlib import Path


def bootstrap_workflow() -> str:
    return Path(".github/workflows/samuel-bootstrap.yml").read_text(encoding="utf-8")


def test_bootstrap_native_action_path_is_non_blocking():
    workflow=bootstrap_workflow()
    assert "dispatch_native_plan(" not in workflow
    assert "dispatch_native_plan_async" in workflow
    assert '"action_intent"' in workflow
    assert '"action_observation"' in workflow
