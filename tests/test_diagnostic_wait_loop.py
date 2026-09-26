from chatgpt_operation.controller.bootstrap import select_controller_work
from chatgpt_operation.controller.diagnostic import record_diagnostic_wait
from chatgpt_operation.controller.research import ResearchState


def test_identical_wait_transitions_to_evidence_acquisition():
    s=ResearchState("r","finish",diagnostic_recoveries={"a":{"status":"open"}})
    assert record_diagnostic_wait(s,"a",phase="apply_corrective_action",evidence="missing")=="open"
    assert record_diagnostic_wait(s,"a",phase="apply_corrective_action",evidence="missing")=="needs_evidence"
    selected=select_controller_work([],diagnostic_recoveries=s.diagnostic_recoveries)
    assert selected[0]=="evidence"
    assert selected[1]["action_id"]=="a"


def test_new_wait_fingerprint_resets_attempt_counter():
    s=ResearchState("r","finish",diagnostic_recoveries={"a":{"status":"open"}})
    record_diagnostic_wait(s,"a",phase="investigate_root_cause",evidence="one")
    record_diagnostic_wait(s,"a",phase="investigate_root_cause",evidence="two")
    assert s.diagnostic_recoveries["a"]["status"]=="open"
    assert s.diagnostic_recoveries["a"]["wait"]["attempts"]==1
