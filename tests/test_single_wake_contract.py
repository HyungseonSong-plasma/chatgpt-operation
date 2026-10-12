from pathlib import Path
import unittest

from chatgpt_operation.controller.decisions import DecisionRegistry
from chatgpt_operation.controller.issue_ingestion import decode_admission_ledger
from chatgpt_operation.controller.runtime import (
    ControllerTrigger,
    SamuelController,
    TriggerKind,
)


def controller():
    return SamuelController(
        decisions=DecisionRegistry.load("automation/samuel/decisions.json"),
        reasoning_enabled=False,
    )


def trigger(kind: TriggerKind, action: str = "") -> ControllerTrigger:
    return ControllerTrigger(
        kind,
        action=action,
        head_sha="a" * 40,
        ref="refs/heads/main",
        executor_ref="main",
        executor_head_sha="b" * 40,
    )


def repository_issue(number: int, labels=("samuel",), state="open"):
    return {
        "number": number,
        "title": f"Samuel work {number}",
        "body": f"bounded work for issue {number}",
        "state": state,
        "labels": list(labels),
    }


def event_issue(number: int, labels=("samuel",)):
    return {
        "number": number,
        "title": f"Samuel work {number}",
        "body": f"bounded work for issue {number}",
        "html_url": f"https://github.com/o/r/issues/{number}",
        "labels": [{"name": name} for name in labels],
    }


class SingleWakeContractTests(unittest.TestCase):
    def test_overlapping_issue_and_generic_wakes_collapse_to_same_workload(self):
        snapshot={"open_issues": [repository_issue(209)]}
        first=controller().run_cycle(
            trigger(TriggerKind.ISSUES, "labeled"),
            comments=[],
            pending=[],
            issue=event_issue(209),
            repository_context=snapshot,
        )
        self.assertEqual(
            first.selected_work,
            {"kind": "reasoning_required", "work_id": "issue:209"},
        )
        self.assertIsNotNone(first.admission_write)
        ledger=decode_admission_ledger(first.admission_write["body"])
        self.assertEqual(set(ledger), {"issue:209"})

        comments=[{"id": 7, "body": first.admission_write["body"]}]
        second=controller().run_cycle(
            trigger(TriggerKind.WORKFLOW_DISPATCH),
            comments=comments,
            pending=[],
            repository_context=snapshot,
        )
        self.assertEqual(second.selected_work, first.selected_work)
        self.assertIsNone(second.admission_write)

    def test_unrelated_later_issue_wake_recovers_replaced_admission_wake(self):
        result=controller().run_cycle(
            trigger(TriggerKind.ISSUES, "opened"),
            comments=[],
            pending=[],
            issue=event_issue(999, labels=("bug",)),
            repository_context={
                "open_issues": [
                    repository_issue(209),
                    repository_issue(999, labels=("bug",)),
                ]
            },
        )
        self.assertEqual(
            result.selected_work,
            {"kind": "reasoning_required", "work_id": "issue:209"},
        )
        ledger=decode_admission_ledger(result.admission_write["body"])
        self.assertEqual(set(ledger), {"issue:209"})

    def test_replayed_useful_wake_is_idempotent(self):
        snapshot={"open_issues": [repository_issue(209)]}
        first=controller().run_cycle(
            trigger(TriggerKind.WORKFLOW_DISPATCH),
            comments=[],
            pending=[],
            repository_context=snapshot,
        )
        comments=[{"id": 7, "body": first.admission_write["body"]}]

        replay_one=controller().run_cycle(
            trigger(TriggerKind.WORKFLOW_DISPATCH),
            comments=comments,
            pending=[],
            repository_context=snapshot,
        )
        replay_two=controller().run_cycle(
            trigger(TriggerKind.SCHEDULE),
            comments=comments,
            pending=[],
            repository_context=snapshot,
        )
        self.assertEqual(replay_one.selected_work, replay_two.selected_work)
        self.assertEqual(
            replay_one.selected_work,
            {"kind": "reasoning_required", "work_id": "issue:209"},
        )
        self.assertIsNone(replay_one.admission_write)
        self.assertIsNone(replay_two.admission_write)

    def test_comment_filter_is_outside_bootstrap_concurrency_boundary(self):
        bootstrap=Path(".github/workflows/samuel-bootstrap.yml").read_text(
            encoding="utf-8"
        )
        mediator=Path(".github/workflows/samuel-reasoning-wake.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("group: samuel-bootstrap", bootstrap)
        self.assertIn("cancel-in-progress: false", bootstrap)
        self.assertIn("issues?state=open&per_page=100", bootstrap)
        self.assertNotIn("issue_comment:", bootstrap)
        self.assertNotIn("samuel-reasoning-submission", bootstrap)

        self.assertIn("issue_comment:", mediator)
        self.assertIn("samuel-reasoning-submission", mediator)
        self.assertIn("actions: write", mediator)
        self.assertIn("samuel-bootstrap.yml/dispatches", mediator)
        self.assertNotIn("issues: write", mediator)
        self.assertNotIn("samuel-work-admission", mediator)
        self.assertNotIn("samuel-state", mediator)


if __name__ == "__main__":
    unittest.main()
