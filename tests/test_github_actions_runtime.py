import unittest
from datetime import datetime, timezone

from chatgpt_operation.github.actions_runtime import (
    ActionsRuntimeError,
    dispatch_workflow,
    observe_dispatch_once,
    wait_for_dispatch,
)


class FakeTransport:
    def __init__(self, *, dispatch=(200, None), run=None, runs=None):
        self.dispatch_response = dispatch
        self.run = run
        self.run_sequence = None
        self.runs = list(runs or [])
        self.requests = []

    def get(self, path, *, query=None):
        self.requests.append(("GET", path, query))
        if path.startswith("/actions/workflows/") and path.endswith("/runs"):
            return {"workflow_runs": self.runs}
        if path.startswith("/actions/workflows/"):
            return {
                "id": 260,
                "name": "Issue 26 observation E2E",
                "path": ".github/workflows/issue-26-observation-e2e.yml",
            }
        if path.startswith("/actions/runs/"):
            if self.run_sequence is not None:
                if len(self.run_sequence) > 1:
                    return self.run_sequence.pop(0)
                return self.run_sequence[0]
            return self.run
        raise AssertionError(f"unexpected GET {path}")

    def request(self, method, path, *, payload=None):
        self.requests.append((method, path, payload))
        return self.dispatch_response


def dt(second=0):
    return datetime(2026, 9, 22, 8, 0, second, tzinfo=timezone.utc)


def run(
    *,
    status="completed",
    conclusion="success",
    run_id=9001,
    created_at="2026-09-22T08:00:02Z",
):
    return {
        "id": run_id,
        "workflow_id": 260,
        "event": "workflow_dispatch",
        "head_sha": "77c231b8bcd2f8dc8cb14444323b2ad8d5d91e5e",
        "head_branch": "issue-26-actions-observation",
        "created_at": created_at,
        "run_attempt": 1,
        "status": status,
        "conclusion": conclusion,
    }


class ActionsRuntimeTests(unittest.TestCase):
    def test_dispatch_feature_branch_returns_causal_receipt(self):
        t = FakeTransport(
            dispatch=(
                200,
                {
                    "workflow_run_id": 9001,
                    "run_url": "https://api.github.com/repos/o/r/actions/runs/9001",
                    "html_url": "https://github.com/o/r/actions/runs/9001",
                },
            )
        )
        receipt = dispatch_workflow(
            t,
            workflow="issue-26-observation-e2e.yml",
            ref="issue-26-actions-observation",
            correlation_id="science-exp-26-001",
            inputs={"mode": "smoke"},
            now=lambda: dt(),
        )
        self.assertEqual(receipt["workflow_id"], 260)
        self.assertEqual(receipt["workflow_run_id"], 9001)
        self.assertEqual(receipt["ref"], "issue-26-actions-observation")
        post = [item for item in t.requests if item[0] == "POST"][0]
        self.assertEqual(post[1], "/actions/workflows/260/dispatches")
        self.assertEqual(post[2]["ref"], "issue-26-actions-observation")
        self.assertTrue(post[2]["return_run_details"])
        self.assertEqual(
            post[2]["inputs"]["correlation_id"], "science-exp-26-001"
        )
        self.assertEqual(post[2]["inputs"]["mode"], "smoke")

    def test_direct_run_id_observation_reaches_terminal(self):
        t = FakeTransport(
            dispatch=(200, {"workflow_run_id": 9001}),
            run=run(),
        )
        receipt = dispatch_workflow(
            t,
            workflow="issue-26-observation-e2e.yml",
            ref="issue-26-actions-observation",
            correlation_id="science-exp-26-001",
            now=lambda: dt(),
        )
        result = observe_dispatch_once(
            t,
            receipt,
            expected_head_sha="77c231b8bcd2f8dc8cb14444323b2ad8d5d91e5e",
            now=lambda: dt(10),
        )
        self.assertEqual(result["status"], "MATCHED_TERMINAL")
        self.assertEqual(result["matched_run_ids"], [9001])
        self.assertEqual(result["correlation_id"], "science-exp-26-001")

    def test_empty_legacy_dispatch_fallback_with_observable_correlation_fails_closed(self):
        t = FakeTransport(dispatch=(204, None), runs=[run()])
        receipt = dispatch_workflow(
            t,
            workflow="issue-26-observation-e2e.yml",
            ref="issue-26-actions-observation",
            correlation_id="science-exp-26-001",
            now=lambda: dt(),
        )
        result = observe_dispatch_once(t, receipt, now=lambda: dt(10))
        self.assertEqual(result["status"], "OBSERVATION_INCOMPLETE")

    def test_empty_legacy_dispatch_without_correlation_can_use_complete_enumeration(self):
        t = FakeTransport(dispatch=(204, None), runs=[run()])
        receipt = dispatch_workflow(
            t,
            workflow="issue-26-observation-e2e.yml",
            ref="issue-26-actions-observation",
            correlation_input=None,
            now=lambda: dt(),
        )
        result = observe_dispatch_once(t, receipt, now=lambda: dt(10))
        self.assertEqual(result["status"], "MATCHED_TERMINAL")
        self.assertEqual(result["matched_run_ids"], [9001])

    def test_fallback_duplicate_runs_are_ambiguous(self):
        t = FakeTransport(
            dispatch=(204, None),
            runs=[
                run(run_id=9001),
                run(run_id=9002, created_at="2026-09-22T08:00:03Z"),
            ],
        )
        receipt = dispatch_workflow(
            t,
            workflow="issue-26-observation-e2e.yml",
            ref="issue-26-actions-observation",
            correlation_input=None,
            now=lambda: dt(),
        )
        result = observe_dispatch_once(t, receipt, now=lambda: dt(10))
        self.assertEqual(result["status"], "AMBIGUOUS_MATCH")

    def test_wait_polls_active_until_terminal(self):
        t = FakeTransport(dispatch=(200, {"workflow_run_id": 9001}))
        t.run_sequence = [
            run(status="in_progress", conclusion=None),
            run(status="completed", conclusion="success"),
        ]
        receipt = dispatch_workflow(
            t,
            workflow="issue-26-observation-e2e.yml",
            ref="issue-26-actions-observation",
            correlation_id="science-exp-26-001",
            now=lambda: dt(),
        )
        ticks = iter([0.0, 0.0, 1.0, 1.0])
        result = wait_for_dispatch(
            t,
            receipt,
            expected_head_sha="77c231b8bcd2f8dc8cb14444323b2ad8d5d91e5e",
            timeout_seconds=10,
            poll_interval_seconds=0,
            now=lambda: dt(10),
            monotonic=lambda: next(ticks),
            sleep=lambda _: None,
        )
        self.assertEqual(result["status"], "MATCHED_TERMINAL")

    def test_conflicting_correlation_input_is_rejected_before_dispatch(self):
        t = FakeTransport(dispatch=(200, {"workflow_run_id": 9001}))
        with self.assertRaises(ActionsRuntimeError):
            dispatch_workflow(
                t,
                workflow="issue-26-observation-e2e.yml",
                ref="issue-26-actions-observation",
                correlation_id="expected",
                inputs={"correlation_id": "different"},
                now=lambda: dt(),
            )
        self.assertFalse(any(item[0] == "POST" for item in t.requests))


if __name__ == "__main__":
    unittest.main()
