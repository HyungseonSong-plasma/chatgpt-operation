import unittest

from chatgpt_operation.github.actions_observation import evaluate


class ObservationConsumerReuseTests(unittest.TestCase):
    def snapshot(self, status="in_progress", conclusion=None):
        return {
            "request": {
                "workflow": "issue-26-observation-e2e.yml",
                "event": "workflow_dispatch",
                "correlation_id": "science-exp-26-001",
                "head_sha": "abc123",
                "ref": "refs/heads/issue-26-actions-observation",
                "requested_at": "2026-09-22T03:00:00Z",
                "visibility_grace_seconds": 60,
            },
            "observation": {
                "observed_at": "2026-09-22T03:00:20Z",
                "enumeration_complete": True,
                "runs": [{
                    "run_id": 26001,
                    "workflow": "issue-26-observation-e2e.yml",
                    "event": "workflow_dispatch",
                    "correlation_id": "science-exp-26-001",
                    "head_sha": "abc123",
                    "ref": "refs/heads/issue-26-actions-observation",
                    "created_at": "2026-09-22T03:00:05Z",
                    "run_attempt": 1,
                    "status": status,
                    "conclusion": conclusion,
                }],
            },
        }

    def test_science_consumer_observes_execution_without_claiming_acceptance(self):
        result = evaluate(self.snapshot(status="completed", conclusion="success"))
        self.assertEqual(result["status"], "MATCHED_TERMINAL")
        self.assertNotIn("scientific_validity", result)
        self.assertNotIn("experiment_acceptance", result)

    def test_controller_consumer_maps_active_run_without_moving_policy_into_skill(self):
        result = evaluate(self.snapshot())
        self.assertEqual(result["status"], "MATCHED_ACTIVE")
        controller_state = {
            "MATCHED_ACTIVE": "WAIT_EXTERNAL",
            "MATCHED_TERMINAL": "VALIDATION_READY",
        }[result["status"]]
        self.assertEqual(controller_state, "WAIT_EXTERNAL")
        self.assertNotIn("controller_state", result)


if __name__ == "__main__":
    unittest.main()
