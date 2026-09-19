from __future__ import annotations

import copy
import unittest

from chatgpt_operation.controller.lifecycle import LifecycleError, evaluate


def snapshot() -> dict:
    return {
        "schema_version": 1,
        "controller_id": "refactor-controller",
        "scope_id": "refactor-label-v1|sentinel-157|active-pr-v1",
        "observation_id": "cycle-1",
        "explicit_pause": False,
        "primary_work_scan": {
            "complete": True,
            "open_count": 0,
            "method": "search",
            "evidence_id": "primary-1",
        },
        "confirmation_work_scan": {
            "complete": True,
            "open_count": 0,
            "method": "fanout",
            "evidence_id": "confirm-1",
        },
        "active_work_scan": {
            "complete": True,
            "open_count": 0,
            "method": "prs",
            "evidence_id": "active-1",
        },
        "sentinel": {
            "complete": True,
            "terminal": True,
            "method": "issue",
            "evidence_id": "sentinel-1",
        },
        "previous_candidate": None,
    }


class ControllerLifecycleTests(unittest.TestCase):
    def test_transient_empty_incomplete_scan_never_completes(self):
        data = snapshot()
        data["primary_work_scan"]["complete"] = False
        result = evaluate(data)
        self.assertEqual(result["status"], "WAIT")
        self.assertFalse(result["can_disable"])

    def test_disagreeing_zero_and_nonzero_scans_wait(self):
        data = snapshot()
        data["confirmation_work_scan"]["open_count"] = 2
        result = evaluate(data)
        self.assertEqual(result["status"], "WAIT")
        self.assertFalse(result["can_disable"])

    def test_open_work_blocks_completion(self):
        data = snapshot()
        data["primary_work_scan"]["open_count"] = 1
        data["confirmation_work_scan"]["open_count"] = 1
        result = evaluate(data)
        self.assertEqual(result["status"], "ACTIVE")
        self.assertFalse(result["can_disable"])

    def test_active_pr_blocks_completion(self):
        data = snapshot()
        data["active_work_scan"]["open_count"] = 1
        result = evaluate(data)
        self.assertEqual(result["status"], "ACTIVE")
        self.assertFalse(result["can_disable"])

    def test_open_sentinel_blocks_completion(self):
        data = snapshot()
        data["sentinel"]["terminal"] = False
        result = evaluate(data)
        self.assertEqual(result["status"], "ACTIVE")
        self.assertFalse(result["can_disable"])

    def test_first_terminal_observation_only_creates_candidate(self):
        result = evaluate(snapshot())
        self.assertEqual(result["status"], "TERMINAL_CANDIDATE")
        self.assertFalse(result["can_disable"])
        self.assertIsNotNone(result["candidate"])

    def test_later_matching_cycle_verifies_completion(self):
        first = evaluate(snapshot())
        data = snapshot()
        data["observation_id"] = "cycle-2"
        data["previous_candidate"] = first["candidate"]
        result = evaluate(data)
        self.assertEqual(result["status"], "VERIFIED_COMPLETE")
        self.assertTrue(result["can_disable"])

    def test_same_cycle_cannot_self_confirm(self):
        first = evaluate(snapshot())
        data = snapshot()
        data["previous_candidate"] = first["candidate"]
        result = evaluate(data)
        self.assertEqual(result["status"], "TERMINAL_CANDIDATE")
        self.assertFalse(result["can_disable"])

    def test_mismatched_candidate_requires_new_confirmation(self):
        data = snapshot()
        data["previous_candidate"] = {"token": "stale", "observation_id": "cycle-0"}
        result = evaluate(data)
        self.assertEqual(result["status"], "TERMINAL_CANDIDATE")
        self.assertFalse(result["can_disable"])

    def test_explicit_pause_is_distinct_from_completion(self):
        data = snapshot()
        data["explicit_pause"] = True
        del data["primary_work_scan"]
        del data["confirmation_work_scan"]
        del data["active_work_scan"]
        del data["sentinel"]
        result = evaluate(data)
        self.assertEqual(result["status"], "PAUSED")
        self.assertTrue(result["can_disable"])

    def test_independent_scan_methods_are_required(self):
        data = snapshot()
        data["confirmation_work_scan"]["method"] = "search"
        with self.assertRaises(LifecycleError):
            evaluate(data)

    def test_scope_change_invalidates_previous_candidate(self):
        first = evaluate(snapshot())
        data = snapshot()
        data["observation_id"] = "cycle-2"
        data["scope_id"] = "different-terminal-policy-v2"
        data["previous_candidate"] = first["candidate"]
        result = evaluate(data)
        self.assertEqual(result["status"], "TERMINAL_CANDIDATE")
        self.assertFalse(result["can_disable"])

    def test_candidate_does_not_depend_on_evidence_ids(self):
        first = evaluate(snapshot())
        data = copy.deepcopy(snapshot())
        data["observation_id"] = "cycle-2"
        data["primary_work_scan"]["evidence_id"] = "primary-2"
        data["confirmation_work_scan"]["evidence_id"] = "confirm-2"
        data["previous_candidate"] = first["candidate"]
        result = evaluate(data)
        self.assertEqual(result["status"], "VERIFIED_COMPLETE")


if __name__ == "__main__":
    unittest.main()
