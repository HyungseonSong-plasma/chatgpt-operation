"""No-write qualification for native GitHub scoped wake readbacks."""
from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
import unittest

from chatgpt_operation.controller.durable_state import encode_state
from chatgpt_operation.controller.issue_ingestion import encode_admission_ledger
from chatgpt_operation.controller.research import ResearchState
from chatgpt_operation.controller.scoped_wake_native import evaluate_live_scoped_wake

REPO = "HyungseonSong-plasma/chatgpt-operation"
HEAD = "a" * 40
RUN_ID = 8787
POLICY_PATH = "automation/samuel/agent-child-scoped-preview-281.json"


def parent(number=281, *, labels=("samuel",)):
    return {
        "id": 5000 + number,
        "number": number,
        "state": "open",
        "title": f"Samuel task {number}",
        "body": f"Approved implementation {number}",
        "labels": [{"name": x} for x in labels],
        "html_url": f"https://github.com/{REPO}/issues/{number}",
    }


def item(issue):
    number = issue["number"]
    return {
        "work_id": f"issue:{number}",
        "issue_number": number,
        "title": issue["title"],
        "body": issue["body"],
        "html_url": issue["html_url"],
        "status": "admitted",
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
        "id": RUN_ID,
        "run_attempt": 1,
        "event": "workflow_dispatch",
        "path": ".github/workflows/samuel-bootstrap.yml",
        "head_branch": "main",
        "head_sha": HEAD,
        "status": "in_progress",
        "conclusion": None,
        "repository": {"full_name": REPO},
    }


class NativeFake:
    repository = REPO

    def __init__(self, *, config=None):
        self.run = workflow_run()
        self.head = HEAD
        self.config = scope() if config is None else config
        self.issues = [parent()]
        self.comments = [{
            "id": 110,
            "body": encode_admission_ledger({"issue:281": item(self.issues[0])}),
        }]
        self.calls = []
        self.change_run_after_first = False
        self.change_issues_after_first = False

    def get(self, path, *, query=None):
        self.calls.append((path, copy.deepcopy(query)))
        if path == f"/actions/runs/{RUN_ID}":
            value = copy.deepcopy(self.run)
            if self.change_run_after_first and sum(
                x[0] == path for x in self.calls
            ) > 1:
                value["status"] = "completed"
            return value
        if path == "/branches/main":
            return {"commit": {"sha": self.head}}
        if path == "/contents/" + POLICY_PATH:
            if query != {"ref": HEAD}:
                raise AssertionError("policy MUST be exact HEAD")
            return {
                "type": "file",
                "path": POLICY_PATH,
                "encoding": "base64",
                "content": base64.b64encode(
                    json.dumps(self.config).encode("utf-8")
                ).decode("ascii"),
            }
        if path in ("/issues", "/issues/44/comments"):
            if query is None:
                raise AssertionError("pagination must be explicit")
            if path == "/issues":
                values = copy.deepcopy(self.issues)
                if self.change_issues_after_first and sum(
                    x[0] == path for x in self.calls
                ) > 1:
                    values.append(parent(282))
            else:
                values = copy.deepcopy(self.comments)
            index = (int(query["page"]) - 1) * 100
            return values[index:index+100]
        raise AssertionError("unexpected native API request: " + path)


def evaluate(native):
    return evaluate_live_scoped_wake(
        native, repository=REPO, run_id=RUN_ID, run_attempt=1,
    )


class LiveScopedWakeTests(unittest.TestCase):
    def test_real_checked_in_scope_defaults_disabled(self):
        source = json.loads(Path(POLICY_PATH).read_text("utf-8"))
        self.assertEqual(source, scope(enabled=False))
        self.assertEqual(evaluate(NativeFake(config=source)).status, "BLOCKED_SCOPE")

    def test_native_authenticated_preview_is_never_executable(self):
        native = NativeFake()
        result = evaluate(native)
        self.assertEqual(result.status, "SCOPE_CANDIDATE")
        self.assertEqual(result.work_id, "issue:281")
        self.assertFalse(result.dispatch_authorized)
        self.assertIsNone(result.admission_write)
        self.assertIsNone(result.state_write)
        self.assertIsNone(result.execution_command)
        self.assertEqual(native.calls[0][0], f"/actions/runs/{RUN_ID}")
        self.assertTrue(all(x[0].startswith("/") for x in native.calls))

    def test_unlabelled_task_issue_does_not_admit(self):
        native = NativeFake()
        native.issues = [parent(labels=())]
        native.comments[0]["body"] = encode_admission_ledger({})
        self.assertEqual(evaluate(native).status, "BLOCKED_SCOPE")

    def test_existing_256_open_samuel_work_blocks(self):
        native = NativeFake()
        native.issues.append(parent(256))
        result = evaluate(native)
        self.assertEqual(result.status, "BLOCKED_SCOPE")
        self.assertIn("another open Samuel Issue", result.reason)

    def test_existing_255_global_owner_blocks(self):
        native = NativeFake()
        native.comments.append({
            "id": 111, "body": encode_state(ResearchState("issue:255", "blocked owner")),
        })
        result = evaluate(native)
        self.assertEqual(result.status, "BLOCKED_SCOPE")
        self.assertIn("issue:255", result.reason)

    def test_forged_policy_scope_blocks(self):
        native = NativeFake()
        native.config["work_id"] = "issue:256"
        self.assertEqual(evaluate(native).status, "BLOCKED_SCOPE")

    def test_main_head_mismatch_blocks(self):
        native = NativeFake()
        native.head = "b" * 40
        self.assertEqual(evaluate(native).status, "BLOCKED_SCOPE")

    def test_run_source_mismatch_blocks(self):
        native = NativeFake()
        native.run["event"] = "issues"
        self.assertEqual(evaluate(native).status, "BLOCKED_SCOPE")

    def test_changed_run_during_readback_blocks(self):
        native = NativeFake()
        native.change_run_after_first = True
        self.assertEqual(evaluate(native).status, "BLOCKED_SCOPE")

    def test_changed_open_inventory_during_readback_blocks(self):
        native = NativeFake()
        native.change_issues_after_first = True
        self.assertEqual(evaluate(native).status, "BLOCKED_SCOPE")

    def test_duplicate_open_issue_record_blocks(self):
        native = NativeFake()
        native.issues.append(copy.deepcopy(native.issues[0]))
        self.assertEqual(evaluate(native).status, "BLOCKED_SCOPE")

    def test_corrupted_policy_base64_blocks(self):
        class Corrupted(NativeFake):
            def get(self, path, *, query=None):
                if path == "/contents/" + POLICY_PATH:
                    return {
                        "path": POLICY_PATH, "type": "file",
                        "encoding": "base64", "content": "**",
                    }
                return super().get(path, query=query)
        self.assertEqual(evaluate(Corrupted()).status, "BLOCKED_SCOPE")

    def test_scope_run_id_unsupported_bool_blocks(self):
        native = NativeFake()
        result = evaluate_live_scoped_wake(
            native, repository=REPO, run_id=True, run_attempt=1,
        )
        self.assertEqual(result.status, "BLOCKED_SCOPE")
        self.assertEqual(native.calls, [])

    def test_reader_cannot_mutate_through_native_transport(self):
        native = NativeFake()
        evaluate(native)
        self.assertFalse(hasattr(native, "request"))
        self.assertTrue(native.calls)
        self.assertTrue(all(x[0].startswith("/") for x in native.calls))

    def test_terminal_no_work_defaults_blocked(self):
        native = NativeFake()
        native.config["enabled"] = False
        result = evaluate(native)
        self.assertEqual(result.status, "BLOCKED_SCOPE")
        self.assertIsNone(result.execution_command)


if __name__ == "__main__":
    unittest.main()
