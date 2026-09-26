from chatgpt_operation.controller.durable_state import apply_evidence_patch
from chatgpt_operation.controller.research import ResearchState


def test_evidence_patch_reopens_waiting_diagnostic():
    s=ResearchState("r","finish",diagnostic_recoveries={"a":{
        "status":"needs_evidence","failure":{"details":{}},"evidence_request":{"fingerprint":"f"}
    }},revision=3)
    p=apply_evidence_patch(s,{"action_id":"a","evidence":{"provider":"native"},"revision_delta":1})
    assert s.diagnostic_recoveries["a"]["status"]=="needs_evidence"
    assert p.diagnostic_recoveries["a"]["status"]=="open"
    assert p.diagnostic_recoveries["a"]["failure"]["details"]["provider"]=="native"
    assert p.revision==4
