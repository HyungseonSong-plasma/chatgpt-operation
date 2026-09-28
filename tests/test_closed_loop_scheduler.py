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
