from chatgpt_operation.controller.durable_state import (
    DurableStateError,
    decode_state,
    encode_state,
    require_fresh_write,
    load_state_comment,
    prepare_state_write,
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
