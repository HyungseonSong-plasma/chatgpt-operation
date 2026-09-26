import pathlib
import tempfile
import unittest
from chatgpt_operation.controller.bootstrap import load_pending, resolve_bootstrap_provider, select_controller_work, BootstrapError


class SamuelBootstrapTests(unittest.TestCase):
    def test_repository_queue_contains_live_qualification(self):
        pending=load_pending("automation/samuel/bootstrap.json")
        self.assertEqual([x.work_id for x in pending], ["issue-44-write-blocker-qualification"])
        self.assertEqual(pending[0].workflow, "samuel-write-blocker-qualification.yml")

    def test_schedule_is_root_trigger_not_plan_injection(self):
        text=pathlib.Path(".github/workflows/samuel-bootstrap.yml").read_text()
        self.assertIn("schedule:", text)
        self.assertIn("actions: write", text)
        self.assertIn("issues: write", text)
        self.assertIn("samuel-bootstrap-ledger", text)
        self.assertIn("samuel-qualification-result.json", text)
        self.assertIn('result.get("http_code") == 403', text)
        self.assertIn('result.get("status") == "BLOCKED"', text)
        self.assertIn('result.get("continuation") == "RETRY"', text)
        self.assertIn("dispatch_and_wait", text)
        self.assertNotIn("plan_json", text)


    def test_pending_work_resolves_repository_provider_from_registry(self):
        work=load_pending("automation/samuel/bootstrap.json")[0]
        provider=resolve_bootstrap_provider(work)
        self.assertEqual(provider.name, "repository-actions")
        self.assertEqual(provider.contract, "github-native-dispatch")

    def test_bootstrap_workflow_cannot_bypass_registry_resolution(self):
        text=pathlib.Path(".github/workflows/samuel-bootstrap.yml").read_text()
        self.assertIn("resolve_bootstrap_provider(work)", text)
        self.assertIn("SAMUEL_BOOTSTRAP_PROVIDER=", text)

    def test_duplicate_work_ids_fail_closed(self):
        with tempfile.NamedTemporaryFile("w+", suffix=".json") as f:
            f.write('{"schema_version":1,"work":[{"work_id":"x","kind":"workflow","workflow":"a"},{"work_id":"x","kind":"workflow","workflow":"b"}]}')
            f.flush()
            with self.assertRaises(BootstrapError):
                load_pending(f.name)


if __name__ == "__main__":
    unittest.main()


def test_open_diagnostic_recovery_preempts_pending_work():
    pending = load_pending("automation/samuel/bootstrap.json")
    selected = select_controller_work(
        pending,
        diagnostic_recoveries={
            "b" * 64: {"status": "resolved"},
            "a" * 64: {"status": "open", "root_cause": None},
        },
    )
    assert selected[0] == "diagnostic"
    assert selected[1]["action_id"] == "a" * 64


def test_pending_work_runs_when_no_open_diagnosis():
    pending = load_pending("automation/samuel/bootstrap.json")
    selected = select_controller_work(
        pending,
        diagnostic_recoveries={"a" * 64: {"status": "resolved"}},
    )
    assert selected == ("pending", pending[0])


def test_admitted_issue_preempts_legacy_pending_work():
    pending = load_pending("automation/samuel/bootstrap.json")
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
