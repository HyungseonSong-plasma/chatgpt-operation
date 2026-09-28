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
    assert 'context="samuel/trusted-validation"' in text
    assert "gh workflow run samuel-bootstrap.yml" in text


def test_bootstrap_does_not_wait_for_validation_artifact():
    text=Path(".github/workflows/samuel-bootstrap.yml").read_text(
        encoding="utf-8"
    )
    assert 'surface=="trusted_validation"' in text
    assert "SAMUEL_WORKER_ID=NOT_REQUIRED surface=trusted_validation" in text
