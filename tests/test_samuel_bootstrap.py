import pathlib
import tempfile
import unittest

from chatgpt_operation.controller.bootstrap import (
    BootstrapError,
    BootstrapKind,
    BootstrapWork,
    load_pending,
    resolve_bootstrap_provider,
    select_controller_work,
)


def synthetic_pending():
    return [
        BootstrapWork(
            "legacy-qualification",
            BootstrapKind.WORKFLOW,
            "samuel-write-blocker-qualification.yml",
        )
    ]


class SamuelBootstrapTests(unittest.TestCase):
    def test_repository_queue_retires_one_shot_qualification(self):
        pending=load_pending("automation/samuel/bootstrap.json")
        self.assertEqual(pending, [])

    def test_schedule_is_root_trigger_not_plan_injection(self):
        text=pathlib.Path(".github/workflows/samuel-bootstrap.yml").read_text()
        self.assertIn("schedule:", text)
        self.assertIn("actions: write", text)
        self.assertIn("issues: write", text)
        self.assertNotIn("dispatch_and_wait", text)
        self.assertIn("controller run-cycle", text)
        self.assertIn("controller execute-command", text)
        self.assertNotIn("plan_json", text)

    def test_bootstrap_exposes_bounded_repository_manifest_to_reasoning(self):
        text=pathlib.Path(".github/workflows/samuel-bootstrap.yml").read_text()
        self.assertIn('["git","ls-files"]',text)
        self.assertIn('"tracked_paths":tracked_paths',text)
        self.assertIn('"tracked_paths_truncated":tracked_paths_truncated',text)
        self.assertIn('"workflow_files":workflow_files',text)
        self.assertIn('"mutation_policy":mutation_policy',text)
        self.assertIn(
            '"automation/samuel/repository-mutation-policy.json"',
            text,
        )
        self.assertIn('".github/workflows/"',text)
        self.assertIn("relevant_tracked_paths[:500]",text)
        self.assertIn(
            "tracked_paths_truncated=len(relevant_tracked_paths)>500",
            text,
        )

    def test_workflow_has_no_direct_evidence_or_diagnostic_dispatch_runtime(self):
        text=pathlib.Path(".github/workflows/samuel-bootstrap.yml").read_text()
        self.assertNotIn("dispatch_and_wait",text)
        self.assertNotIn("dispatch_workflow(",text)
        self.assertNotIn("observe_dispatch_once(",text)
        self.assertNotIn("resume_evidence_dispatch_intent",text)
        self.assertNotIn("resume_dispatched_evidence",text)
        self.assertNotIn("resume_diagnostic_dispatch_intent",text)
        self.assertNotIn("resume_dispatched_diagnostic",text)
        self.assertEqual(text.count("controller execute-command"),2)
        self.assertIn(
            "- name: Observe completed bounded worker through composition root",
            text,
        )

    def test_legacy_work_still_resolves_repository_provider_outside_runtime(self):
        work=synthetic_pending()[0]
        provider=resolve_bootstrap_provider(work)
        self.assertEqual(provider.name, "repository-actions")
        self.assertEqual(provider.contract, "github-native-dispatch")

    def test_duplicate_work_ids_fail_closed(self):
        with tempfile.NamedTemporaryFile("w+", suffix=".json") as f:
            f.write('{"schema_version":1,"work":[{"work_id":"x","kind":"workflow","workflow":"a"},{"work_id":"x","kind":"workflow","workflow":"b"}]}')
            f.flush()
            with self.assertRaises(BootstrapError):
                load_pending(f.name)


if __name__ == "__main__":
    unittest.main()


def test_open_diagnostic_recovery_preempts_pending_work():
    selected = select_controller_work(
        synthetic_pending(),
        diagnostic_recoveries={
            "b" * 64: {"status": "resolved"},
            "a" * 64: {"status": "open", "root_cause": None},
        },
    )
    assert selected[0] == "diagnostic"
    assert selected[1]["action_id"] == "a" * 64


def test_selector_can_surface_legacy_pending_work_for_explicit_rejection():
    pending = synthetic_pending()
    selected = select_controller_work(
        pending,
        diagnostic_recoveries={"a" * 64: {"status": "resolved"}},
    )
    assert selected == ("pending", pending[0])


def test_admitted_issue_preempts_legacy_pending_work():
    pending = synthetic_pending()
    admitted = {
        "issue:44": {
            "work_id": "issue:44",
            "issue_number": 44,
            "title": "Samuel OS",
            "body": "work",
            "html_url": "https://github.com/o/r/issues/44",
            "status": "admitted",
        }
    }
    selected = select_controller_work(pending, admitted_work=admitted)
    assert selected[0] == "issue"
    assert selected[1]["work_id"] == "issue:44"


def test_durable_action_preempts_admitted_issue():
    admitted = {"issue:44": {"work_id": "issue:44", "status": "admitted"}}
    action_id = "a" * 64
    selected = select_controller_work(
        [],
        action_queue={action_id: {"status": "pending", "plan": {"typed": True}}},
        admitted_work=admitted,
    )
    assert selected[0] == "action"
    assert selected[1]["action_id"] == action_id


def test_admitted_issue_identity_mismatch_fails_closed():
    with unittest.TestCase().assertRaises(BootstrapError):
        select_controller_work(
            [],
            admitted_work={"issue:44": {"work_id": "issue:45", "status": "admitted"}},
        )
