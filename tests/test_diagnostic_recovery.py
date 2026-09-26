from chatgpt_operation.controller.action_plan import ExecutorKind
from chatgpt_operation.controller.execution import ExecutionResult, ExecutionStatus
from chatgpt_operation.controller.diagnostic import advance_diagnostic, resolve_from_execution_receipt
from chatgpt_operation.controller.research import ResearchStage, ResearchState


ACTION = "a" * 64


def state(details):
    return ResearchState(
        "issue-44-controller",
        "finish work",
        stage=ResearchStage.EXECUTE,
        diagnostic_recoveries={
            ACTION: {
                "status": "open",
                "fingerprint": [ACTION, "failed", "connector", "RuntimeError", ""],
                "failure": {
                    "status": "failed",
                    "details": details,
                },
                "root_cause": None,
                "corrective_action": None,
                "resolution_evidence": None,
            }
        },
    )


def test_root_cause_advances_only_from_typed_failure_evidence():
    s = state({"provider": "connector", "error_type": "RuntimeError", "provider_status": "403"})
    result = advance_diagnostic(s, ACTION)
    assert result.advanced
    assert s.diagnostic_recoveries[ACTION]["root_cause"] == "provider=connector;error_type=RuntimeError;provider_status=403"


def test_missing_typed_evidence_does_not_invent_root_cause():
    s = state({})
    result = advance_diagnostic(s, ACTION)
    assert not result.advanced
    assert s.diagnostic_recoveries[ACTION]["root_cause"] is None


def test_corrective_action_requires_typed_alternative_provider():
    s = state({
        "provider": "connector",
        "error_type": "RuntimeError",
        "provider_failures": [{"provider": "repository-native"}],
    })
    assert advance_diagnostic(s, ACTION).advanced
    result = advance_diagnostic(s, ACTION)
    assert result.advanced
    assert "repository-native" in s.diagnostic_recoveries[ACTION]["corrective_action"]


def test_resolution_requires_independent_verified_evidence():
    s = state({"provider": "connector", "error_type": "RuntimeError"})
    assert advance_diagnostic(s, ACTION).advanced
    s.diagnostic_recoveries[ACTION]["corrective_action"] = "use repository-native"
    result = advance_diagnostic(s, ACTION)
    assert not result.advanced
    assert s.diagnostic_recoveries[ACTION]["status"] == "open"

    s.diagnostic_recoveries[ACTION]["failure"]["details"]["resolution_verification"] = {
        "verified": True,
        "evidence": "postcondition readback passed",
    }
    result = advance_diagnostic(s, ACTION)
    assert result.advanced
    assert s.diagnostic_recoveries[ACTION]["status"] == "resolved"


def test_verified_pass_receipt_resolves_diagnostic():
    s = state({"provider": "connector", "error_type": "RuntimeError"})
    assert advance_diagnostic(s, ACTION).advanced
    s.diagnostic_recoveries[ACTION]["corrective_action"] = "execute repository-native corrective plan"
    result = ExecutionResult(
        research_id=s.research_id,
        action_id="corrective-action",
        executor=ExecutorKind.GITHUB_NATIVE,
        status=ExecutionStatus.PASS,
        observation="GitHub mutation verified by postcondition readback",
        details={"after": {"merged": True}},
    )
    resolved = resolve_from_execution_receipt(s, ACTION, corrective_result=result)
    assert resolved.advanced
    assert s.diagnostic_recoveries[ACTION]["status"] == "resolved"


def test_failed_or_unverified_corrective_result_cannot_resolve():
    s = state({"provider": "connector", "error_type": "RuntimeError"})
    assert advance_diagnostic(s, ACTION).advanced
    s.diagnostic_recoveries[ACTION]["corrective_action"] = "execute repository-native corrective plan"
    failed = ExecutionResult(
        research_id=s.research_id,
        action_id="corrective-action",
        executor=ExecutorKind.GITHUB_NATIVE,
        status=ExecutionStatus.FAILED,
        observation="postcondition failed",
        retryable=True,
        details={},
    )
    assert not resolve_from_execution_receipt(s, ACTION, corrective_result=failed).advanced
    assert s.diagnostic_recoveries[ACTION]["status"] == "open"

    fake_pass = ExecutionResult(
        research_id=s.research_id,
        action_id="corrective-action",
        executor=ExecutorKind.GITHUB_NATIVE,
        status=ExecutionStatus.PASS,
        observation="claimed pass",
        details={},
    )
    assert not resolve_from_execution_receipt(s, ACTION, corrective_result=fake_pass).advanced
    assert s.diagnostic_recoveries[ACTION]["status"] == "open"
