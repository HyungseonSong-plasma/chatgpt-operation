from chatgpt_operation.controller.durable_state import (
    DurableStateError,
    decode_state,
    encode_state,
    require_fresh_write,
    load_state_comment,
    prepare_state_write,
    apply_diagnostic_patch,
)
from chatgpt_operation.controller.research import ResearchStage, ResearchState


def state(revision=3):
    return ResearchState(
        "issue-44-controller",
        "autonomously finish governed work",
        stage=ResearchStage.EXECUTE,
        diagnostic_recoveries={
            "a" * 64: {
                "status": "open",
                "fingerprint": ["a" * 64, "failed", "provider", "TimeoutError", ""],
                "failure": {"status": "failed"},
                "root_cause": None,
                "corrective_action": None,
                "resolution_evidence": None,
            }
        },
        revision=revision,
    )


def test_issue_ledger_round_trip_preserves_open_diagnosis():
    original = state()
    restored = decode_state(encode_state(original))
    assert restored.research_id == original.research_id
    assert restored.revision == 3
    assert restored.diagnostic_recoveries == original.diagnostic_recoveries


def test_round_trip_preserves_last_reasoning_head_sha():
    current=ResearchState(
        "issue:24",
        "blocked semantic work",
        revision=6,
        last_reasoning_head_sha="c"*40,
    )
    restored=decode_state(encode_state(current))
    assert restored.last_reasoning_head_sha=="c"*40


def test_stale_scheduled_cycle_cannot_overwrite_newer_state():
    try:
        require_fresh_write(state(5), state(5))
    except DurableStateError as exc:
        assert "stale controller state revision" in str(exc)
    else:
        raise AssertionError("same revision must fail closed")


def test_newer_revision_can_replace_current_state():
    require_fresh_write(state(5), state(6))


def test_cross_research_overwrite_fails_closed():
    proposed = state(6)
    proposed.research_id = "different"
    try:
        require_fresh_write(state(5), proposed)
    except DurableStateError as exc:
        assert "different research state" in str(exc)
    else:
        raise AssertionError("cross-research overwrite must fail closed")


def test_terminal_cross_research_rollover_is_allowed():
    current=ResearchState(
        "issue:44",
        "completed root work",
        stage=ResearchStage.EXECUTE,
        action_queue={"done":{"status":"complete"}},
        revision=5,
    )
    proposed=ResearchState(
        "issue:24",
        "next admitted work",
        stage=ResearchStage.DEFINE_PROBLEM,
        revision=2,
    )
    require_fresh_write(current,proposed)
    comments=[{"id":99,"body":encode_state(current)}]
    write=prepare_state_write(comments,proposed)
    assert write["comment_id"]==99
    assert write["expected_previous_revision"]==5
    assert decode_state(write["body"]).research_id=="issue:24"


def test_comment_loader_and_writer_use_single_authoritative_marker():
    current = state(4)
    comments = [{"id": 99, "body": encode_state(current)}]
    loaded = load_state_comment(comments)
    assert loaded is not None and loaded.revision == 4
    proposed = state(5)
    write = prepare_state_write(comments, proposed)
    assert write["comment_id"] == 99
    assert write["expected_previous_revision"] == 4
    assert decode_state(write["body"]).revision == 5


def test_duplicate_state_comments_fail_closed():
    comments = [
        {"id": 1, "body": encode_state(state(4))},
        {"id": 2, "body": encode_state(state(5))},
    ]
    try:
        load_state_comment(comments)
    except DurableStateError as exc:
        assert "multiple authoritative" in str(exc)
    else:
        raise AssertionError("duplicate authoritative state must fail closed")


def test_diagnostic_artifact_patches_only_selected_recovery_and_increments_once():
    current = state(7)
    artifact = {
        "action_id": "a" * 64,
        "phase": "investigate_root_cause",
        "advanced": True,
        "evidence": "provider=connector;error_type=RuntimeError",
        "revision_delta": 1,
        "recovery": {
            **current.diagnostic_recoveries["a" * 64],
            "root_cause": "provider=connector;error_type=RuntimeError",
        },
    }
    proposed = apply_diagnostic_patch(current, artifact)
    assert proposed.revision == 8
    assert current.revision == 7
    assert proposed.diagnostic_recoveries["a" * 64]["root_cause"].startswith("provider=")


def test_nonadvancing_diagnostic_artifact_cannot_mutate_ledger():
    current = state(7)
    artifact = {
        "action_id": "a" * 64,
        "advanced": False,
        "revision_delta": 0,
        "recovery": current.diagnostic_recoveries["a" * 64],
    }
    try:
        apply_diagnostic_patch(current, artifact)
    except DurableStateError as exc:
        assert "exactly one advanced revision" in str(exc)
    else:
        raise AssertionError("WAIT artifact must not mutate durable state")


def test_round_trip_preserves_markdown_fences_inside_state_payload():
    state=ResearchState(
        "issue:44",
        "close issue with markdown",
        revision=3,
        action_queue={
            "a"*64:{
                "status":"complete",
                "completion_result":{
                    "schema_version":1,
                    "research_id":"issue:44",
                    "action_id":"a"*64,
                    "executor":"github_native",
                    "status":"pass",
                    "observation":"closed",
                    "retryable":False,
                    "details":{
                        "mutation":{
                            "body":"example\n```python\nprint('x')\n```\n"
                        }
                    },
                },
            }
        },
    )
    restored=decode_state(encode_state(state))
    assert restored.action_queue==state.action_queue
