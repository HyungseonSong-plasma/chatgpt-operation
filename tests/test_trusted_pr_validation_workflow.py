from pathlib import Path


def test_trusted_validation_supports_exact_head_workflow_dispatch():
    text=Path(".github/workflows/samuel-trusted-pr-validation.yml").read_text(
        encoding="utf-8"
    )
    assert "workflow_dispatch:" in text
    for name in (
        "samuel_validation_id:",
        "pr_number:",
        "head_sha:",
        "head_branch:",
    ):
        assert name in text
    assert "trusted validation PR head SHA is stale" in text
    assert "trusted validation PR head branch changed" in text
    assert 'observed["actor"] != "github-actions[bot]"' in text
    assert "trusted validation fallback cannot validate workflow mutations" in text
    assert "actions: read" in text
    assert "Verify ordinary CI fallback boundary" in text
    assert "actions/workflows/ci.yml/runs?event=pull_request" in text
    assert "actions/runs/$run_id/jobs?per_page=100" in text
    assert 'conclusion in {"action_required","failure"}' in text
    assert 'actor=="github-actions[bot]"' in text
    assert "SAMUEL_ORDINARY_CI_ROUTE=BLOCKED_NO_JOBS" in text
    assert "ordinary CI is not eligible for trusted fallback" in text
    assert 'context="samuel/trusted-validation"' in text
    assert "gh workflow run samuel-bootstrap.yml" in text


def test_bootstrap_does_not_wait_for_validation_artifact():
    text=Path(".github/workflows/samuel-bootstrap.yml").read_text(
        encoding="utf-8"
    )
    assert 'surface=="trusted_validation"' in text
    assert "SAMUEL_WORKER_ID=NOT_REQUIRED surface=trusted_validation" in text
