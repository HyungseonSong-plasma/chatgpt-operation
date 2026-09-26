from chatgpt_operation.github.actions_observation import evaluate


def terminal_snapshot(conclusion="success"):
    return {
        "request": {
            "workflow": "123", "event": "workflow_dispatch", "correlation_id": None,
            "head_sha": None, "ref": "main", "run_attempt": None,
            "requested_at": "2026-09-26T09:00:00Z", "visibility_grace_seconds": 60,
        },
        "observation": {
            "observed_at": "2026-09-26T09:01:00Z", "enumeration_complete": True,
            "runs": [{
                "run_id": 1, "workflow": "123", "event": "workflow_dispatch",
                "correlation_id": None, "head_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "ref": "main", "created_at": "2026-09-26T09:00:01Z",
                "run_attempt": 1, "status": "completed", "conclusion": conclusion,
            }],
        },
    }


def test_terminal_observation_preserves_success_conclusion():
    result = evaluate(terminal_snapshot())
    assert result["status"] == "MATCHED_TERMINAL"
    assert result["conclusion"] == "success"


def test_terminal_observation_preserves_failure_conclusion():
    result = evaluate(terminal_snapshot("failure"))
    assert result["status"] == "MATCHED_TERMINAL"
    assert result["conclusion"] == "failure"
