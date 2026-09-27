from chatgpt_operation.controller.bootstrap import (
    BootstrapError,
    select_controller_work,
)


def ready():
    return {
        "status":"open",
        "root_cause":"provider failure",
        "corrective_action":"retry fallback",
        "corrective_provider":"fallback",
        "resolution_evidence":None,
        "source_plan":{"schema_version":1},
    }


def test_ready_corrective_preempts_new_diagnostic_phase():
    selected=select_controller_work(
        [],
        diagnostic_recoveries={"c":ready()},
        action_queue={"p":{"status":"pending","plan":{"schema_version":1}}},
    )
    assert selected[0]=="corrective"
    assert selected[1]["action_id"]=="c"


def test_corrective_intent_preempts_new_work():
    recovery=ready()
    recovery["corrective_dispatch"]={
        "status":"dispatch_intent",
        "intent":{"schema_version":2},
        "correlation_id":"corrective-x",
    }
    selected=select_controller_work(
        [],diagnostic_recoveries={"c":recovery}
    )
    assert selected[0]=="corrective_intent"


def test_dispatched_corrective_preempts_new_work():
    recovery=ready()
    recovery["corrective_dispatch"]={
        "status":"dispatched",
        "intent":{"schema_version":2},
        "correlation_id":"corrective-x",
        "receipt":{"workflow_run_id":99},
    }
    selected=select_controller_work(
        [],diagnostic_recoveries={"c":recovery}
    )
    assert selected[0]=="corrective_observation"


def test_corrective_and_diagnostic_cannot_overlap():
    c=ready()
    c["corrective_dispatch"]={
        "status":"dispatch_intent",
        "intent":{"schema_version":2},
        "correlation_id":"corrective-x",
    }
    d={
        "status":"open",
        "diagnostic_dispatch":{
            "status":"dispatched",
            "intent":{"schema_version":2},
            "correlation_id":"diagnostic-x",
            "receipt":{"workflow_run_id":100},
        },
    }
    try:
        select_controller_work(
            [],diagnostic_recoveries={"c":c,"d":d}
        )
    except BootstrapError as exc:
        assert "multiple in-flight durable workflows" in str(exc)
    else:
        raise AssertionError("corrective and diagnostic workflows may not overlap")
