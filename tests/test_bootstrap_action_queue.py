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
