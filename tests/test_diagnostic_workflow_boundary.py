from pathlib import Path


def workflow() -> str:
    return Path(".github/workflows/samuel-diagnostic-recovery.yml").read_text(
        encoding="utf-8"
    )


def test_diagnostic_worker_cannot_dispatch_or_mutate_repository():
    text=workflow()
    assert "dispatch_native_plan" not in text
    assert "dispatch_and_wait" not in text
    assert "GitHubActionsTransport" not in text
    assert "actions: write" not in text
    assert "issues: write" not in text
    assert "GITHUB_TOKEN" not in text


def test_diagnostic_worker_advances_one_typed_phase_with_dispatch_provenance():
    text=workflow()
    assert "advance_diagnostic" in text
    assert "record_diagnostic_wait" in text
    assert "samuel_dispatch_id:" in text
    assert "required: true" in text
    assert '"dispatch_id":dispatch_id' in text
    assert '"workflow_run_id":int(os.environ["GITHUB_RUN_ID"])' in text
