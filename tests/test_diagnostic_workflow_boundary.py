from pathlib import Path


def workflow() -> str:
    return Path(".github/workflows/samuel-diagnostic-recovery.yml").read_text(
        encoding="utf-8"
    )


def test_diagnostic_worker_cannot_dispatch_or_mutate_repository():
    text=workflow()
    for forbidden in (
        "dispatch_native_plan",
        "dispatch_and_wait",
        "GitHubActionsTransport",
        "execution_result_artifact_metadata",
        "GITHUB_TOKEN",
        "actions: write",
        "issues: write",
        "recovery_authorization",
        "corrective_plan_from_recovery",
    ):
        assert forbidden not in text


def test_diagnostic_worker_advances_one_typed_phase_with_dispatch_provenance():
    text=workflow()
    assert "advance_diagnostic" in text
    assert "record_diagnostic_wait" in text
    assert "samuel_dispatch_id:" in text
    assert "required: true" in text
    assert '"dispatch_id":dispatch_id' in text
    assert '"workflow_run_id":int(os.environ["GITHUB_RUN_ID"])' in text


def test_bootstrap_routes_corrective_through_root_command_and_terminal_ingestion():
    text=Path(".github/workflows/samuel-bootstrap.yml").read_text(
        encoding="utf-8"
    )
    assert "--corrective-run-id-result samuel-corrective-run-id.txt" in text
    assert 'surface="corrective"' in text
    assert '"corrective":"samuel-execution-result.json"' in text
