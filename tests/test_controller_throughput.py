from __future__ import annotations

import unittest

from chatgpt_operation.controller.throughput import ThroughputError, evaluate


def snapshot() -> dict:
    return {
        "schema_version": 1,
        "authority": {
            "desired_state": "ACTIVE",
            "durable_state": "ACTIVE",
            "synchronized": True,
        },
        "validation": {
            "required": False,
            "launch_expected": False,
            "exact_head_runs": 0,
            "active_runs": 0,
            "terminal_runs": 0,
            "lock_scope": "NONE",
            "locked_resources": [],
        },
        "max_lanes": 2,
        "tasks": [],
    }


class ControllerThroughputTests(unittest.TestCase):
    def test_pause_resume_authority_must_be_durable(self):
        data = snapshot()
        data["authority"]["durable_state"] = "PAUSED"
        data["authority"]["synchronized"] = False
        result = evaluate(data)
        self.assertEqual(result["status"], "SYNC_AUTHORITY")
        self.assertFalse(result["can_progress"])

    def test_missing_exact_head_run_is_fix_not_wait(self):
        data = snapshot()
        data["validation"].update(
            {"required": True, "launch_expected": True}
        )
        result = evaluate(data)
        self.assertEqual(result["status"], "MISSING_VALIDATION_ROUTE")
        self.assertEqual(
            result["next_action"], "repair_or_explicitly_trigger_validation_route"
        )

    def test_global_active_lock_blocks_mutation_burst(self):
        data = snapshot()
        data["validation"].update(
            {
                "required": True,
                "launch_expected": True,
                "exact_head_runs": 1,
                "active_runs": 1,
                "lock_scope": "GLOBAL",
            }
        )
        data["tasks"] = [
            {"id": "next", "ready": True, "needs_mutation": True, "resources": ["branch:b"]}
        ]
        result = evaluate(data)
        self.assertEqual(result["status"], "WAIT_EXTERNAL")

    def test_scoped_lock_allows_independent_lane(self):
        data = snapshot()
        data["validation"].update(
            {
                "required": True,
                "launch_expected": True,
                "exact_head_runs": 1,
                "active_runs": 1,
                "lock_scope": "SCOPED",
                "locked_resources": ["branch:a"],
            }
        )
        data["tasks"] = [
            {"id": "blocked", "ready": True, "needs_mutation": True, "resources": ["branch:a"]},
            {"id": "free", "ready": True, "needs_mutation": True, "resources": ["branch:b"]},
        ]
        result = evaluate(data)
        self.assertEqual(result["status"], "BURST_ADVANCE")
        self.assertEqual(result["selected_tasks"], ["free"])

    def test_two_disjoint_ready_tasks_form_parallel_burst(self):
        data = snapshot()
        data["tasks"] = [
            {"id": "a", "ready": True, "needs_mutation": True, "resources": ["branch:a"]},
            {"id": "b", "ready": True, "needs_mutation": True, "resources": ["branch:b"]},
        ]
        result = evaluate(data)
        self.assertEqual(result["status"], "PARALLEL_ADVANCE")
        self.assertEqual(result["selected_tasks"], ["a", "b"])

    def test_conflicting_mutation_resources_are_not_parallelized(self):
        data = snapshot()
        data["tasks"] = [
            {"id": "a", "ready": True, "needs_mutation": True, "resources": ["main"]},
            {"id": "b", "ready": True, "needs_mutation": True, "resources": ["main"]},
        ]
        result = evaluate(data)
        self.assertEqual(result["selected_tasks"], ["a"])

    def test_read_only_task_can_progress_during_scoped_lock(self):
        data = snapshot()
        data["validation"].update(
            {
                "required": True,
                "launch_expected": True,
                "exact_head_runs": 1,
                "active_runs": 1,
                "lock_scope": "SCOPED",
                "locked_resources": ["branch:a"],
            }
        )
        data["tasks"] = [
            {"id": "inspect", "ready": True, "needs_mutation": False, "resources": ["branch:a"]}
        ]
        result = evaluate(data)
        self.assertEqual(result["selected_tasks"], ["inspect"])

    def test_invalid_run_accounting_fails_closed(self):
        data = snapshot()
        data["validation"].update(
            {"exact_head_runs": 1, "active_runs": 1, "terminal_runs": 1}
        )
        with self.assertRaises(ThroughputError):
            evaluate(data)


if __name__ == "__main__":
    unittest.main()
