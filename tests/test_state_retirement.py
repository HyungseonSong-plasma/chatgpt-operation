import unittest

from chatgpt_operation.controller.decisions import DecisionRegistry
from chatgpt_operation.controller.durable_state import (
    DurableStateError,
    can_rollover_state,
    decode_state,
    encode_state,
    retire_quiescent_state,
    require_fresh_write,
)
from chatgpt_operation.controller.issue_ingestion import encode_admission_ledger
from chatgpt_operation.controller.research import ResearchState
from chatgpt_operation.controller.runtime import (
    ControllerTrigger,
    SamuelController,
    TriggerKind,
)


def work(number, *, status="admitted", observability=False):
    body = (
        "This issue is telemetry/observability only."
        if observability
        else "Bounded actionable workload."
    )
    return {
        "work_id": f"issue:{number}",
        "issue_number": number,
        "title": f"Issue {number}",
        "body": body,
        "html_url": f"https://github.com/o/r/issues/{number}",
        "status": status,
    }


def open_issue(number):
    return {
        "number": number,
        "title": f"Issue {number}",
        "body": "Bounded actionable workload.",
        "state": "open",
        "labels": ["samuel"],
    }


def controller():
    return SamuelController(
        decisions=DecisionRegistry.load("automation/samuel/decisions.json"),
        reasoning_enabled=False,
    )


def trigger():
    return ControllerTrigger(
        TriggerKind.WORKFLOW_DISPATCH,
        head_sha="a" * 40,
        ref="refs/heads/main",
        executor_ref="main",
        executor_head_sha="b" * 40,
    )


class StateRetirementTests(unittest.TestCase):
    def test_closed_quiescent_state_retires_then_yields_on_next_cycle(self):
        old = ResearchState("issue:43", "observability", revision=7)
        admitted = {
            "issue:43": work(
                43, status="reasoning_required", observability=True
            ),
            "issue:210": work(210),
        }
        comments = [
            {"id": 1, "body": encode_admission_ledger(admitted)},
            {"id": 2, "body": encode_state(old)},
        ]
        context = {
            "open_issues": [open_issue(210)],
            "open_issues_complete": True,
        }

        first = controller().run_cycle(
            trigger(), comments=comments, pending=[], repository_context=context
        )
        self.assertEqual(first.selected_work["kind"], "state_retirement")
        self.assertEqual(first.selected_work["work_id"], "issue:43")
        self.assertIsNotNone(first.state_write)
        self.assertIsNotNone(first.admission_write)

        retired = decode_state(first.state_write["body"])
        self.assertEqual(retired.revision, 8)
        self.assertEqual(retired.retirement.status, "retired")
        self.assertEqual(retired.retirement.issue_number, 43)
        self.assertEqual(retired.retirement.workload_mode, "observability_only")
        self.assertTrue(can_rollover_state(retired))

        next_comments = [
            {"id": 1, "body": first.admission_write["body"]},
            {"id": 2, "body": first.state_write["body"]},
        ]
        second = controller().run_cycle(
            trigger(),
            comments=next_comments,
            pending=[],
            repository_context=context,
        )
        self.assertEqual(
            second.selected_work,
            {"kind": "reasoning_required", "work_id": "issue:210"},
        )

    def test_empty_state_cannot_be_overwritten_without_retirement_proof(self):
        current = ResearchState("issue:43", "old", revision=4)
        proposed = ResearchState("issue:210", "new", revision=1)
        self.assertFalse(can_rollover_state(current))
        with self.assertRaisesRegex(DurableStateError, "different research state"):
            require_fresh_write(current, proposed)

        retired = retire_quiescent_state(
            current, issue_number=43, workload_mode="observability_only"
        )
        self.assertTrue(can_rollover_state(retired))
        require_fresh_write(retired, proposed)

    def test_incomplete_open_issue_snapshot_cannot_authorize_retirement(self):
        state = ResearchState("issue:43", "old", revision=4)
        comments = [
            {
                "id": 1,
                "body": encode_admission_ledger(
                    {
                        "issue:43": work(
                            43,
                            status="reasoning_required",
                            observability=True,
                        ),
                        "issue:210": work(210),
                    }
                ),
            },
            {"id": 2, "body": encode_state(state)},
        ]
        result = controller().run_cycle(
            trigger(),
            comments=comments,
            pending=[],
            repository_context={
                "open_issues": [open_issue(210)],
                "open_issues_complete": False,
            },
        )
        self.assertEqual(result.selected_work["kind"], "blocked")
        self.assertIsNone(result.state_write)

    def test_pending_dispatched_suspended_and_open_recovery_block_retirement(self):
        for status in ("pending", "dispatched", "suspended"):
            state = ResearchState(
                "issue:43",
                "old",
                revision=2,
                action_queue={"a": {"status": status}},
            )
            with self.assertRaisesRegex(DurableStateError, "retirement requires"):
                retire_quiescent_state(
                    state,
                    issue_number=43,
                    workload_mode="observability_only",
                )

        recovering = ResearchState(
            "issue:43",
            "old",
            revision=2,
            diagnostic_recoveries={"a": {"status": "open"}},
        )
        with self.assertRaisesRegex(DurableStateError, "retirement requires"):
            retire_quiescent_state(
                recovering,
                issue_number=43,
                workload_mode="observability_only",
            )

    def test_terminal_history_rollover_remains_unchanged(self):
        terminal = ResearchState(
            "issue:44",
            "done",
            revision=5,
            action_queue={"done": {"status": "complete"}},
        )
        self.assertTrue(can_rollover_state(terminal))
        self.assertIsNone(terminal.retirement)

    def test_retirement_round_trip_is_typed_and_replay_safe(self):
        state = ResearchState("issue:43", "old", revision=3)
        retired = retire_quiescent_state(
            state, issue_number=43, workload_mode="actionable"
        )
        restored = decode_state(encode_state(retired))
        self.assertEqual(restored.retirement, retired.retirement)
        self.assertEqual(restored.revision, 4)
        self.assertTrue(can_rollover_state(restored))
        with self.assertRaisesRegex(DurableStateError, "retirement requires"):
            retire_quiescent_state(
                restored,
                issue_number=43,
                workload_mode="actionable",
            )


if __name__ == "__main__":
    unittest.main()
