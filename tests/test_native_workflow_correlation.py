from pathlib import Path


def test_native_workflow_exposes_action_id_in_run_name():
    text=Path(".github/workflows/samuel-native-github.yml").read_text(encoding="utf-8")
    assert "samuel_action_id:" in text
    assert "run-name: Samuel Native GitHub Executor action:" in text
    assert "inputs.samuel_action_id" in text
