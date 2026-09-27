from pathlib import Path


def test_diagnostic_worker_never_dispatches_native_corrective_work_synchronously():
    text=Path(".github/workflows/samuel-diagnostic-recovery.yml").read_text(
        encoding="utf-8"
    )
    assert "dispatch_native_plan(" not in text
    assert "dispatch_and_wait(" not in text
    assert "timeout_seconds=600" not in text


def test_diagnostic_worker_emits_causal_provenance():
    text=Path(".github/workflows/samuel-diagnostic-recovery.yml").read_text(
        encoding="utf-8"
    )
    assert "samuel_dispatch_id:" in text
    assert "run-name: Samuel Diagnostic Recovery dispatch:" in text
    assert '"workflow_run_id":int(os.environ["GITHUB_RUN_ID"])' in text
    assert '"dispatch_id":dispatch_id' in text


def test_bootstrap_corrective_path_is_async_and_dispatch_identity_is_separate():
    text=Path(".github/workflows/samuel-bootstrap.yml").read_text(encoding="utf-8")
    start=text.index(
        'if selected.get("kind") in {"corrective","corrective_intent","corrective_observation"}:'
    )
    end=text.index(
        'if selected.get("kind") in {"action","action_intent","action_observation"}:',
        start,
    )
    surface=text[start:end]
    assert "dispatch_native_plan_async(" in surface
    assert "observe_native_intent(" in surface
    assert "observe_native_plan(" in surface
    assert "dispatch_id=dispatch_id" in surface
    assert "dispatch_and_wait(" not in surface
