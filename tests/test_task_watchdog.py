"""Task-driven completion and hourly liveness recovery (#220)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import unittest

from chatgpt_operation.controller.task_watchdog import (
    TaskWatchdogError, decide_task_wake,
)

NOW = datetime(2026, 10, 24, 19, 0, tzinfo=timezone.utc)


def issue(n=92, *, labels=("samuel",), state="open"):
    return {
        "number": n, "state": state, "labels": [{"name": name} for name in labels],
        "title": "Finish this Issue",
    }


def admitted(n=92, status="active"):
    return {f"issue:{n}": {
        "work_id": f"issue:{n}", "issue_number": n, "status": status,
    }}


def run(*, status="completed", age=3600, number=120):
    return {
        "id": number, "status": status,
        "updated_at": (NOW - timedelta(seconds=age)).isoformat(),
    }


def decision(issues=None, admitted_work=None, bootstrap_runs=None, **kwargs):
    return decide_task_wake(
        issues=[issue()] if issues is None else issues,
        admitted_work=admitted() if admitted_work is None else admitted_work,
        bootstrap_runs=[run()] if bootstrap_runs is None else bootstrap_runs,
        now=NOW, **kwargs,
    )


class TaskWatchdogTests(unittest.TestCase):

    def test_stalled_task_restarts_after_one_hour(self):
        observed = decision()
        assert observed.status == "WAKE"
        assert observed.work_ids == ("issue:92",)
        assert "1 hour" in observed.reason


    def test_no_daily_periodic_work_without_task(self):
        assert decision(issues=[]).status == "IDLE"
        assert decision(issues=[issue(labels=("bug",))]).status == "IDLE"
        assert decision(issues=[issue(state="closed")]).status == "IDLE"
        assert decision(issues=[issue(labels=("samuel",), state="closed")]).status == "IDLE"


    def test_recover_first_lost_opt_in_event(self):
        assert decision(admitted_work={}, bootstrap_runs=[]).status == "WAKE"


    def test_current_task_work_is_never_started_twice(self):
        for status in ("in_progress", "queued", "waiting"):
            assert decision(bootstrap_runs=[run(status=status)]).status == "BUSY"


    def test_do_not_restart_early_after_worker_finishes(self):
        assert decision(bootstrap_runs=[run(age=3599)]).status == "DEFER"
        assert decision(bootstrap_runs=[run(age=3600)]).status == "WAKE"


    def test_multiple_bootstrap_runs_use_latest_not_oldest(self):
        assert decision(bootstrap_runs=[run(age=7200), run(age=200, number=121)]).status == "DEFER"
        assert decision(bootstrap_runs=[run(age=7200), run(age=4200, number=121)]).status == "WAKE"


    def test_explicit_block_or_approval_needed_does_not_retry(self):
        for status in ("blocked", "revision_required", "complete"):
            assert decision(admitted_work=admitted(status=status)).status == "PAUSED"


    def test_mixed_blocked_and_open_only_restarts_open_work(self):
        all_work = {**admitted(92, "blocked"), **admitted(93, "active")}
        observed = decision(issues=[issue(92), issue(93)],
                            admitted_work=all_work)
        assert observed.status == "WAKE"
        assert observed.work_ids == ("issue:93",)


    def test_incomplete_issue_or_active_run_scan_hard_stops(self):
        with self.assertRaisesRegex(TaskWatchdogError, "incomplete"):
            decision(complete_issue_scan=False)
        with self.assertRaisesRegex(TaskWatchdogError, "incomplete"):
            decision(complete_active_run_scan=False)


    def test_duplicate_issue_or_ledger_identity_mismatch_hard_stops(self):
        with self.assertRaisesRegex(TaskWatchdogError, "duplicated"):
            decision(issues=[issue(), issue()])
        bad = admitted()
        bad["issue:92"]["issue_number"] = 93
        with self.assertRaisesRegex(TaskWatchdogError, "mismatch"):
            decision(admitted_work=bad)


    def test_future_run_time_hard_stops(self):
        with self.assertRaisesRegex(TaskWatchdogError, "future"):
            decision(bootstrap_runs=[run(age=-3600)])


    def test_unknown_status_or_malformed_run_hard_stops(self):
        with self.assertRaisesRegex(TaskWatchdogError, "lifecycle"):
            decision(admitted_work=admitted(status="fantasy"))
        with self.assertRaisesRegex(TaskWatchdogError, "run state"):
            decision(bootstrap_runs=[run(status="not-real")])
        with self.assertRaisesRegex(TaskWatchdogError, "timestamp"):
            decision(bootstrap_runs=[{"id": 1, "status": "completed", "updated_at": None}])


    def test_interval_must_be_one_hour_or_longer(self):
        with self.assertRaisesRegex(TaskWatchdogError, "shorter"):
            decision(recovery_seconds=300)


    def test_same_input_deterministic_receipt(self):
        assert decision().to_document() == decision().to_document()


    def test_bootstrap_daily_cron_removed_and_task_continuation_preserved(self):
        boot = Path(".github/workflows/samuel-bootstrap.yml").read_text()
        assert "20 13 * * *" not in boot
        assert "schedule:" not in boot.split("jobs:", 1)[0]
        assert "- name: Continue Samuel closed loop after terminal persistence" in boot
        assert "gh workflow run samuel-bootstrap.yml" in boot


    def test_watchdog_workflow_hourly_only_resumes_admitted_work(self):
        config = Path(".github/workflows/samuel-task-watchdog.yml").read_text()
        assert "0 * * * *" in config
        assert "samuel_task_watchdog.py" in config
        assert "if [ \"$decision\" = \"WAKE\" ]; then" in config
        assert "gh workflow run samuel-bootstrap.yml" in config
        assert "SAMUEL_WATCHDOG=$decision no dispatch" in config
        assert "samuel-task-recovery" in config
        assert "actions: write" in config
