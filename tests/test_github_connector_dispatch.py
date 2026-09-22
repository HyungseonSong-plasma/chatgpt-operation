import unittest

from datetime import datetime, timezone

from chatgpt_operation.github.actions_runtime import observe_dispatch_once
from chatgpt_operation.github.connector_dispatch import (
    ConnectorDispatchError,
    build_dispatch_action_request,
    normalize_dispatch_action_result,
)


class DirectRunTransport:
    def get(self, path, *, query=None):
        if path == "/actions/runs/31001":
            return {
                "id": 31001,
                "workflow_id": 31,
                "event": "workflow_dispatch",
                "head_sha": "abc123",
                "head_branch": "main",
                "created_at": "2026-09-22T22:15:01Z",
                "run_attempt": 1,
                "status": "completed",
                "conclusion": "success",
            }
        raise AssertionError(f"unexpected GET {path}")


class ConnectorDispatchContractTests(unittest.TestCase):
    def test_issue_309_request_preserves_supplied_inputs(self):
        inputs = {
            "issue": "309",
            "sequence": "01",
            "task": "manifest",
            "manifest": "automation/manifests/refactors/Issue_309_refactor01.json",
            "base_sha": "b1d581c56642f26ba7fed45a7be30395d57125d2",
        }
        request = build_dispatch_action_request(
            repository="HyungseonSong-plasma/moose-test-repo",
            workflow="refactor.yml",
            ref="issue-309-standard-moose-sheath-refactor",
            inputs=inputs,
            correlation_id="issue-309-refactor01",
            correlation_input=None,
            expected_head_sha=inputs["base_sha"],
        )
        self.assertEqual(request["inputs"], inputs)
        self.assertEqual(
            request["ref"], "issue-309-standard-moose-sheath-refactor"
        )
        self.assertTrue(request["return_run_details"])
        self.assertNotIn("token", request)

    def test_workflow_inputs_are_not_filtered_by_secret_like_names(self):
        inputs = {"token": "consumer-owned-value", "mode": "smoke"}
        request = build_dispatch_action_request(
            repository="o/r",
            workflow="experiment.yml",
            ref="feature",
            inputs=inputs,
        )
        self.assertEqual(request["inputs"], inputs)

    def test_explicit_correlation_input_is_injected_only_when_requested(self):
        request = build_dispatch_action_request(
            repository="o/r",
            workflow="experiment.yml",
            ref="feature",
            inputs={"mode": "smoke"},
            correlation_id="exp-1",
            correlation_input="correlation_id",
        )
        self.assertEqual(request["inputs"]["mode"], "smoke")
        self.assertEqual(request["inputs"]["correlation_id"], "exp-1")

    def test_conflicting_correlation_input_fails_closed(self):
        with self.assertRaises(ConnectorDispatchError):
            build_dispatch_action_request(
                repository="o/r",
                workflow="experiment.yml",
                ref="feature",
                inputs={"correlation_id": "other"},
                correlation_id="expected",
                correlation_input="correlation_id",
            )

    def test_direct_run_details_normalize_to_observation_receipt(self):
        request = build_dispatch_action_request(
            repository="o/r",
            workflow="refactor.yml",
            ref="main",
            correlation_id="req-31",
            expected_head_sha="abc123",
        )
        receipt = normalize_dispatch_action_result(
            request,
            {
                "workflow_id": 31,
                "workflow_name": "Governed refactor entrypoint",
                "workflow_path": ".github/workflows/refactor.yml",
                "dispatch_status": 200,
                "requested_at": "2026-09-22T22:15:00Z",
                "workflow_run_id": 31001,
                "run_url": "https://api.github.com/repos/o/r/actions/runs/31001",
                "html_url": "https://github.com/o/r/actions/runs/31001",
            },
        )
        self.assertEqual(receipt["workflow_run_id"], 31001)
        self.assertEqual(receipt["expected_head_sha"], "abc123")
        self.assertEqual(receipt["correlation_id"], "req-31")

    def test_empty_dispatch_details_keep_deterministic_fallback_receipt(self):
        request = build_dispatch_action_request(
            repository="o/r",
            workflow="refactor.yml",
            ref="main",
            correlation_id="req-31",
            correlation_input=None,
        )
        receipt = normalize_dispatch_action_result(
            request,
            {
                "workflow_id": 31,
                "workflow_name": "Governed refactor entrypoint",
                "workflow_path": ".github/workflows/refactor.yml",
                "dispatch_status": 204,
                "requested_at": "2026-09-22T22:15:00Z",
                "workflow_run_id": None,
                "run_url": None,
                "html_url": None,
            },
        )
        self.assertIsNone(receipt["workflow_run_id"])
        self.assertEqual(receipt["workflow_id"], 31)
        self.assertEqual(receipt["ref"], "main")

    def test_connector_receipt_flows_into_existing_observer(self):
        request = build_dispatch_action_request(
            repository="o/r",
            workflow="refactor.yml",
            ref="main",
            correlation_id="req-31",
            expected_head_sha="abc123",
        )
        receipt = normalize_dispatch_action_result(
            request,
            {
                "workflow_id": 31,
                "workflow_name": "Governed refactor entrypoint",
                "workflow_path": ".github/workflows/refactor.yml",
                "dispatch_status": 200,
                "requested_at": "2026-09-22T22:15:00Z",
                "workflow_run_id": 31001,
                "run_url": "https://api.github.com/repos/o/r/actions/runs/31001",
                "html_url": "https://github.com/o/r/actions/runs/31001",
            },
        )
        result = observe_dispatch_once(
            DirectRunTransport(),
            receipt,
            expected_head_sha=receipt["expected_head_sha"],
            now=lambda: datetime(2026, 9, 22, 22, 15, 10, tzinfo=timezone.utc),
        )
        self.assertEqual(result["status"], "MATCHED_TERMINAL")
        self.assertEqual(result["matched_run_ids"], [31001])

    def test_connector_must_not_return_raw_credential_material(self):
        request = build_dispatch_action_request(
            repository="o/r",
            workflow="refactor.yml",
            ref="main",
        )
        with self.assertRaises(ConnectorDispatchError):
            normalize_dispatch_action_result(
                request,
                {
                    "workflow_id": 31,
                    "dispatch_status": 200,
                    "requested_at": "2026-09-22T22:15:00Z",
                    "workflow_run_id": 31001,
                    "access_token": "secret",
                },
            )


if __name__ == "__main__":
    unittest.main()
