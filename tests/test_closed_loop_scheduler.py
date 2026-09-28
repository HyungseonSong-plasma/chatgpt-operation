from pathlib import Path

from chatgpt_operation.controller.bootstrap import select_controller_work
from chatgpt_operation.controller.durable_state import can_rollover_state
from chatgpt_operation.controller.issue_ingestion import discover_admissible_issues
from chatgpt_operation.controller.research import ResearchState


def test_pending_action_preempts_new_workload():
    selected=select_controller_work(
        [],
        action_queue={
            "action-a":{
                "status":"pending",
                "plan":{"schema_version":1},
            }
        },
        admitted_work={
            "issue:24":{
                "work_id":"issue:24",
                "status":"admitted",
            }
        },
    )
    assert selected[0]=="action"
    assert selected[1]["action_id"]=="action-a"


def test_error_recovery_preempts_pending_action():
    selected=select_controller_work(
        [],
        diagnostic_recoveries={
            "action-a":{
                "status":"open",
                "root_cause":None,
                "corrective_action":None,
                "resolution_evidence":None,
            }
        },
        action_queue={
            "action-b":{
                "status":"pending",
                "plan":{"schema_version":1},
            }
        },
    )
    assert selected[0]=="diagnostic"
    assert selected[1]["action_id"]=="action-a"


def test_empty_work_queue_refills_from_explicit_samuel_opt_in():
    discovered=discover_admissible_issues(
        {},
        [
            {
                "number":24,
                "title":"telemetry",
                "body":"collect telemetry",
                "html_url":"https://github.com/o/r/issues/24",
                "state":"open",
                "labels":["samuel"],
            },
            {
                "number":25,
                "title":"unmanaged",
                "body":"must remain outside Samuel",
                "html_url":"https://github.com/o/r/issues/25",
                "state":"open",
                "labels":["bug"],
            },
        ],
    )
    assert list(discovered)==["issue:24"]
    assert discovered["issue:24"]["status"]=="admitted"


def test_terminal_state_can_roll_to_next_workload():
    state=ResearchState("issue:44","done")
    state.action_queue={
        "done":{"status":"complete"},
        "retired":{"status":"rejected"},
    }
    assert can_rollover_state(state) is True


def test_nonterminal_state_cannot_roll_to_next_workload():
    state=ResearchState("issue:44","still running")
    state.action_queue={"pending":{"status":"pending"}}
    assert can_rollover_state(state) is False


def test_no_action_recovery_or_admitted_work_is_idle():
    assert select_controller_work(
        [],
        diagnostic_recoveries={},
        action_queue={},
        admitted_work={},
    ) is None


def test_worker_completion_wake_is_bounded_and_non_recursive():
    text=Path(
        ".github/workflows/samuel-worker-completion-wake.yml"
    ).read_text(encoding="utf-8")
    for name in (
        "Samuel Native GitHub Executor",
        "Samuel Repository Mutation",
        "Samuel Evidence Acquisition",
        "Samuel Diagnostic Recovery",
    ):
        assert f'- "{name}"' in text
    observed=text.split("workflows:",1)[1].split("types:",1)[0]
    assert "Samuel Bootstrap" not in observed
    assert "actions: write" in text
    assert "gh workflow run samuel-bootstrap.yml" in text
    assert '--ref main' in text


def test_worker_authority_stays_narrow():
    repository_worker=Path(
        ".github/workflows/samuel-repository-mutation.yml"
    ).read_text(encoding="utf-8")
    evidence_worker=Path(
        ".github/workflows/samuel-evidence-acquisition.yml"
    ).read_text(encoding="utf-8")
    diagnostic_worker=Path(
        ".github/workflows/samuel-diagnostic-recovery.yml"
    ).read_text(encoding="utf-8")
    assert "actions: write" not in repository_worker
    assert "actions: write" not in evidence_worker
    assert "actions: write" not in diagnostic_worker


def test_bootstrap_waits_for_dispatched_worker_before_terminal_ingestion():
    text=Path(
        ".github/workflows/samuel-bootstrap.yml"
    ).read_text(encoding="utf-8")
    materialize_marker="- name: Materialize dispatched worker run identity"
    wait_marker="- name: Wait for dispatched bounded worker terminal state"
    persist_marker="- name: Persist execution gateway state write"
    terminal_marker="- name: Persist terminal controller artifact"
    assert text.count(materialize_marker)==1
    assert text.count(wait_marker)==1
    assert (
        text.index(persist_marker)
        < text.index(materialize_marker)
        < text.index(wait_marker)
        < text.index(terminal_marker)
    )
    materialize=text.split(materialize_marker,1)[1].split(wait_marker,1)[0]
    assert 'raw.get("status") != "receipt"' in materialize
    assert 'receipt.get("workflow_run_id")' in materialize
    for filename in (
        "samuel-action-run-id.txt",
        "samuel-evidence-run-id.txt",
        "samuel-diagnostic-run-id.txt",
        "samuel-corrective-run-id.txt",
    ):
        assert filename in materialize
    assert "SAMUEL_WORKER_ID=MATERIALIZED" in materialize
    wait=text.split(wait_marker,1)[1].split(terminal_marker,1)[0]
    assert 'actions/runs/$run_id' in wait
    assert 'status" = "completed"' in wait
    assert "SECONDS+360" in wait
    assert "sleep 5" in wait
    assert "SAMUEL_WORKER_WAIT=HARD_STOP timeout" in wait


def test_completed_worker_is_reobserved_before_terminal_ingestion():
    text=Path(
        ".github/workflows/samuel-bootstrap.yml"
    ).read_text(encoding="utf-8")
    wait_marker="- name: Wait for dispatched bounded worker terminal state"
    promote_marker="- name: Promote completed worker receipt to terminal observation"
    terminal_marker="- name: Persist terminal controller artifact"
    assert text.count(promote_marker)==1
    assert (
        text.index(wait_marker)
        < text.index(promote_marker)
        < text.index(terminal_marker)
    )
    promote=text.split(promote_marker,1)[1].split(terminal_marker,1)[0]
    assert "controller run-cycle" in promote
    assert "--event-name workflow_dispatch" in promote
    assert "SAMUEL_REASONING_MODE: OFF" in promote
    assert "action_observation" in promote
    assert "evidence_observation" in promote
    assert "diagnostic_observation" in promote
    assert "corrective_observation" in promote
    assert "controller execute-command" in promote
    assert "samuel-terminal-gateway-result.json" in promote
    terminal=text.split(terminal_marker,1)[1]
    assert "--gateway-result samuel-terminal-gateway-result.json" in terminal
    assert "--gateway-result samuel-execution-gateway-result.json" not in terminal


def test_terminal_persistence_triggers_exactly_one_continuation_wake():
    text=Path(
        ".github/workflows/samuel-bootstrap.yml"
    ).read_text(encoding="utf-8")
    marker="- name: Continue Samuel closed loop after terminal persistence"
    assert text.count(marker)==1
    tail=text.split(marker,1)[1]
    assert "samuel-terminal-state-persist-result.json" in tail
    assert "gh workflow run samuel-bootstrap.yml" in tail
    assert "--ref main" in tail
    assert text.count("gh workflow run samuel-bootstrap.yml")==1
