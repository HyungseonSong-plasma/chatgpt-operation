from pathlib import Path


def test_native_workflow_separates_action_and_dispatch_identity():
    text=Path(".github/workflows/samuel-native-github.yml").read_text(encoding="utf-8")
    assert "samuel_action_id:" in text
    assert "samuel_dispatch_id:" in text
    assert "run-name: Samuel Native GitHub Executor dispatch:" in text
    assert "inputs.samuel_dispatch_id" in text
    assert "inputs.samuel_action_id" in text


def test_native_workflow_binds_provenance_before_artifact_upload():
    text=Path(".github/workflows/samuel-native-github.yml").read_text(encoding="utf-8")
    bind=text.index("- name: Bind execution provenance")
    upload=text.index("- name: Upload typed execution result")
    assert bind < upload
    assert '"workflow_run_id":int(os.environ["GITHUB_RUN_ID"])' in text
    assert '"action_id":action_id' in text
