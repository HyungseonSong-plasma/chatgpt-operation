"""Read-only regression tests for draft Samuel Issue #281 scoped work gate."""
from __future__ import annotations

import copy
import unittest

from chatgpt_operation.controller.decisions import DecisionRegistry
from chatgpt_operation.controller.durable_state import encode_state
from chatgpt_operation.controller.issue_ingestion import encode_admission_ledger
from chatgpt_operation.controller.research import ResearchState
from chatgpt_operation.controller.runtime import (
    ControllerTrigger, SamuelController, TriggerKind,
)
from chatgpt_operation.controller.scoped_work_gate import (
    assess_scoped_work_snapshot,
)

REPO = "HyungseonSong-plasma/chatgpt-operation"
SHA = "a" * 40


def ticket(number=281, *, labels=("samuel",)):
    return {
        "number": number,
        "state": "open",
        "title": f"Samuel work {number}",
        "body": f"Approved scoped work {number}",
        "labels": [{"name": value} for value in labels],
    }


def work(issue, *, status="admitted"):
    number = issue["number"]
    return {
        "work_id": f"issue:{number}",
        "issue_number": number,
        "title": issue["title"],
        "body": issue["body"],
        "html_url": f"https://github.com/{REPO}/issues/{number}",
        "status": status,
    }


def fixture(*, admitted=True, active_state=None, extras=()):
    item = ticket()
    issues = [item, *extras]
    ledger = {"issue:281": work(item)} if admitted else {}
    comments = [{"id": 100, "body": encode_admission_ledger(ledger)}]
    if active_state is not None:
        comments.append({
            "id": 101,
            "body": encode_state(ResearchState(active_state, "durable owner")),
        })
    context = {
        "schema_version": 1,
        "repository": REPO,
        "observed_head_sha": SHA,
        "open_issues_complete": True,
        "open_issues": issues,
    }
    return comments, context


def inspect(comments, context, requested="issue:281"):
    return assess_scoped_work_snapshot(
        requested_work_id=requested,
        comments=comments,
        repository_context=context,
    )


class ScopedWorkGateTests(unittest.TestCase):
    def test_clean_single_work_is_candidate_not_dispatch_authority(self):
        comments, context = fixture()
        decision = inspect(comments, context)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.status, "SCOPE_CANDIDATE")
        self.assertIn("Bootstrap binding still required", decision.reason)

    def test_real_281_unlabelled_is_not_admitted(self):
        comments, context = fixture(admitted=False)
        context["open_issues"][0]["labels"] = []
        result = inspect(comments, context)
        self.assertFalse(result.allowed)
        self.assertEqual(result.status, "BLOCKED_SCOPE")

    def test_live_samuel_issue_256_blocks_281(self):
        comments, context = fixture(extras=(ticket(256),))
        decision = inspect(comments, context)
        self.assertFalse(decision.allowed)
        self.assertIn("another open Samuel Issue", decision.reason)

    def test_ledger_competitor_without_open_snapshot_blocks(self):
        comments, context = fixture()
        data = {"issue:281": work(ticket()), "issue:256": work(ticket(256))}
        comments[0]["body"] = encode_admission_ledger(data)
        self.assertIn("another durable work", inspect(comments, context).reason)

    def test_255_durable_state_blocks_even_when_255_issue_closed(self):
        comments, context = fixture(active_state="issue:255")
        decision = inspect(comments, context)
        self.assertEqual(decision.status, "BLOCKED_SCOPE")
        self.assertIn("issue:255", decision.reason)

    def test_same_work_state_remains_scoped_candidate(self):
        comments, context = fixture(active_state="issue:281")
        self.assertEqual(inspect(comments, context).status, "SCOPE_CANDIDATE")

    def test_incomplete_issue_inventory_blocks(self):
        comments, context = fixture()
        context["open_issues_complete"] = False
        self.assertEqual(inspect(comments, context).status, "BLOCKED_SCOPE")

    def test_stale_or_invalid_head_blocks(self):
        comments, context = fixture()
        context["observed_head_sha"] = "main"
        self.assertIn("HEAD", inspect(comments, context).reason)

    def test_forged_admission_identity_blocks(self):
        comments, context = fixture()
        wrong = work(ticket())
        wrong["body"] = "substituted"
        comments[0]["body"] = encode_admission_ledger({"issue:281": wrong})
        self.assertIn("exact identity", inspect(comments, context).reason)

    def test_duplicate_authoritative_admission_comments_block(self):
        comments, context = fixture()
        comments.append({"id": 300, "body": comments[0]["body"]})
        self.assertIn("ambiguous", inspect(comments, context).reason)

    def test_mismatched_work_id_blocks(self):
        comments, context = fixture()
        decision = inspect(comments, context, requested="issue:999")
        self.assertEqual(decision.status, "BLOCKED_SCOPE")

    def test_real_281_conflict_preview_does_not_mutate_input(self):
        comments, context = fixture(active_state="issue:255", extras=(ticket(256),))
        context["open_issues"][0]["labels"] = []
        saved = copy.deepcopy((comments, context))
        result = inspect(comments, context)
        self.assertFalse(result.allowed)
        self.assertEqual((comments, context), saved)

    def test_composition_root_blocks_scope_before_any_write(self):
        comments, context = fixture(active_state="issue:255")
        controller = SamuelController(decisions=DecisionRegistry())
        trigger = ControllerTrigger(
            TriggerKind.WORKFLOW_DISPATCH,
            action="", head_sha=SHA, ref="refs/heads/main",
            executor_ref="main", executor_head_sha=SHA,
        )
        cycle = controller.run_cycle(
            trigger, comments=comments, pending=[],
            repository_context=context, requested_work_id="issue:281",
        )
        self.assertEqual(cycle.selected_work["kind"], "blocked_scope")
        self.assertEqual(cycle.selected_work["work_id"], "issue:281")
        self.assertIsNone(cycle.admission_write)
        self.assertIsNone(cycle.state_write)
        self.assertIsNone(cycle.execution_command)

    def test_composition_root_rejects_conflicting_event_or_legacy_pending(self):
        comments, context = fixture()
        controller = SamuelController(decisions=DecisionRegistry())
        trigger = ControllerTrigger(
            TriggerKind.WORKFLOW_DISPATCH, action="", head_sha=SHA,
            ref="refs/heads/main", executor_ref="main", executor_head_sha=SHA,
        )
        cycle = controller.run_cycle(
            trigger, comments=comments, pending=[],
            issue=ticket(256), repository_context=context,
            requested_work_id="issue:281",
        )
        self.assertEqual(cycle.selected_work["kind"], "blocked_scope")
        self.assertIsNone(cycle.admission_write)


if __name__ == "__main__":
    unittest.main()
