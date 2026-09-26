from chatgpt_operation.controller.diagnostic import advance_diagnostic
from chatgpt_operation.controller.research import ResearchState


def state(details):
    return ResearchState("r","finish",diagnostic_recoveries={"a":{
        "status":"open","fingerprint":["f"],
        "failure":{"details":details},"root_cause":"provider failed",
        "corrective_action":None,"resolution_evidence":None,
    }})


def test_failed_provider_is_never_selected_as_alternative():
    s=state({"provider":"native","provider_failures":[{"provider":"rest"}],
             "available_providers":["native","rest","workflow"]})
    r=advance_diagnostic(s,"a")
    assert r.advanced
    assert r.evidence=="retry through eligible provider=workflow"


def test_failure_list_without_positive_capability_evidence_cannot_authorize_retry():
    s=state({"provider":"native","provider_failures":[{"provider":"rest"}]})
    r=advance_diagnostic(s,"a")
    assert not r.advanced
    assert "no eligible provider proven" in r.evidence
