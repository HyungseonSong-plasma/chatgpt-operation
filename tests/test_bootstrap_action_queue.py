from chatgpt_operation.controller.bootstrap import BootstrapKind, BootstrapWork, select_controller_work


def test_open_diagnostic_preempts_durable_action_and_static_work():
    work=[BootstrapWork("static",BootstrapKind.WORKFLOW,"x.yml")]
    actions={"a":{"status":"pending","plan":{"schema_version":1}}}
    recoveries={"d":{"status":"open"}}
    selected=select_controller_work(work,diagnostic_recoveries=recoveries,action_queue=actions)
    assert selected[0]=="diagnostic"


def test_durable_action_preempts_static_work():
    work=[BootstrapWork("static",BootstrapKind.WORKFLOW,"x.yml")]
    actions={"a":{"status":"pending","plan":{"schema_version":1}}}
    selected=select_controller_work(work,diagnostic_recoveries={},action_queue=actions)
    assert selected[0]=="action"
    assert selected[1]["action_id"]=="a"


def test_dispatch_intent_preempts_diagnostic_and_pending_work():
    work=[BootstrapWork("static",BootstrapKind.WORKFLOW,"x.yml")]
    actions={
        "intent":{
            "status":"dispatch_intent",
            "plan":{"schema_version":1},
            "dispatch_intent":{"schema_version":1},
        },
        "pending":{"status":"pending","plan":{"schema_version":1}},
    }
    recoveries={"d":{"status":"open"}}
    selected=select_controller_work(
        work,diagnostic_recoveries=recoveries,action_queue=actions
    )
    assert selected[0]=="action_intent"
    assert selected[1]["action_id"]=="intent"


def test_dispatched_action_preempts_new_pending_work():
    actions={
        "active":{
            "status":"dispatched",
            "plan":{"schema_version":1},
            "dispatch_receipt":{"correlation_id":"active"},
        },
        "pending":{"status":"pending","plan":{"schema_version":1}},
    }
    selected=select_controller_work([],diagnostic_recoveries={},action_queue=actions)
    assert selected[0]=="action_observation"
    assert selected[1]["action_id"]=="active"


def test_multiple_in_flight_actions_fail_closed():
    actions={
        "a":{"status":"dispatch_intent","plan":{},"dispatch_intent":{}},
        "b":{"status":"dispatched","plan":{},"dispatch_receipt":{}},
    }
    try:
        select_controller_work([],diagnostic_recoveries={},action_queue=actions)
    except Exception as exc:
        assert "multiple in-flight" in str(exc)
    else:
        raise AssertionError("parallel in-flight durable actions must fail closed")


def test_unknown_action_lifecycle_is_not_silently_ignored():
    actions={"a":{"status":"mystery","plan":{}}}
    try:
        select_controller_work([],diagnostic_recoveries={},action_queue=actions)
    except Exception as exc:
        assert "unsupported lifecycle" in str(exc)
    else:
        raise AssertionError("unknown lifecycle status must fail closed")

def test_evidence_dispatch_intent_preempts_open_diagnostic_and_pending_action():
    actions={"pending":{"status":"pending","plan":{"schema_version":1}}}
    recoveries={
        "e":{
            "status":"needs_evidence",
            "evidence_dispatch":{
                "status":"dispatch_intent",
                "intent":{"schema_version":2},
                "correlation_id":"evidence-x",
            },
        },
        "d":{"status":"open"},
    }
    selected=select_controller_work(
        [],diagnostic_recoveries=recoveries,action_queue=actions
    )
    assert selected[0]=="evidence_intent"
    assert selected[1]["action_id"]=="e"


def test_dispatched_evidence_preempts_new_work():
    recoveries={
        "e":{
            "status":"needs_evidence",
            "evidence_dispatch":{
                "status":"dispatched",
                "intent":{"schema_version":2},
                "correlation_id":"evidence-x",
                "receipt":{"workflow_run_id":99},
            },
        },
    }
    selected=select_controller_work(
        [],diagnostic_recoveries=recoveries,
        action_queue={"p":{"status":"pending","plan":{"schema_version":1}}},
    )
    assert selected[0]=="evidence_observation"


def test_action_and_evidence_cannot_be_in_flight_together():
    actions={
        "a":{
            "status":"dispatched",
            "plan":{"schema_version":1},
            "dispatch_receipt":{"workflow_run_id":1},
        }
    }
    recoveries={
        "e":{
            "status":"needs_evidence",
            "evidence_dispatch":{
                "status":"dispatch_intent",
                "intent":{"schema_version":2},
                "correlation_id":"evidence-x",
            },
        },
    }
    try:
        select_controller_work(
            [],diagnostic_recoveries=recoveries,action_queue=actions
        )
    except Exception as exc:
        assert "multiple in-flight durable workflows" in str(exc)
    else:
        raise AssertionError("parallel external controller work must fail closed")



def test_diagnostic_dispatch_intent_preempts_new_work():
    recoveries={
        "d":{
            "status":"open",
            "diagnostic_dispatch":{
                "status":"dispatch_intent",
                "intent":{"schema_version":2},
                "correlation_id":"diagnostic-x",
            },
        },
    }
    selected=select_controller_work(
        [],diagnostic_recoveries=recoveries,
        action_queue={"p":{"status":"pending","plan":{"schema_version":1}}},
    )
    assert selected[0]=="diagnostic_intent"
    assert selected[1]["action_id"]=="d"


def test_dispatched_diagnostic_preempts_new_work():
    recoveries={
        "d":{
            "status":"open",
            "diagnostic_dispatch":{
                "status":"dispatched",
                "intent":{"schema_version":2},
                "correlation_id":"diagnostic-x",
                "receipt":{"workflow_run_id":99},
            },
        },
    }
    selected=select_controller_work([],diagnostic_recoveries=recoveries)
    assert selected[0]=="diagnostic_observation"


def test_diagnostic_and_action_cannot_be_in_flight_together():
    recoveries={
        "d":{
            "status":"open",
            "diagnostic_dispatch":{
                "status":"dispatch_intent",
                "intent":{"schema_version":2},
                "correlation_id":"diagnostic-x",
            },
        },
    }
    actions={
        "a":{
            "status":"dispatched",
            "plan":{"schema_version":1},
            "dispatch_receipt":{"workflow_run_id":1},
        },
    }
    try:
        select_controller_work(
            [],diagnostic_recoveries=recoveries,action_queue=actions
        )
    except Exception as exc:
        assert "multiple in-flight durable workflows" in str(exc)
    else:
        raise AssertionError("diagnostic and action may not execute concurrently")
