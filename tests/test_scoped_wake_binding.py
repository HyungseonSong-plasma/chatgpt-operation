"""Draft-only trusted run identity and repository-owned work-scope tests."""
from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path
import unittest

from chatgpt_operation.controller.durable_state import encode_state
from chatgpt_operation.controller.issue_ingestion import encode_admission_ledger
from chatgpt_operation.controller.research import ResearchState
from chatgpt_operation.controller.scoped_wake_binding import (
    evaluate_repository_owned_wake,
)

REPO = "HyungseonSong-plasma/chatgpt-operation"
HEAD = "a" * 40
RUN = 9001


def issue(number=281, labels=("samuel",)):
    return {
        "number": number,
        "title": "Approved task",
        "body": "Approved, bounded work",
        "state": "open",
        "labels": [{"name": label} for label in labels],
    }


def admitted(item):
    n = item["number"]
    return {
        "work_id": f"issue:{n}",
        "issue_number": n,
        "title": item["title"],
        "body": item["body"],
        "status": "admitted",
        "html_url": f"https://github.com/{REPO}/issues/{n}",
    }


def scope(*, enabled=True):
    return {
        "schema_version": 1,
        "repository": REPO,
        "workflow": "samuel-bootstrap.yml",
        "ref": "main",
        "work_id": "issue:281",
        "mode": "preview_only",
        "enabled": enabled,
    }


def workflow_run():
    return {
        "id": RUN,
        "run_attempt": 1,
        "event": "workflow_dispatch",
        "path": ".github/workflows/samuel-bootstrap.yml",
        "head_branch": "main",
        "head_sha": HEAD,
        "status": "in_progress",
        "conclusion": None,
        "repository": {"full_name": REPO},
    }


class ReadOnlyGitHub:
    def __init__(self, value=None):
        self.run = workflow_run() if value is None else value
        self.reads = []

    def get_run(self, run_id):
        self.reads.append(run_id)
        return copy.deepcopy(self.run)


def setup(*, labels=("samuel",), extra_issues=(), active=None):
    item = issue(labels=labels)
    work = {"issue:281": admitted(item)} if "samuel" in labels else {}
    comments = [{"id": 10, "body": encode_admission_ledger(work)}]
    if active is not None:
        comments.append({
            "id": 20, "body": encode_state(ResearchState(active, "existing owner")),
        })
    context = {
        "repository": REPO,
        "observed_head_sha": HEAD,
        "open_issues_complete": True,
        "open_issues": [item, *extra_issues],
    }
    return comments, context


def inspect_wake(*, policy=None, reader=None, comments=None, context=None,
                 run_id=RUN, attempt=1):
    if comments is None or context is None:
        comments, context = setup()
    return evaluate_repository_owned_wake(
        scope=scope() if policy is None else policy,
        run_reader=ReadOnlyGitHub() if reader is None else reader,
        run_id=run_id,
        run_attempt=attempt,
        comments=comments,
        repository_context=context,
    )


class RepositoryOwnedScopeTests(unittest.TestCase):
    def test_checked_in_policy_is_draft_disabled(self):
        p = json.loads(Path(
            "automation/samuel/agent-child-scoped-preview-281.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(p, scope(enabled=False))
        self.assertEqual(inspect_wake(policy=p).status, "BLOCKED_SCOPE")

    def test_single_trusted_work_is_only_read_only_candidate(self):
        reader = ReadOnlyGitHub()
        result = inspect_wake(reader=reader)
        self.assertEqual(result.status, "SCOPE_CANDIDATE")
        self.assertEqual(result.work_id, "issue:281")
        self.assertFalse(result.dispatch_authorized)
        self.assertIsNone(result.admission_write)
        self.assertIsNone(result.state_write)
        self.assertIsNone(result.execution_command)
        self.assertEqual(reader.reads, [RUN])

    def test_no_scheduler_selected_work_parameter(self):
        self.assertNotIn(
            "requested_work_id",
            inspect.signature(evaluate_repository_owned_wake).parameters,
        )

    def test_foreign_repository_or_unexpected_workflow_is_denied(self):
        for key, value in (
            ("repository", "somebody/else"),
            ("workflow", "other.yml"),
            ("ref", "dev"),
            ("mode", "live"),
            ("work_id", "issue:256"),
        ):
            p = scope()
            p[key] = value
            with self.subTest(field=key):
                self.assertEqual(inspect_wake(policy=p).status, "BLOCKED_SCOPE")

    def test_unknown_policy_fields_denied(self):
        p = scope()
        p["external_override"] = "issue:281"
        self.assertEqual(inspect_wake(policy=p).status, "BLOCKED_SCOPE")

    def test_source_run_provenance_fail_closed(self):
        variations = [
            ("event", "issues"),
            ("path", ".github/workflows/other.yml"),
            ("head_branch", "other"),
            ("head_sha", "b" * 40),
            ("status", "completed"),
            ("conclusion", "success"),
            ("run_attempt", 2),
            ("id", RUN + 1),
        ]
        for key, value in variations:
            fake = workflow_run()
            fake[key] = value
            with self.subTest(field=key):
                self.assertEqual(
                    inspect_wake(reader=ReadOnlyGitHub(fake)).status,
                    "BLOCKED_SCOPE",
                )

    def test_native_run_repository_identity_must_match(self):
        fake = workflow_run()
        fake["repository"]["full_name"] = "elsewhere/repo"
        self.assertEqual(
            inspect_wake(reader=ReadOnlyGitHub(fake)).status, "BLOCKED_SCOPE",
        )

    def test_invalid_run_identity_denied(self):
        for run_id, attempt in ((True, 1), (0, 1), (RUN, False), (RUN, 0)):
            with self.subTest(run_id=run_id, attempt=attempt):
                self.assertEqual(
                    inspect_wake(run_id=run_id, attempt=attempt).status,
                    "BLOCKED_SCOPE",
                )

    def test_external_gitHub_reader_failure_denied(self):
        class FailingRead:
            def get_run(self, run_id):
                raise OSError("no authenticated source")
        self.assertEqual(
            inspect_wake(reader=FailingRead()).status, "BLOCKED_SCOPE",
        )

    def test_missing_281_admission_denied(self):
        comments, context = setup(labels=())
        self.assertEqual(
            inspect_wake(comments=comments, context=context).status,
            "BLOCKED_SCOPE",
        )

    def test_issue_256_competition_denied(self):
        comments, context = setup(extra_issues=(issue(256),))
        result = inspect_wake(comments=comments, context=context)
        self.assertEqual(result.status, "BLOCKED_SCOPE")
        self.assertIn("another open Samuel Issue", result.reason)

    def test_closed_255_owning_global_state_denied(self):
        comments, context = setup(active="issue:255")
        result = inspect_wake(comments=comments, context=context)
        self.assertEqual(result.status, "BLOCKED_SCOPE")
        self.assertIn("issue:255", result.reason)

    def test_source_context_head_drift_denied(self):
        comments, context = setup()
        context["observed_head_sha"] = "b" * 40
        self.assertEqual(
            inspect_wake(comments=comments, context=context).status,
            "BLOCKED_SCOPE",
        )

    def test_admission_ledger_conflict_does_not_write(self):
        comments, context = setup()
        others = {"issue:281": admitted(issue()), "issue:256": admitted(issue(256))}
        comments[0]["body"] = encode_admission_ledger(others)
        snapshot = copy.deepcopy((comments, context))
        result = inspect_wake(comments=comments, context=context)
        self.assertEqual(result.status, "BLOCKED_SCOPE")
        self.assertEqual((comments, context), snapshot)
        self.assertIsNone(result.state_write)


class ScopedWakeRootTests(unittest.TestCase):
    def make_root(self):
        from chatgpt_operation.controller.decisions import DecisionRegistry
        from chatgpt_operation.controller.runtime import SamuelController
        return SamuelController(decisions=DecisionRegistry())

    def trigger(self, *, sha=HEAD, event=None):
        from chatgpt_operation.controller.runtime import ControllerTrigger, TriggerKind
        return ControllerTrigger(
            event or TriggerKind.WORKFLOW_DISPATCH,
            action="", head_sha=sha, ref="refs/heads/main",
            executor_ref="main", executor_head_sha=sha,
        )

    def run_scope_cycle(self, *, comments=None, context=None, policy=None,
            expected_work_id=None, trigger=None, reader=None):
        if comments is None or context is None:
            comments, context = setup()
        return self.make_root().run_cycle(
            self.trigger() if trigger is None else trigger,
            comments=comments,
            pending=[],
            repository_context=context,
            requested_work_id=expected_work_id,
            scoped_repository_policy=scope() if policy is None else policy,
            scoped_native_run_reader=ReadOnlyGitHub() if reader is None else reader,
            scoped_native_run_id=RUN,
            scoped_native_run_attempt=1,
        )

    def test_trusted_run_scoped_root_is_preview_only(self):
        cycle = self.run_scope_cycle()
        self.assertEqual(cycle.selected_work["kind"], "scoped_preview")
        self.assertEqual(cycle.selected_work["work_id"], "issue:281")
        self.assertFalse(cycle.selected_work["dispatch_authorized"])
        self.assertEqual(cycle.selected_work["verified_run_id"], RUN)
        self.assertIsNone(cycle.admission_write)
        self.assertIsNone(cycle.state_write)
        self.assertIsNone(cycle.execution_command)
        self.assertIsNone(cycle.issue_planning)

    def test_disabled_policy_root_blocks_without_write(self):
        cycle = self.run_scope_cycle(policy=scope(enabled=False))
        self.assertEqual(cycle.selected_work["kind"], "blocked_scope")
        self.assertIsNone(cycle.admission_write)
        self.assertIsNone(cycle.state_write)
        self.assertIsNone(cycle.execution_command)

    def test_caller_selected_work_id_cannot_override_repository_policy(self):
        cycle = self.run_scope_cycle(expected_work_id="issue:256")
        self.assertEqual(cycle.selected_work["kind"], "blocked_scope")
        self.assertIsNone(cycle.admission_write)

    def test_stale_trusted_sha_blocks_before_child_work(self):
        cycle = self.run_scope_cycle(trigger=self.trigger(sha="b" * 40))
        self.assertEqual(cycle.selected_work["kind"], "blocked_scope")
        self.assertIsNone(cycle.execution_command)

    def test_255_and_256_conflicts_block_root_without_state_write(self):
        comments, context = setup(
            active="issue:255", extra_issues=(issue(256),),
        )
        cycle = self.run_scope_cycle(comments=comments, context=context)
        self.assertEqual(cycle.selected_work["kind"], "blocked_scope")
        self.assertIsNone(cycle.state_write)
        self.assertIsNone(cycle.admission_write)
        self.assertIsNone(cycle.execution_command)

    def test_no_policy_but_run_evidence_is_rejected(self):
        comments, context = setup()
        cycle = self.make_root().run_cycle(
            self.trigger(),
            comments=comments, pending=[],
            repository_context=context,
            scoped_native_run_reader=ReadOnlyGitHub(),
            scoped_native_run_id=RUN,
            scoped_native_run_attempt=1,
        )
        self.assertEqual(cycle.selected_work["kind"], "blocked_scope")
        self.assertIsNone(cycle.state_write)
        self.assertIsNone(cycle.execution_command)


if __name__ == "__main__":
    unittest.main()
