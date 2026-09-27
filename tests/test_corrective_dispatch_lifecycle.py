from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.controller.diagnostic import (
    attach_source_plan,
    corrective_dispatch_correlation_id,
    record_corrective_dispatch,
    record_corrective_dispatch_intent,
    resume_corrective_dispatch_intent,
    resume_dispatched_corrective,
)
from chatgpt_operation.controller.research import ResearchStage, ResearchState


HEAD="b"*40


def plan():
    return ActionPlan.from_dict({
        "schema_version":1,
        "research_id":"r",
        "stage":"execute",
        "executor":"github_native",
        "payload":{
            "action":"comment_issue",
            "repository":"o/r",
            "target":{"issue_number":44},
            "preconditions":{"state":"open"},
            "desired_postcondition":{"comment_present":True},
        },
        "expected_observation":"verified",
    })


def state():
    p=plan()
    s=ResearchState(
        "r","finish",stage=ResearchStage.EXECUTE,
        action_queue={p.idempotency_key:{
            "status":"suspended",
            "plan":{
                "schema_version":1,
                "research_id":"r",
                "stage":"execute",
                "executor":"github_native",
                "payload":p.payload,
                "expected_observation":"verified",
                "decision_risk":None,
            },
        }},
        diagnostic_recoveries={p.idempotency_key:{
            "status":"open",
            "fingerprint":[],
            "failure":{"details":{"provider":"primary","available_providers":["fallback"]}},
            "root_cause":"provider failure",
            "corrective_action":"retry through eligible provider=fallback",
            "corrective_provider":"fallback",
            "resolution_evidence":None,
        }},
        revision=5,
    )
    attach_source_plan(s,p.idempotency_key,p)
    return p,s


def test_corrective_dispatch_intent_is_durable_and_reentrant():
    p,s=state()
    before=s.revision
    intent,correlation_id=record_corrective_dispatch_intent(
        s,p.idempotency_key,workflow="samuel-native-github.yml",
        ref="feature",requested_at="2026-09-27T20:00:00Z",
        expected_head_sha=HEAD,
    )
    assert s.revision==before+1
    assert correlation_id==corrective_dispatch_correlation_id(s,p.idempotency_key)
    replay_plan,auth,replay_intent,replay_id=resume_corrective_dispatch_intent(
        s,p.idempotency_key
    )
    assert replay_plan.idempotency_key==p.idempotency_key
    assert auth.corrective_provider=="fallback"
    assert replay_intent==intent
    assert replay_id==correlation_id

    before=s.revision
    second,second_id=record_corrective_dispatch_intent(
        s,p.idempotency_key,workflow="samuel-native-github.yml",
        ref="feature",requested_at="2026-09-27T20:05:00Z",
        expected_head_sha=HEAD,
    )
    assert second==intent
    assert second_id==correlation_id
    assert s.revision==before


def test_corrective_dispatch_requires_authoritative_matching_receipt():
    p,s=state()
    _,correlation_id=record_corrective_dispatch_intent(
        s,p.idempotency_key,workflow="samuel-native-github.yml",
        ref="feature",requested_at="2026-09-27T20:00:00Z",
        expected_head_sha=HEAD,
    )
    try:
        record_corrective_dispatch(s,p.idempotency_key,{
            "correlation_id":correlation_id,"ref":"feature","workflow_run_id":None,
        })
    except ValueError as exc:
        assert "authoritative workflow_run_id" in str(exc)
    else:
        raise AssertionError("corrective receipt without run id must fail closed")

    try:
        record_corrective_dispatch(s,p.idempotency_key,{
            "correlation_id":"foreign","ref":"feature","workflow_run_id":99,
        })
    except ValueError as exc:
        assert "correlation mismatch" in str(exc)
    else:
        raise AssertionError("foreign corrective receipt must fail closed")


def test_dispatched_corrective_round_trip_preserves_authorization():
    p,s=state()
    _,correlation_id=record_corrective_dispatch_intent(
        s,p.idempotency_key,workflow="samuel-native-github.yml",
        ref="feature",requested_at="2026-09-27T20:00:00Z",
        expected_head_sha=HEAD,
    )
    receipt={
        "workflow_path":".github/workflows/samuel-native-github.yml",
        "ref":"feature",
        "correlation_id":correlation_id,
        "workflow_run_id":99,
    }
    record_corrective_dispatch(s,p.idempotency_key,receipt)
    replay_plan,auth,intent,replay_id,persisted=resume_dispatched_corrective(
        s,p.idempotency_key
    )
    assert replay_plan.idempotency_key==p.idempotency_key
    assert auth.corrective_provider=="fallback"
    assert intent.expected_head_sha==HEAD
    assert replay_id==correlation_id
    assert persisted==receipt
